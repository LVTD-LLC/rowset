from typing import Any

from django.conf import settings
from django.db import transaction
from django_q.tasks import async_task

from apps.core.model_typing import agent_api_key_id, profile_id
from apps.core.models import AgentApiKey, Profile

ROWSET_SIGNUP_COMPLETED = "rowset_signup_completed"
ROWSET_AGENT_API_KEY_CREATED = "rowset_agent_api_key_created"
ROWSET_AGENT_SETUP_PROMPT_COPIED = "rowset_agent_setup_prompt_copied"
ROWSET_GET_USER_INFO_SUCCEEDED = "rowset_get_user_info_succeeded"
ROWSET_DATASET_CREATED = "rowset_dataset_created"
ROWSET_DATASET_ROW_MUTATED = "rowset_dataset_row_mutated"


def agent_api_key_tracking_properties(agent_api_key: AgentApiKey | None) -> dict[str, Any]:
    if agent_api_key is None:
        return {
            "agent_api_key_present": False,
            "agent_api_key_id": None,
            "agent_api_key_access_level": "",
        }
    return {
        "agent_api_key_present": True,
        "agent_api_key_id": agent_api_key_id(agent_api_key),
        "agent_api_key_access_level": agent_api_key.access_level,
    }


def track_activation_event(
    profile: Profile,
    event_name: str,
    properties: dict[str, Any] | None = None,
    *,
    source_function: str | None = None,
) -> str:
    if not settings.POSTHOG_API_KEY:
        return "PostHog API key not found."

    resolved_profile_id = profile_id(profile)
    event_properties = properties or {}

    def enqueue_event() -> None:
        async_task(
            "core.tasks.track_activation_event",
            profile_id=resolved_profile_id,
            event_name=event_name,
            properties=event_properties,
            source_function=source_function,
            group="Track Activation Event",
        )

    connection = transaction.get_connection()
    if connection.in_atomic_block:
        transaction.on_commit(enqueue_event)
    else:
        enqueue_event()

    return f"Queued activation event {event_name} for profile {resolved_profile_id}"
