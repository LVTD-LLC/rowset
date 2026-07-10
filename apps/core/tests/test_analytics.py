from types import SimpleNamespace

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
