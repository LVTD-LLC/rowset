from typing import Any, Protocol, cast

from apps.core.models import AgentApiKey, Profile


class ProfileUser(Protocol):
    id: int | None
    email: str
    is_authenticated: bool
    is_superuser: bool
    profile: Profile


class ProfileManager(Protocol):
    def select_related(self, *fields: str) -> ProfileManager: ...

    def get(self, **filters: object) -> Profile: ...


class AgentApiKeyManager(Protocol):
    def get(self, **filters: object) -> AgentApiKey: ...


class AgentApiKeyRequest(Protocol):
    agent_api_key: AgentApiKey | None


ProfileDoesNotExist = cast(type[Exception], cast(Any, Profile).DoesNotExist)
AgentApiKeyDoesNotExist = cast(type[Exception], cast(Any, AgentApiKey).DoesNotExist)


def profile_objects() -> ProfileManager:
    return cast(ProfileManager, cast(Any, Profile).objects)


def agent_api_key_objects() -> AgentApiKeyManager:
    return cast(AgentApiKeyManager, cast(Any, AgentApiKey).objects)


def profile_id(profile: Profile) -> int:
    return cast(int, cast(Any, profile).id)


def profile_user(profile: Profile) -> ProfileUser:
    return cast(ProfileUser, cast(Any, profile).user)


def agent_api_key_id(agent_api_key: AgentApiKey) -> int:
    return cast(int, cast(Any, agent_api_key).id)


def request_user(request: object) -> ProfileUser | None:
    user = getattr(request, "user", None)
    if user is None:
        return None
    return cast(ProfileUser, user)


def attach_agent_api_key_to_request(
    request: object,
    agent_api_key: AgentApiKey | None,
) -> None:
    cast(AgentApiKeyRequest, request).agent_api_key = agent_api_key
