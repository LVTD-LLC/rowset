from dataclasses import dataclass
from datetime import timedelta

from allauth.account.models import EmailAddress
from django.conf import settings
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from apps.core.choices import TrialReward, TrialStatus
from apps.core.models import Profile, TrialRewardClaim
from rowset.utils import build_absolute_public_url


class TrialExpiredError(Exception):
    code = "TRIAL_EXPIRED"

    def __init__(self, trial_ended_at):
        self.trial_ended_at = trial_ended_at
        self.upgrade_url = build_absolute_public_url(reverse("pricing"))
        super().__init__(
            "Your Rowset trial has ended. Upgrade to continue using the API, CLI, and MCP."
        )


class TrialRewardUnavailableError(ValueError):
    pass


@dataclass(frozen=True)
class TrialRewardDefinition:
    reward: TrialReward
    title: str
    description: str
    action_label: str
    url: str | None = None
    days: int = 3


@dataclass(frozen=True)
class TrialRewardClaimResult:
    claim: TrialRewardClaim
    created: bool


TRIAL_REWARD_DEFINITIONS = (
    TrialRewardDefinition(
        reward=TrialReward.EMAIL_VERIFIED,
        title="Verify your email",
        description="Protect your account and make recovery easier.",
        action_label="Claim verified email reward",
    ),
    TrialRewardDefinition(
        reward=TrialReward.GITHUB_STAR,
        title="Star Rowset on GitHub",
        description="Support the open-source project and follow its progress.",
        action_label="Star on GitHub — earn 3 days",
        url="https://github.com/LVTD-LLC/rowset",
    ),
    TrialRewardDefinition(
        reward=TrialReward.DISCORD_JOIN,
        title="Join our Discord community",
        description="Get help, share feedback, and meet other Rowset users.",
        action_label="Join Discord — earn 3 days",
        url="https://discord.gg/kzaHJBwMQ",
    ),
    TrialRewardDefinition(
        reward=TrialReward.X_FOLLOW,
        title="Follow Rasul on X",
        description="Keep up with Rowset releases and behind-the-scenes updates.",
        action_label="Follow on X — earn 3 days",
        url="https://x.com/rasulkireev",
    ),
)

TRIAL_REWARD_DEFINITIONS_BY_REWARD = {
    definition.reward: definition for definition in TRIAL_REWARD_DEFINITIONS
}


def get_trial_status(profile: Profile, *, at=None) -> TrialStatus:
    if profile.has_active_subscription:
        return TrialStatus.SUBSCRIBED
    if profile.trial_started_at is None:
        return TrialStatus.NOT_STARTED
    if (at or timezone.now()) > profile.trial_ends_at:
        return TrialStatus.EXPIRED
    return TrialStatus.ACTIVE


def require_unexpired_trial_access(profile: Profile) -> None:
    """Allow subscribed or unstarted profiles, but reject an expired trial."""
    if get_trial_status(profile) == TrialStatus.EXPIRED:
        raise TrialExpiredError(profile.trial_ends_at)


def activate_or_require_trial_access(profile: Profile) -> None:
    if profile.has_active_subscription:
        return

    now = timezone.now()
    if profile.trial_started_at is not None and now <= profile.trial_ends_at:
        return

    with transaction.atomic():
        locked_profile = (
            Profile.objects.select_for_update(of=("self",))
            .select_related("user")
            .get(pk=profile.pk)
        )
        if locked_profile.has_active_subscription:
            return

        if locked_profile.trial_started_at is None:
            pending_claims = list(
                locked_profile.trial_reward_claims.select_for_update().filter(
                    applied_at__isnull=True
                )
            )
            bonus_days = sum(claim.days for claim in pending_claims)
            locked_profile.trial_started_at = now
            locked_profile.trial_ends_at = now + timedelta(
                days=settings.TRIAL_DURATION_DAYS + bonus_days
            )
            locked_profile.save(update_fields=["trial_started_at", "trial_ends_at", "updated_at"])
            if pending_claims:
                TrialRewardClaim.objects.filter(
                    pk__in=[claim.pk for claim in pending_claims]
                ).update(applied_at=now, updated_at=now)

        profile.trial_started_at = locked_profile.trial_started_at
        profile.trial_ends_at = locked_profile.trial_ends_at

    if now > profile.trial_ends_at:
        raise TrialExpiredError(profile.trial_ends_at)


def extend_trial(profile: Profile, *, days: int):
    if not isinstance(days, int) or isinstance(days, bool) or days <= 0:
        raise ValueError("Trial extension days must be a positive integer.")

    now = timezone.now()
    with transaction.atomic():
        locked_profile = Profile.objects.select_for_update().get(pk=profile.pk)
        if locked_profile.trial_ends_at is None:
            raise ValueError("A trial must be started before it can be extended.")
        profile.trial_ends_at = _extend_locked_trial(locked_profile, days=days, at=now)
    return profile.trial_ends_at


def _extend_locked_trial(profile: Profile, *, days: int, at):
    profile.trial_ends_at = max(profile.trial_ends_at, at) + timedelta(days=days)
    profile.save(update_fields=["trial_ends_at", "updated_at"])
    return profile.trial_ends_at


def claim_trial_reward(profile: Profile, reward: str | TrialReward) -> TrialRewardClaimResult:
    try:
        reward = TrialReward(reward)
    except ValueError as exc:
        raise TrialRewardUnavailableError("Unknown trial reward.") from exc

    definition = TRIAL_REWARD_DEFINITIONS_BY_REWARD[reward]
    now = timezone.now()
    with transaction.atomic():
        locked_profile = (
            Profile.objects.select_for_update(of=("self",))
            .select_related("user")
            .get(pk=profile.pk)
        )
        existing_claim = locked_profile.trial_reward_claims.filter(reward=reward).first()
        if existing_claim is not None:
            return TrialRewardClaimResult(claim=existing_claim, created=False)
        if locked_profile.has_active_subscription:
            raise TrialRewardUnavailableError(
                "Trial rewards are not available with an active subscription."
            )
        if (
            reward == TrialReward.EMAIL_VERIFIED
            and not EmailAddress.objects.filter(
                user=locked_profile.user,
                verified=True,
            ).exists()
        ):
            raise TrialRewardUnavailableError("Verify your email before claiming this reward.")

        applied_at = None
        if locked_profile.trial_ends_at is not None:
            profile.trial_ends_at = _extend_locked_trial(
                locked_profile,
                days=definition.days,
                at=now,
            )
            applied_at = now

        claim = TrialRewardClaim.objects.create(
            profile=locked_profile,
            reward=reward,
            days=definition.days,
            applied_at=applied_at,
        )

    return TrialRewardClaimResult(claim=claim, created=True)
