from types import SimpleNamespace

import pytest
import structlog
from django.db import transaction
from django.test import override_settings
from django.utils.module_loading import import_string

from apps.core import analytics


@override_settings(POSTHOG_API_KEY="phc_test")
def test_track_activation_event_queues_importable_worker_task(monkeypatch):
    queued = []
    profile = SimpleNamespace(id=42)

    def fake_async_task(task_path, **kwargs):
        queued.append((task_path, kwargs))

    monkeypatch.setattr(analytics, "async_task", fake_async_task)

    result = analytics.track_activation_event(
        profile,
        analytics.ROWSET_DATASET_CREATED,
        {"source": "test"},
        source_function="test_track_activation_event",
    )

    assert result == "Queued activation event rowset_dataset_created for profile 42"
    assert len(queued) == 1
    task_path, kwargs = queued[0]
    assert task_path == "apps.core.tasks.track_activation_event"
    assert import_string(task_path).__name__ == "track_activation_event"
    assert kwargs["profile_id"] == 42


@override_settings(POSTHOG_API_KEY="phc_test")
def test_track_activation_event_propagates_safe_browser_session(monkeypatch):
    queued = []
    monkeypatch.setattr(analytics, "async_task", lambda _path, **kwargs: queued.append(kwargs))
    structlog.contextvars.bind_contextvars(sessionId="session-123")
    try:
        analytics.track_activation_event(SimpleNamespace(id=42), "rowset_test")
    finally:
        structlog.contextvars.clear_contextvars()
    assert queued[0]["session_id"] == "session-123"


@pytest.mark.django_db
@override_settings(POSTHOG_API_KEY="phc_test")
def test_track_account_deleted_event_snapshots_profile_before_commit(
    profile,
    monkeypatch,
    django_capture_on_commit_callbacks,
):
    queued = []
    monkeypatch.setattr(
        analytics,
        "async_task",
        lambda path, **kwargs: queued.append((path, kwargs)),
    )
    profile_id = profile.id
    profile_state = profile.state

    with django_capture_on_commit_callbacks(execute=True):
        with transaction.atomic():
            result = analytics.track_account_deleted_event(profile, session_id="session-123")
            profile.user.delete()
            assert queued == []

    assert result == f"Queued account deletion event for profile {profile_id}"
    assert queued == [
        (
            "apps.core.tasks.track_account_deleted_event",
            {
                "profile_id": profile_id,
                "current_state": profile_state,
                "session_id": "session-123",
                "group": "Track Activation Event",
            },
        )
    ]
    assert import_string(queued[0][0]).__name__ == "track_account_deleted_event"


@pytest.mark.django_db
@override_settings(POSTHOG_API_KEY="phc_test")
def test_track_user_logged_in_event_queues_privacy_safe_snapshot(profile, monkeypatch):
    queued = []
    monkeypatch.setattr(
        analytics,
        "async_task",
        lambda path, **kwargs: queued.append((path, kwargs)),
    )

    result = analytics.track_user_logged_in_event(
        profile,
        login_method="AuthenticationBackend",
        session_id="session-123",
    )

    assert result == f"Queued login event for profile {profile.id}"
    assert queued == [
        (
            "apps.core.tasks.track_user_logged_in_event",
            {
                "profile_id": profile.id,
                "current_state": profile.state,
                "login_method": "AuthenticationBackend",
                "session_id": "session-123",
                "group": "Track Activation Event",
            },
        )
    ]
    assert import_string(queued[0][0]).__name__ == "track_user_logged_in_event"
