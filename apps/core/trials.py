from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from apps.core.choices import TrialStatus
from apps.core.models import Profile
from rowset.utils import build_absolute_public_url


class TrialExpiredError(Exception):
    code = "TRIAL_EXPIRED"

    def __init__(self, trial_ended_at):
        self.trial_ended_at = trial_ended_at
        self.upgrade_url = build_absolute_public_url(reverse("pricing"))
        super().__init__(
            "Your Rowset trial has ended. Upgrade to continue using the API, CLI, and MCP."
        )


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
            locked_profile.trial_started_at = now
            locked_profile.trial_ends_at = now + timedelta(days=settings.TRIAL_DURATION_DAYS)
            locked_profile.save(update_fields=["trial_started_at", "trial_ends_at", "updated_at"])

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
        locked_profile.trial_ends_at = max(locked_profile.trial_ends_at, now) + timedelta(days=days)
        locked_profile.save(update_fields=["trial_ends_at", "updated_at"])
        profile.trial_ends_at = locked_profile.trial_ends_at
    return profile.trial_ends_at
