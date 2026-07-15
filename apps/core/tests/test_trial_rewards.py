from datetime import datetime, timedelta

import pytest
from allauth.account.models import EmailAddress
from django.test import override_settings
from django.utils import timezone

from apps.core import signals, trials
from apps.core.choices import ProfileStates, TrialReward
from apps.core.models import TrialRewardClaim

pytestmark = pytest.mark.django_db


def start_trial(profile, *, starts_at, ends_at):
    profile.trial_started_at = starts_at
    profile.trial_ends_at = ends_at
    profile.save(update_fields=["trial_started_at", "trial_ends_at", "updated_at"])


def test_claim_reward_extends_an_active_trial_once(profile, monkeypatch):
    now = datetime(2026, 7, 15, 12, tzinfo=timezone.UTC)
    original_end = now + timedelta(days=4)
    start_trial(profile, starts_at=now - timedelta(days=3), ends_at=original_end)
    monkeypatch.setattr(trials.timezone, "now", lambda: now)

    first_result = trials.claim_trial_reward(profile, TrialReward.GITHUB_STAR)
    second_result = trials.claim_trial_reward(profile, TrialReward.GITHUB_STAR)

    profile.refresh_from_db()
    claim = TrialRewardClaim.objects.get(profile=profile, reward=TrialReward.GITHUB_STAR)
    assert first_result.created is True
    assert second_result.created is False
    assert claim.days == 3
    assert claim.applied_at == now
    assert profile.trial_ends_at == original_end + timedelta(days=3)


@override_settings(TRIAL_DURATION_DAYS=7)
def test_reward_claimed_before_trial_start_is_applied_when_trial_starts(profile, monkeypatch):
    claimed_at = datetime(2026, 7, 15, 12, tzinfo=timezone.UTC)
    started_at = claimed_at + timedelta(days=2)
    monkeypatch.setattr(trials.timezone, "now", lambda: claimed_at)

    result = trials.claim_trial_reward(profile, TrialReward.DISCORD_JOIN)

    result.claim.refresh_from_db()
    assert result.claim.applied_at is None
    assert profile.trial_started_at is None

    monkeypatch.setattr(trials.timezone, "now", lambda: started_at)
    trials.activate_or_require_trial_access(profile)

    profile.refresh_from_db()
    result.claim.refresh_from_db()
    assert profile.trial_started_at == started_at
    assert profile.trial_ends_at == started_at + timedelta(days=10)
    assert result.claim.applied_at == started_at


def test_email_reward_requires_a_verified_email(profile):
    EmailAddress.objects.update_or_create(
        user=profile.user,
        email=profile.user.email,
        defaults={"primary": True, "verified": False},
    )

    with pytest.raises(trials.TrialRewardUnavailableError, match="Verify your email"):
        trials.claim_trial_reward(profile, TrialReward.EMAIL_VERIFIED)

    assert not TrialRewardClaim.objects.filter(profile=profile).exists()


def test_verified_email_can_be_claimed(profile):
    EmailAddress.objects.update_or_create(
        user=profile.user,
        email=profile.user.email,
        defaults={"primary": True, "verified": True},
    )

    result = trials.claim_trial_reward(profile, TrialReward.EMAIL_VERIFIED)

    assert result.created is True
    assert result.claim.reward == TrialReward.EMAIL_VERIFIED


def test_existing_email_reward_claim_remains_idempotent_if_address_is_removed(profile):
    email_address, _ = EmailAddress.objects.update_or_create(
        user=profile.user,
        email=profile.user.email,
        defaults={"primary": True, "verified": True},
    )
    trials.claim_trial_reward(profile, TrialReward.EMAIL_VERIFIED)
    email_address.delete()

    result = trials.claim_trial_reward(profile, TrialReward.EMAIL_VERIFIED)

    assert result.created is False
    assert TrialRewardClaim.objects.filter(profile=profile).count() == 1


def test_unknown_reward_is_rejected(profile):
    with pytest.raises(trials.TrialRewardUnavailableError, match="Unknown"):
        trials.claim_trial_reward(profile, "watch_video")


def test_subscribed_profile_cannot_claim_trial_rewards(profile):
    profile.state = ProfileStates.SUBSCRIBED
    profile.save(update_fields=["state", "updated_at"])

    with pytest.raises(trials.TrialRewardUnavailableError, match="active subscription"):
        trials.claim_trial_reward(profile, TrialReward.X_FOLLOW)

    assert not TrialRewardClaim.objects.filter(profile=profile).exists()


def test_claiming_reward_restarts_an_expired_trial_from_now(profile, monkeypatch):
    now = datetime(2026, 7, 15, 12, tzinfo=timezone.UTC)
    start_trial(
        profile,
        starts_at=now - timedelta(days=10),
        ends_at=now - timedelta(days=3),
    )
    monkeypatch.setattr(trials.timezone, "now", lambda: now)

    trials.claim_trial_reward(profile, TrialReward.X_FOLLOW)

    profile.refresh_from_db()
    assert profile.trial_ends_at == now + timedelta(days=3)


def test_confirming_email_automatically_claims_the_reward(profile):
    email_address, _ = EmailAddress.objects.update_or_create(
        user=profile.user,
        email=profile.user.email,
        defaults={"primary": True, "verified": True},
    )

    signals.claim_email_verification_trial_reward(
        sender=object(),
        email_address=email_address,
    )

    claim = TrialRewardClaim.objects.get(
        profile=profile,
        reward=TrialReward.EMAIL_VERIFIED,
    )
    assert claim.applied_at is None
