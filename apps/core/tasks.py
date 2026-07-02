import json
from urllib.parse import unquote

import apprise
import posthog
import requests
from django.conf import settings

from apps.core.model_typing import (
    FeedbackDoesNotExist,
    ProfileDoesNotExist,
    agent_api_key_task_fields,
    feedback_objects,
    feedback_task_fields,
    model_id,
    profile_objects,
    profile_state_fields,
    profile_state_transition_objects,
    profile_user,
)
from apps.core.models import Feedback
from rowset.utils import get_rowset_logger

logger = get_rowset_logger(__name__)


def _format_feedback_apprise_body(feedback: Feedback) -> str:
    feedback_fields = feedback_task_fields(feedback)
    submitter = (
        profile_user(feedback_fields.profile).email if feedback_fields.profile else "Anonymous"
    )
    lines = [
        f"Source: {feedback_fields.get_source_display()}",
        f"User: {submitter}",
    ]

    if feedback_fields.agent_api_key:
        agent_api_key_fields = agent_api_key_task_fields(feedback_fields.agent_api_key)
        lines.append(
            f"Agent API key: {agent_api_key_fields.name} ({agent_api_key_fields.key_prefix})"
        )
    if feedback_fields.page:
        lines.append(f"Page: {feedback_fields.page}")

    metadata = feedback_fields.metadata if isinstance(feedback_fields.metadata, dict) else {}
    rowset_row_url = metadata.get("rowset_row_url")
    if rowset_row_url:
        lines.append(f"Rowset row: {rowset_row_url}")

    if metadata:
        context_keys = ", ".join(sorted(str(key) for key in metadata if key != "rowset_row_url"))
        if context_keys:
            lines.append(f"Context keys: {context_keys}")

    lines.extend(["", feedback_fields.feedback])
    return "\n".join(lines)


def notify_feedback_apprise(feedback_id: int) -> str:
    urls = tuple(getattr(settings, "ROWSET_FEEDBACK_APPRISE_URLS", ()))
    if not urls:
        return "Apprise feedback notifications are not configured."

    try:
        feedback = (
            feedback_objects().select_related("profile__user", "agent_api_key").get(id=feedback_id)
        )
    except FeedbackDoesNotExist:
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
            error=str(exc),
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


def try_create_posthog_alias(
    profile_id: int,
    cookies: dict[str, object],
    source_function: str | None = None,
) -> str | None:
    if not settings.POSTHOG_API_KEY:
        return "PostHog API key not found."

    base_log_data = {
        "profile_id": profile_id,
        "cookies": cookies,
        "source_function": source_function,
    }

    profile = profile_objects().get(id=profile_id)
    email = profile_user(profile).email

    base_log_data["email"] = email
    base_log_data["profile_id"] = profile_id

    posthog_cookie = cookies.get(f"ph_{settings.POSTHOG_API_KEY}_posthog")
    if not isinstance(posthog_cookie, str) or not posthog_cookie:
        logger.warning("[Try Create Posthog Alias] No PostHog cookie found.", **base_log_data)
        return f"No PostHog cookie found for profile {profile_id}."
    base_log_data["posthog_cookie"] = posthog_cookie

    logger.info("[Try Create Posthog Alias] Setting PostHog alias", **base_log_data)

    cookie_dict = json.loads(unquote(posthog_cookie))
    frontend_distinct_id = cookie_dict.get("distinct_id")

    if frontend_distinct_id:
        posthog.alias(frontend_distinct_id, email)
        posthog.alias(frontend_distinct_id, str(profile_id))

    logger.info("[Try Create Posthog Alias] Set PostHog alias", **base_log_data)


def track_event(
    profile_id: int,
    event_name: str,
    properties: dict[str, object],
    source_function: str | None = None,
) -> str:
    if not settings.POSTHOG_API_KEY:
        return "PostHog API key not found."

    base_log_data = {
        "profile_id": profile_id,
        "event_name": event_name,
        "properties": properties,
        "source_function": source_function,
    }

    try:
        profile = profile_objects().get(id=profile_id)
    except ProfileDoesNotExist:
        logger.error("[TrackEvent] Profile not found.", **base_log_data)
        return f"Profile with id {profile_id} not found."

    profile_state = profile_state_fields(profile)
    user = profile_user(profile)
    posthog.capture(
        event=event_name,
        distinct_id=str(model_id(profile)),
        properties={
            "profile_id": model_id(profile),
            "email": user.email,
            "current_state": profile_state.state,
            **properties,
        },
    )

    logger.info("[TrackEvent] Tracked event", **base_log_data)

    return f"Tracked event {event_name} for profile {profile_id}"


def track_activation_event(
    profile_id: int,
    event_name: str,
    properties: dict[str, object] | None = None,
    source_function: str | None = None,
) -> str:
    if not settings.POSTHOG_API_KEY:
        return "PostHog API key not found."

    base_log_data = {
        "profile_id": profile_id,
        "event_name": event_name,
        "property_keys": sorted((properties or {}).keys()),
        "source_function": source_function,
    }

    try:
        profile = profile_objects().select_related("user").get(id=profile_id)
    except ProfileDoesNotExist:
        logger.error("[ActivationTracking] Profile not found.", **base_log_data)
        return f"Profile with id {profile_id} not found."

    profile_state = profile_state_fields(profile)
    user = profile_user(profile)
    posthog.capture(
        event=event_name,
        distinct_id=str(model_id(profile)),
        properties={
            "profile_id": model_id(profile),
            "current_state": profile_state.state,
            "$set": {
                "email": user.email,
                "username": user.username,
            },
            **(properties or {}),
        },
    )

    logger.info("[ActivationTracking] Tracked event", **base_log_data)
    return f"Tracked activation event {event_name} for profile {profile_id}"


def track_state_change(
    profile_id: int,
    from_state: str,
    to_state: str,
    metadata: dict[str, object] | None = None,
    source_function: str | None = None,
) -> str:
    base_log_data = {
        "profile_id": profile_id,
        "from_state": from_state,
        "to_state": to_state,
        "metadata": metadata,
        "source_function": source_function,
    }

    try:
        profile = profile_objects().get(id=profile_id)
    except ProfileDoesNotExist:
        logger.error("[TrackStateChange] Profile not found.", **base_log_data)
        return f"Profile with id {profile_id} not found."

    if from_state != to_state:
        logger.info("[TrackStateChange] Tracking state change", **base_log_data)
        profile_state_transition_objects().create(
            profile=profile,
            from_state=from_state,
            to_state=to_state,
            backup_profile_id=profile_id,
            metadata=metadata,
        )
        profile_state_fields(profile).state = to_state
        profile.save(update_fields=["state"])

    return f"Tracked state change from {from_state} to {to_state} for profile {profile_id}"
