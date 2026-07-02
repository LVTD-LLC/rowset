from typing import Protocol, cast

from apps.core.models import AgentApiKey, EmailSent, Feedback, Profile, ProfileStateTransition


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


class ProfileStateFields(Protocol):
    state: str


class ProfileQuerySet(Protocol):
    def first(self) -> Profile | None: ...

    def get(self, **filters: object) -> Profile: ...

    def only(self, *fields: str) -> ProfileQuerySet: ...


class ProfileManager(Protocol):
    def select_related(self, *fields: str) -> ProfileManager: ...

    def create(self, **fields: object) -> Profile: ...

    def filter(self, **filters: object) -> ProfileQuerySet: ...

    def get(self, **filters: object) -> Profile: ...

    def get_or_create(self, **filters: object) -> tuple[Profile, bool]: ...

    def only(self, *fields: str) -> ProfileQuerySet: ...


class AgentApiKeyQuerySet(Protocol):
    def exists(self) -> bool: ...


class AgentApiKeyManager(Protocol):
    def filter(self, **filters: object) -> AgentApiKeyQuerySet: ...

    def get(self, **filters: object) -> AgentApiKey: ...


class AgentApiKeyRequest(Protocol):
    agent_api_key: AgentApiKey | None


class AgentApiKeyTaskFields(Protocol):
    key_prefix: str
    name: str


def _django_attr(model: object, name: str) -> object:
    return getattr(model, name)


class EmailSentManager(Protocol):
    def create(self, **fields: object) -> EmailSent: ...


class FeedbackTaskFields(Protocol):
    agent_api_key: AgentApiKey | None
    feedback: str
    metadata: object
    page: str
    profile: Profile | None

    def get_source_display(self) -> str: ...


class FeedbackQuerySet(Protocol):
    def get(self, **filters: object) -> Feedback: ...


class FeedbackManager(Protocol):
    def create(self, **fields: object) -> Feedback: ...

    def select_related(self, *fields: str) -> FeedbackQuerySet: ...


class ProfileStateTransitionManager(Protocol):
    def create(self, **fields: object) -> ProfileStateTransition: ...


ProfileDoesNotExist = cast(type[Exception], _django_attr(Profile, "DoesNotExist"))
AgentApiKeyDoesNotExist = cast(type[Exception], _django_attr(AgentApiKey, "DoesNotExist"))
FeedbackDoesNotExist = cast(type[Exception], _django_attr(Feedback, "DoesNotExist"))


def profile_objects() -> ProfileManager:
    return cast(ProfileManager, _django_attr(Profile, "objects"))


def agent_api_key_objects() -> AgentApiKeyManager:
    return cast(AgentApiKeyManager, _django_attr(AgentApiKey, "objects"))


def email_sent_objects() -> EmailSentManager:
    return cast(EmailSentManager, _django_attr(EmailSent, "objects"))


def feedback_objects() -> FeedbackManager:
    return cast(FeedbackManager, _django_attr(Feedback, "objects"))


def profile_state_transition_objects() -> ProfileStateTransitionManager:
    return cast(
        ProfileStateTransitionManager,
        _django_attr(ProfileStateTransition, "objects"),
    )


def model_id(model: object) -> int:
    return cast(ModelIdentity, model).id


def profile_id(profile: Profile) -> int:
    return model_id(profile)


def profile_user(profile: Profile) -> ProfileUser:
    return cast(ProfileWithUser, profile).user


def profile_state_fields(profile: Profile) -> ProfileStateFields:
    return cast(ProfileStateFields, profile)


def agent_api_key_id(agent_api_key: AgentApiKey) -> int:
    return model_id(agent_api_key)


def agent_api_key_task_fields(agent_api_key: AgentApiKey) -> AgentApiKeyTaskFields:
    return cast(AgentApiKeyTaskFields, agent_api_key)


def feedback_task_fields(feedback: Feedback) -> FeedbackTaskFields:
    return cast(FeedbackTaskFields, feedback)


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
