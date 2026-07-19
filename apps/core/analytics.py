from typing import Any

from django.conf import settings
from django.db import transaction
from django_q.tasks import async_task
from structlog.contextvars import get_contextvars

from apps.core.models import AgentApiKey, Profile
from rowset.logging_context import validate_correlation_id

ROWSET_SIGNUP_COMPLETED = "rowset_signup_completed"
ROWSET_AGENT_API_KEY_CREATED = "rowset_agent_api_key_created"
ROWSET_AGENT_SETUP_PROMPT_COPIED = "rowset_agent_setup_prompt_copied"
ROWSET_AGENT_SETUP_COMPLETED = "rowset_agent_setup_completed"
ROWSET_GET_USER_INFO_SUCCEEDED = "rowset_get_user_info_succeeded"
ROWSET_DATASET_CREATED = "rowset_dataset_created"
ROWSET_DATASET_ROW_MUTATED = "rowset_dataset_row_mutated"
ROWSET_CHECKOUT_STARTED = "rowset_checkout_started"
ROWSET_SUBSCRIPTION_STARTED = "rowset_subscription_started"
ROWSET_SUBSCRIPTION_CANCELLATION_REQUESTED = "rowset_subscription_cancellation_requested"
ROWSET_SUBSCRIPTION_ENDED = "rowset_subscription_ended"
ROWSET_PAYMENT_FAILED = "rowset_payment_failed"
ROWSET_TRIAL_REWARD_CLAIMED = "rowset_trial_reward_claimed"
ROWSET_ACCOUNT_DELETED = "rowset_account_deleted"
ROWSET_AGENT_API_KEY_REVOKED = "rowset_agent_api_key_revoked"
ROWSET_DATASET_EXPORTED = "rowset_dataset_exported"


def agent_api_key_tracking_properties(agent_api_key: AgentApiKey | None) -> dict[str, Any]:
    if agent_api_key is None:
        return {
            "agent_api_key_present": False,
            "agent_api_key_id": None,
            "agent_api_key_access_level": "",
        }
    return {
        "agent_api_key_present": True,
        "agent_api_key_id": agent_api_key.id,
        "agent_api_key_access_level": agent_api_key.access_level,
    }


def track_activation_event(
    profile: Profile,
    event_name: str,
    properties: dict[str, Any] | None = None,
    *,
    source_function: str | None = None,
    session_id: str | None = None,
) -> str:
    if not settings.POSTHOG_API_KEY:
        return "PostHog API key not found."

    profile_id = profile.id
    session_id = validate_correlation_id(session_id or get_contextvars().get("sessionId"))
    event_properties = properties or {}

    def enqueue_event() -> None:
        async_task(
            "apps.core.tasks.track_activation_event",
            profile_id=profile_id,
            event_name=event_name,
            properties=event_properties,
            source_function=source_function,
            session_id=session_id,
            group="Track Activation Event",
        )

    connection = transaction.get_connection()
    if connection.in_atomic_block:
        transaction.on_commit(enqueue_event)
    else:
        enqueue_event()

    return f"Queued activation event {event_name} for profile {profile_id}"
