from datetime import datetime, timedelta

import pytest
from django.db import IntegrityError, transaction
from django.test import override_settings
from django.utils import timezone

from apps.core import trials
from apps.core.choices import ProfileStates

pytestmark = pytest.mark.django_db


@override_settings(TRIAL_DURATION_DAYS=7)
def test_first_agent_request_starts_trial_once(profile, monkeypatch):
    started_at = datetime(2026, 7, 13, 10, 30, tzinfo=timezone.UTC)
    monkeypatch.setattr(trials.timezone, "now", lambda: started_at)

    trials.activate_or_require_trial_access(profile)

    profile.refresh_from_db()
    assert profile.trial_started_at == started_at
    assert profile.trial_ends_at == started_at + timedelta(days=7)

    monkeypatch.setattr(
        trials.timezone,
        "now",
        lambda: started_at + timedelta(days=1),
    )
    trials.activate_or_require_trial_access(profile)

    profile.refresh_from_db()
    assert profile.trial_started_at == started_at
    assert profile.trial_ends_at == started_at + timedelta(days=7)


@override_settings(TRIAL_DURATION_DAYS=7)
def test_trial_is_active_through_exact_deadline(profile, monkeypatch):
    started_at = datetime(2026, 7, 1, tzinfo=timezone.UTC)
    profile.trial_started_at = started_at
    profile.trial_ends_at = started_at + timedelta(days=7)
    profile.save(update_fields=["trial_started_at", "trial_ends_at", "updated_at"])
    monkeypatch.setattr(trials.timezone, "now", lambda: profile.trial_ends_at)

    trials.activate_or_require_trial_access(profile)


def test_expired_trial_raises_structured_error(profile, monkeypatch):
    ended_at = datetime(2026, 7, 8, tzinfo=timezone.UTC)
    profile.trial_started_at = ended_at - timedelta(days=7)
    profile.trial_ends_at = ended_at
    profile.save(update_fields=["trial_started_at", "trial_ends_at", "updated_at"])
    monkeypatch.setattr(trials.timezone, "now", lambda: ended_at + timedelta(microseconds=1))

    with pytest.raises(trials.TrialExpiredError) as exc_info:
        trials.activate_or_require_trial_access(profile)

    assert exc_info.value.code == "TRIAL_EXPIRED"
    assert exc_info.value.trial_ended_at == ended_at


def test_non_activating_access_allows_unstarted_trial_but_rejects_expired_trial(profile):
    trials.require_unexpired_trial_access(profile)
    profile.refresh_from_db()
    assert profile.trial_started_at is None

    ended_at = timezone.now() - timedelta(seconds=1)
    profile.trial_started_at = ended_at - timedelta(days=7)
    profile.trial_ends_at = ended_at
    profile.save(update_fields=["trial_started_at", "trial_ends_at", "updated_at"])

    with pytest.raises(trials.TrialExpiredError) as exc_info:
        trials.require_unexpired_trial_access(profile)

    assert exc_info.value.trial_ended_at == ended_at


def test_subscribed_profile_bypasses_trial_without_starting_it(profile):
    profile.state = ProfileStates.SUBSCRIBED
    profile.save(update_fields=["state", "updated_at"])

    trials.activate_or_require_trial_access(profile)

    profile.refresh_from_db()
    assert profile.trial_started_at is None
    assert profile.trial_ends_at is None


def test_extend_active_trial_preserves_remaining_time(profile, monkeypatch):
    now = datetime(2026, 7, 5, tzinfo=timezone.UTC)
    original_end = datetime(2026, 7, 8, tzinfo=timezone.UTC)
    profile.trial_started_at = datetime(2026, 7, 1, tzinfo=timezone.UTC)
    profile.trial_ends_at = original_end
    profile.save(update_fields=["trial_started_at", "trial_ends_at", "updated_at"])
    monkeypatch.setattr(trials.timezone, "now", lambda: now)

    extended_end = trials.extend_trial(profile, days=3)

    assert extended_end == original_end + timedelta(days=3)
    profile.refresh_from_db()
    assert profile.trial_ends_at == extended_end


def test_extend_expired_trial_restarts_from_now(profile, monkeypatch):
    now = datetime(2026, 7, 10, tzinfo=timezone.UTC)
    profile.trial_started_at = datetime(2026, 7, 1, tzinfo=timezone.UTC)
    profile.trial_ends_at = datetime(2026, 7, 8, tzinfo=timezone.UTC)
    profile.save(update_fields=["trial_started_at", "trial_ends_at", "updated_at"])
    monkeypatch.setattr(trials.timezone, "now", lambda: now)

    extended_end = trials.extend_trial(profile, days=3)

    assert extended_end == now + timedelta(days=3)


def test_extend_trial_rejects_non_positive_days(profile):
    with pytest.raises(ValueError, match="positive"):
        trials.extend_trial(profile, days=0)


def test_trial_status_distinguishes_account_states(profile):
    now = datetime(2026, 7, 10, tzinfo=timezone.UTC)

    assert trials.get_trial_status(profile, at=now) == "not_started"

    profile.trial_started_at = now - timedelta(days=1)
    profile.trial_ends_at = now
    assert trials.get_trial_status(profile, at=now) == "active"

    profile.trial_ends_at = now - timedelta(microseconds=1)
    assert trials.get_trial_status(profile, at=now) == "expired"

    profile.state = ProfileStates.SUBSCRIBED
    assert trials.get_trial_status(profile, at=now) == "subscribed"


def test_trial_end_cannot_precede_trial_start(profile):
    profile.trial_started_at = datetime(2026, 7, 8, tzinfo=timezone.UTC)
    profile.trial_ends_at = datetime(2026, 7, 7, tzinfo=timezone.UTC)

    with pytest.raises(IntegrityError), transaction.atomic():
        profile.save(update_fields=["trial_started_at", "trial_ends_at", "updated_at"])
