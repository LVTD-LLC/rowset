from django.http import HttpRequest
from ninja.security import APIKeyQuery

from apps.core.models import Profile
from apps.core.services import resolve_api_key_profile
from filebridge.utils import get_filebridge_logger

logger = get_filebridge_logger(__name__)


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

    def _get_key(self, request: HttpRequest) -> str | None:
        return _api_key_from_request(request, self.param_name)

    def authenticate(self, request: HttpRequest, key: str | None) -> Profile | None:
        if not key:
            return None
        logger.info("[Django Ninja Auth] API key request")
        resolved = resolve_api_key_profile(key)
        if resolved is None:
            logger.warning("[Django Ninja Auth] Invalid API key")
            return None
        profile, agent_api_key = resolved
        request.agent_api_key = agent_api_key
        return profile


class SessionAuth:
    """Authentication via Django session"""

    def authenticate(self, request: HttpRequest) -> Profile | None:
        if hasattr(request, "user") and request.user.is_authenticated:
            logger.info(
                "[Django Ninja Auth] API Request with authenticated user",
                user_id=request.user.id,
            )
            try:
                return request.user.profile
            except Profile.DoesNotExist:
                logger.warning("[Django Ninja Auth] No profile for user", user_id=request.user.id)
                return None
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
            logger.warning("[Django Ninja Auth] Profile does not exist")
            return None
        profile, agent_api_key = resolved
        if profile.user.is_superuser:
            request.agent_api_key = agent_api_key
            return profile
        logger.warning(
            "[Django Ninja Auth] Non-superuser attempted admin access",
            profile_id=profile.user.id,
        )
        return None


api_key_auth = APIKeyAuth()
session_auth = SessionAuth()
superuser_api_auth = SuperuserAPIKeyAuth()
