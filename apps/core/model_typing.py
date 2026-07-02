from typing import Protocol, cast

from apps.core.models import AgentApiKey, EmailSent, Profile


class ModelIdentity(Protocol):
    id: int


class ProfileUser(Protocol):
    id: int | None
    email: str
    username: str
    is_authenticated: bool
    is_superuser: bool
    profile: Profile


class ProfileWithUser(Protocol):
    user: ProfileUser


class ProfileQuerySet(Protocol):
    def first(self) -> Profile | None: ...


class ProfileManager(Protocol):
    def select_related(self, *fields: str) -> ProfileManager: ...

    def create(self, **fields: object) -> Profile: ...

    def filter(self, **filters: object) -> ProfileQuerySet: ...

    def get(self, **filters: object) -> Profile: ...


class AgentApiKeyQuerySet(Protocol):
    def exists(self) -> bool: ...


class AgentApiKeyManager(Protocol):
    def filter(self, **filters: object) -> AgentApiKeyQuerySet: ...

    def get(self, **filters: object) -> AgentApiKey: ...


class AgentApiKeyRequest(Protocol):
    agent_api_key: AgentApiKey | None


def _django_attr(model: object, name: str) -> object:
    return getattr(model, name)


class EmailSentManager(Protocol):
    def create(self, **fields: object) -> EmailSent: ...


ProfileDoesNotExist = cast(type[Exception], _django_attr(Profile, "DoesNotExist"))
AgentApiKeyDoesNotExist = cast(type[Exception], _django_attr(AgentApiKey, "DoesNotExist"))


def profile_objects() -> ProfileManager:
    return cast(ProfileManager, _django_attr(Profile, "objects"))


def agent_api_key_objects() -> AgentApiKeyManager:
    return cast(AgentApiKeyManager, _django_attr(AgentApiKey, "objects"))


def email_sent_objects() -> EmailSentManager:
    return cast(EmailSentManager, _django_attr(EmailSent, "objects"))


def model_id(model: object) -> int:
    return cast(ModelIdentity, model).id


def profile_id(profile: Profile) -> int:
    return model_id(profile)


def profile_user(profile: Profile) -> ProfileUser:
    return cast(ProfileWithUser, profile).user


def agent_api_key_id(agent_api_key: AgentApiKey) -> int:
    return model_id(agent_api_key)


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
