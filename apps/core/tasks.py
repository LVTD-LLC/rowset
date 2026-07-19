import apprise
import posthog
import requests
from django.conf import settings

from apps.core.analytics import ROWSET_ACCOUNT_DELETED
from apps.core.attribution import attribution_event_properties
from apps.core.models import Feedback, Profile
from rowset.utils import get_rowset_logger

logger = get_rowset_logger(__name__)
_POSTHOG_DURABLE_EVENTS = frozenset(
    {
        "rowset_signup_completed",
        "rowset_agent_setup_completed",
        "rowset_checkout_started",
        "rowset_subscription_started",
        "rowset_subscription_cancellation_requested",
        "rowset_subscription_ended",
        "rowset_payment_failed",
    }
)


def _format_feedback_apprise_body(feedback: Feedback) -> str:
    submitter = feedback.profile.user.email if feedback.profile else "Anonymous"
    lines = [
        f"Source: {feedback.get_source_display()}",
        f"User: {submitter}",
    ]

    if feedback.agent_api_key:
        lines.append(
            f"Agent API key: {feedback.agent_api_key.name} ({feedback.agent_api_key.key_prefix})"
        )
    if feedback.page:
        lines.append(f"Page: {feedback.page}")

    metadata = feedback.metadata if isinstance(feedback.metadata, dict) else {}
    rowset_row_url = metadata.get("rowset_row_url")
    if rowset_row_url:
        lines.append(f"Rowset row: {rowset_row_url}")

    if metadata:
        context_keys = ", ".join(sorted(str(key) for key in metadata if key != "rowset_row_url"))
        if context_keys:
            lines.append(f"Context keys: {context_keys}")

    lines.extend(["", feedback.feedback])
    return "\n".join(lines)


def notify_feedback_apprise(feedback_id: int) -> str:
    urls = tuple(getattr(settings, "ROWSET_FEEDBACK_APPRISE_URLS", ()))
    if not urls:
        return "Apprise feedback notifications are not configured."

    try:
        feedback = Feedback.objects.select_related("profile__user", "agent_api_key").get(
            id=feedback_id
        )
    except Feedback.DoesNotExist:
        logger.warning(
            "Feedback notification skipped because feedback was not found",
            feedback_id=feedback_id,
        )
        return f"Feedback {feedback_id} was not found."

    apprise_client = apprise.Apprise()
    added_url_count = 0
    for url in urls:
        if apprise_client.add(url):
            added_url_count += 1

    if added_url_count == 0:
        logger.warning(
            "Feedback notification skipped because no Apprise URLs could be parsed",
            feedback_id=feedback_id,
            configured_url_count=len(urls),
        )
        return "No Apprise feedback notification URLs could be parsed."

    try:
        sent = apprise_client.notify(
            title=getattr(settings, "ROWSET_FEEDBACK_APPRISE_TITLE", "New Rowset feedback"),
            body=_format_feedback_apprise_body(feedback),
        )
    except Exception as exc:
        logger.error(
            "Failed to send Apprise feedback notification",
            feedback_id=feedback_id,
            error_type=type(exc).__name__,
            exc_info=True,
        )
        return f"Failed to send Apprise feedback notification for feedback {feedback_id}."

    if not sent:
        logger.warning(
            "Apprise feedback notification returned a failure result",
            feedback_id=feedback_id,
            configured_url_count=len(urls),
        )
        return f"Apprise feedback notification failed for feedback {feedback_id}."

    return f"Sent Apprise feedback notification for feedback {feedback_id}."


def add_email_to_buttondown(email, tag):
    if not settings.BUTTONDOWN_API_KEY:
        return "Buttondown API key not found."

    data = {
        "email_address": str(email),
        "metadata": {"source": tag},
        "tags": [tag],
        "referrer_url": "https://rowset.lvtd.dev",
        "type": "regular",
    }

    r = requests.post(
        "https://api.buttondown.email/v1/subscribers",
        headers={"Authorization": f"Token {settings.BUTTONDOWN_API_KEY}"},
        json=data,
    )

    return r.json()


def track_activation_event(
    profile_id: int,
    event_name: str,
    properties: dict | None = None,
    source_function: str = None,
    session_id: str | None = None,
) -> str:
    if not settings.POSTHOG_API_KEY:
        return "PostHog API key not found."

    base_log_data = {
        "profile_id": profile_id,
        "event_name": event_name,
        "properties_count": len(properties or {}),
        "source_function": source_function,
    }

    try:
        profile = Profile.objects.select_related("user").get(id=profile_id)
    except Profile.DoesNotExist:
        logger.error("posthog.activation.failed", **base_log_data, error_type="ProfileNotFound")
        return f"Profile with id {profile_id} not found."

    posthog.capture(
        event_name,
        distinct_id=str(profile.id),
        properties={
            "event_version": 1,
            "environment": settings.ENVIRONMENT,
            "profile_id": profile.id,
            "current_state": profile.state,
            "$set": {
                "email": profile.user.email,
                "username": profile.user.username,
            },
            **attribution_event_properties(profile.marketing_attribution),
            **(properties or {}),
            **({"$session_id": session_id} if session_id else {}),
        },
    )
    if event_name in _POSTHOG_DURABLE_EVENTS:
        posthog.flush(timeout_seconds=5)

    logger.info("posthog.activation.completed", **base_log_data, outcome="success")
    return f"Tracked activation event {event_name} for profile {profile_id}"


def track_account_deleted_event(
    profile_id: int,
    current_state: str,
    session_id: str | None = None,
) -> str:
    """Capture deletion after commit using values snapshotted before the profile was removed."""
    if not settings.POSTHOG_API_KEY:
        return "PostHog API key not found."

    properties = {
        "event_version": 1,
        "environment": settings.ENVIRONMENT,
        "profile_id": profile_id,
        "current_state": current_state,
        **({"$session_id": session_id} if session_id else {}),
    }
    posthog.capture(
        ROWSET_ACCOUNT_DELETED,
        distinct_id=str(profile_id),
        properties=properties,
    )
    posthog.flush(timeout_seconds=5)
    logger.info(
        "posthog.activation.completed",
        profile_id=profile_id,
        event_name=ROWSET_ACCOUNT_DELETED,
        properties_count=0,
        source_function="delete_account",
        outcome="success",
    )
    return f"Tracked account deletion event for profile {profile_id}"


def track_state_change(
    profile_id: int,
    from_state: str,
    to_state: str,
    metadata: dict = None,
    source_function: str = None,
) -> None:
    from apps.core.models import Profile, ProfileStateTransition

    base_log_data = {
        "profile_id": profile_id,
        "from_state": from_state,
        "to_state": to_state,
        "metadata_count": len(metadata or {}),
        "source_function": source_function,
    }

    try:
        profile = Profile.objects.get(id=profile_id)
    except Profile.DoesNotExist:
        logger.error("profile.state_change.failed", **base_log_data, error_type="ProfileNotFound")
        return f"Profile with id {profile_id} not found."

    if from_state != to_state:
        logger.info("profile.state_change.completed", **base_log_data, outcome="success")
        ProfileStateTransition.objects.create(
            profile=profile,
            from_state=from_state,
            to_state=to_state,
            backup_profile_id=profile_id,
            metadata=metadata,
        )
        profile.state = to_state
        profile.save(update_fields=["state"])

    return f"Tracked state change from {from_state} to {to_state} for profile {profile_id}"
