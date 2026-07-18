from collections.abc import Callable

from django.db import DatabaseError
from django.http import HttpRequest, HttpResponse

from apps.core.services import mark_profile_setup_completed
from rowset.utils import get_rowset_logger

logger = get_rowset_logger(__name__)


class AgentSetupCompletionMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)
        agent_api_key = getattr(request, "agent_api_key", None)
        profile = getattr(request, "auth", None)
        if (
            agent_api_key is not None
            and 200 <= response.status_code < 400
            and getattr(profile, "setup_completed_at", None) is None
        ):
            try:
                mark_profile_setup_completed(
                    agent_api_key.profile_id,
                    interface="rest",
                    agent_api_key_id=getattr(agent_api_key, "id", None),
                    agent_api_key_access_level=getattr(agent_api_key, "access_level", ""),
                )
            except DatabaseError as exc:
                logger.warning(
                    "agent_setup.completion_failed",
                    error_type=type(exc).__name__,
                    profile_id=agent_api_key.profile_id,
                    request_interface="rest",
                )
        return response
