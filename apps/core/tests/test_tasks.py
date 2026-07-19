import pytest
from django.conf import settings
from django.test import override_settings

from apps.core import tasks


@pytest.mark.django_db
@override_settings(POSTHOG_API_KEY="phc_test")
def test_track_activation_event_uses_profile_id_distinct_id(profile, monkeypatch):
    captures = []

    def capture(event, *, distinct_id, properties):
        captures.append(
            {
                "distinct_id": distinct_id,
                "event": event,
                "properties": properties,
            }
        )

    monkeypatch.setattr(tasks.posthog, "capture", capture)

    result = tasks.track_activation_event(
        profile.id,
        "rowset_dataset_row_mutated",
        {"operation": "create"},
        source_function="test",
    )

    assert result == (
        f"Tracked activation event rowset_dataset_row_mutated for profile {profile.id}"
    )
    assert captures == [
        {
            "distinct_id": str(profile.id),
            "event": "rowset_dataset_row_mutated",
            "properties": {
                "event_version": 1,
                "environment": settings.ENVIRONMENT,
                "profile_id": profile.id,
                "current_state": str(profile.state),
                "$set": {
                    "email": profile.user.email,
                    "username": profile.user.username,
                },
                "operation": "create",
            },
        }
    ]


@pytest.mark.django_db
@override_settings(POSTHOG_API_KEY="phc_test")
def test_critical_conversion_event_flushes_before_worker_task_completes(profile, monkeypatch):
    flushed = []
    monkeypatch.setattr(tasks.posthog, "capture", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        tasks.posthog,
        "flush",
        lambda *, timeout_seconds: flushed.append(timeout_seconds),
    )

    tasks.track_activation_event(profile.id, "rowset_signup_completed")

    assert flushed == [5]
