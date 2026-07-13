from django.http import HttpRequest
from ninja.security import APIKeyQuery

from apps.core.choices import AgentApiKeyAccessLevel
from apps.core.models import Profile
from apps.core.services import require_agent_api_key_access, resolve_api_key_profile
from apps.core.trials import activate_or_require_trial_access
from rowset.logging_context import bind_actor_context
from rowset.utils import get_rowset_logger

logger = get_rowset_logger(__name__)


def _api_key_from_request(request: HttpRequest, query_param_name: str) -> str | None:
    authorization = request.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() == "bearer" and token.strip():
        return token.strip()

    header_key = request.headers.get("x-api-key", "").strip()
    if header_key:
        return header_key

    return request.GET.get(query_param_name)


class APIKeyAuth(APIKeyQuery):
    param_name = "api_key"

    def __init__(self, required_access_level: str = AgentApiKeyAccessLevel.READ):
        super().__init__()
        self.required_access_level = required_access_level

    def _get_key(self, request: HttpRequest) -> str | None:
        return _api_key_from_request(request, self.param_name)

    def authenticate(self, request: HttpRequest, key: str | None) -> Profile | None:
        if not key:
            return None
        resolved = resolve_api_key_profile(key)
        if resolved is None:
            logger.warning(
                "api.authentication.denied",
                **{"auth.method": "api_key", "auth.outcome": "denied", "auth.reason": "invalid"},
            )
            return None
        profile, agent_api_key = resolved
        activate_or_require_trial_access(profile)
        try:
            require_agent_api_key_access(agent_api_key, self.required_access_level)
        except PermissionError:
            logger.warning(
                "api.authentication.denied",
                **{
                    "auth.method": "api_key",
                    "auth.outcome": "denied",
                    "auth.reason": "insufficient_access",
                },
                profile_id=profile.id,
                agent_api_key_id=getattr(agent_api_key, "id", None),
                required_access_level=self.required_access_level,
            )
            return None
        request.agent_api_key = agent_api_key
        bind_actor_context(
            profile_id=profile.id,
            agent_api_key_id=getattr(agent_api_key, "id", None),
            agent_api_key_access_level=getattr(agent_api_key, "access_level", ""),
            auth_method="api_key",
        )
        return profile


class SessionAuth:
    """Authentication via Django session"""

    def authenticate(self, request: HttpRequest) -> Profile | None:
        if hasattr(request, "user") and request.user.is_authenticated:
            try:
                profile = request.user.profile
            except Profile.DoesNotExist:
                logger.warning(
                    "api.authentication.denied",
                    **{
                        "auth.method": "session",
                        "auth.outcome": "denied",
                        "auth.reason": "profile_missing",
                    },
                    user_id=request.user.id,
                )
                return None
            bind_actor_context(profile_id=profile.id, auth_method="session")
            return profile
        return None

    def __call__(self, request: HttpRequest):
        return self.authenticate(request)


class SuperuserAPIKeyAuth(APIKeyQuery):
    param_name = "api_key"

    def _get_key(self, request: HttpRequest) -> str | None:
        return _api_key_from_request(request, self.param_name)

    def authenticate(self, request: HttpRequest, key: str | None) -> Profile | None:
        if not key:
            return None
        resolved = resolve_api_key_profile(key)
        if resolved is None:
            logger.warning(
                "api.authentication.denied",
                **{"auth.method": "api_key", "auth.outcome": "denied", "auth.reason": "invalid"},
            )
            return None
        profile, agent_api_key = resolved
        if profile.user.is_superuser:
            try:
                require_agent_api_key_access(agent_api_key, AgentApiKeyAccessLevel.ADMIN)
            except PermissionError:
                logger.warning(
                    "api.authentication.denied",
                    **{
                        "auth.method": "api_key",
                        "auth.outcome": "denied",
                        "auth.reason": "insufficient_access",
                    },
                    profile_id=profile.id,
                    agent_api_key_id=getattr(agent_api_key, "id", None),
                    required_access_level=AgentApiKeyAccessLevel.ADMIN,
                )
                return None
            request.agent_api_key = agent_api_key
            bind_actor_context(
                profile_id=profile.id,
                agent_api_key_id=getattr(agent_api_key, "id", None),
                agent_api_key_access_level=getattr(agent_api_key, "access_level", ""),
                auth_method="api_key",
            )
            return profile
        logger.warning(
            "api.authentication.denied",
            **{
                "auth.method": "api_key",
                "auth.outcome": "denied",
                "auth.reason": "superuser_required",
            },
            profile_id=profile.id,
        )
        return None


api_key_auth = APIKeyAuth()
api_key_write_auth = APIKeyAuth(AgentApiKeyAccessLevel.READ_WRITE)
api_key_admin_auth = APIKeyAuth(AgentApiKeyAccessLevel.ADMIN)
session_auth = SessionAuth()
superuser_api_auth = SuperuserAPIKeyAuth()
