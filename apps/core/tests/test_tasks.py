import pytest
from django.test import override_settings

from apps.core import tasks


@pytest.mark.django_db
@override_settings(POSTHOG_API_KEY="phc_test")
def test_track_event_uses_profile_id_distinct_id(profile, monkeypatch):
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

    result = tasks.track_event(
        profile.id,
        "user_signed_up",
        {"signup_method": "test"},
        source_function="test",
    )

    assert result == f"Tracked event user_signed_up for profile {profile.id}"
    assert captures == [
        {
            "distinct_id": str(profile.id),
            "event": "user_signed_up",
            "properties": {
                "profile_id": profile.id,
                "email": profile.user.email,
                "current_state": profile.state,
                "signup_method": "test",
            },
        }
    ]


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
                "profile_id": profile.id,
                "current_state": profile.state,
                "$set": {
                    "email": profile.user.email,
                    "username": profile.user.username,
                },
                "operation": "create",
            },
        }
    ]
