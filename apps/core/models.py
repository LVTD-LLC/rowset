from typing import Protocol, cast

from django.conf import settings
from django.contrib.auth.models import User
from django.db import models
from django_q.tasks import async_task

from apps.core.base_models import BaseModel
from apps.core.choices import AgentApiKeyAccessLevel, EmailType, FeedbackSource, ProfileStates
from apps.core.model_utils import generate_random_key
from rowset.utils import get_rowset_logger

logger = get_rowset_logger(__name__)


class _ModelIdentity(Protocol):
    id: int


class _ProfileUser(Protocol):
    email: str
    username: str
    is_superuser: bool


class _ProfileWithUser(Protocol):
    user: _ProfileUser


class _StateTransition(Protocol):
    to_state: str


class _StateTransitionManager(Protocol):
    def all(self) -> _StateTransitionManager: ...

    def exists(self) -> bool: ...

    def latest(self, *fields: str) -> _StateTransition: ...


class _ProfileStateTransitions(Protocol):
    state_transitions: _StateTransitionManager


def _model_id(model: object) -> int:
    return cast(_ModelIdentity, model).id


def _profile_user(profile: object) -> _ProfileUser:
    return cast(_ProfileWithUser, profile).user


class Profile(BaseModel):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    key = models.CharField(max_length=30, unique=True, default=generate_random_key)
    agent_setup_prompt_dismissed = models.BooleanField(default=False)

    stripe_subscription_id = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="The user's Stripe subscription id, if it exists",
    )
    stripe_customer_id = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="The user's Stripe customer id, if it exists",
    )

    state = models.CharField(
        max_length=255,
        choices=ProfileStates.choices,
        default=ProfileStates.STRANGER,
        help_text="The current state of the user's profile",
    )

    def track_state_change(self, to_state, metadata=None, source_function=None):
        async_task(
            "apps.core.tasks.track_state_change",
            profile_id=_model_id(self),
            from_state=self.current_state,
            to_state=to_state,
            metadata=metadata,
            source_function=source_function,
            group="Track State Change",
        )

    @property
    def current_state(self):
        state_transitions = cast(_ProfileStateTransitions, self).state_transitions
        if not state_transitions.all().exists():
            return ProfileStates.STRANGER
        latest_transition = state_transitions.latest("created_at")
        return latest_transition.to_state

    @property
    def has_active_subscription(self):
        return self.state in [
            ProfileStates.SUBSCRIBED,
            ProfileStates.CANCELLED,
        ] or (_profile_user(self).is_superuser and settings.ENVIRONMENT == "prod")


class AgentApiKey(BaseModel):
    profile = models.ForeignKey(
        Profile,
        on_delete=models.CASCADE,
        related_name="agent_api_keys",
    )
    name = models.CharField(max_length=80)
    key_prefix = models.CharField(max_length=16)
    token_hash = models.CharField(max_length=64, unique=True)
    token_ciphertext = models.TextField(blank=True, default="")
    access_level = models.CharField(
        max_length=20,
        choices=AgentApiKeyAccessLevel.choices,
        default=AgentApiKeyAccessLevel.READ_WRITE,
    )
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["profile", "name"],
                condition=models.Q(revoked_at__isnull=True),
                name="unique_agent_api_key_name_per_profile",
            ),
        ]

    @property
    def is_active(self):
        return self.revoked_at is None

    @property
    def can_read(self):
        return self.access_level in {
            AgentApiKeyAccessLevel.READ,
            AgentApiKeyAccessLevel.READ_WRITE,
            AgentApiKeyAccessLevel.ADMIN,
        }

    @property
    def can_write(self):
        return self.access_level in {
            AgentApiKeyAccessLevel.READ_WRITE,
            AgentApiKeyAccessLevel.ADMIN,
        }

    @property
    def can_admin(self):
        return self.access_level == AgentApiKeyAccessLevel.ADMIN

    def __str__(self):
        return f"{self.name} ({_profile_user(self.profile).email})"


class ProfileStateTransition(BaseModel):
    profile = models.ForeignKey(
        Profile,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="state_transitions",
    )
    from_state = models.CharField(max_length=255, choices=ProfileStates.choices)
    to_state = models.CharField(max_length=255, choices=ProfileStates.choices)
    backup_profile_id = models.IntegerField()
    metadata = models.JSONField(null=True, blank=True)


class Feedback(BaseModel):
    profile = models.ForeignKey(
        Profile,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="feedback",
        help_text="The user who submitted the feedback",
    )
    agent_api_key = models.ForeignKey(
        AgentApiKey,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="feedback",
        help_text="The agent API key used to submit the feedback, when available",
    )
    source = models.CharField(
        max_length=20,
        choices=FeedbackSource.choices,
        default=FeedbackSource.BROWSER,
        help_text="The interface that submitted the feedback",
    )
    feedback = models.TextField(
        help_text="The feedback text",
    )
    page = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="The page where the feedback was submitted",
    )
    metadata = models.JSONField(
        blank=True,
        default=dict,
        help_text="Optional structured context supplied with the feedback",
    )

    def __str__(self):
        return f"{self._submitter_label()}: {self.feedback}"

    def _submitter_label(self) -> str:
        return _profile_user(self.profile).email if self.profile else "Anonymous"


class EmailSent(BaseModel):
    email_address = models.EmailField(help_text="The recipient email address")
    email_type = models.CharField(
        max_length=50, choices=EmailType.choices, help_text="Type of email sent"
    )
    profile = models.ForeignKey(
        Profile,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="emails_sent",
        help_text="Associated user profile, if applicable",
    )

    class Meta:
        verbose_name = "Email Sent"
        verbose_name_plural = "Emails Sent"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.email_type} to {self.email_address}"
