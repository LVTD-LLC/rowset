from types import SimpleNamespace

from django.test import override_settings
from django.utils.module_loading import import_string

from apps.pages import views as page_views


@override_settings(POSTHOG_API_KEY="phc_test")
def test_landing_context_queues_importable_alias_task(monkeypatch):
    queued = []
    profile = SimpleNamespace(id=42)
    view = page_views.LandingPageView()
    view.request = SimpleNamespace(
        user=SimpleNamespace(is_authenticated=True, profile=profile),
        COOKIES={"sessionid": "private"},
        GET={},
    )
    monkeypatch.setattr(
        page_views,
        "async_task",
        lambda task_path, **kwargs: queued.append(task_path),
    )

    view.get_context_data()

    assert queued == ["apps.core.tasks.try_create_posthog_alias"]
    assert import_string(queued[0]).__name__ == "try_create_posthog_alias"


def test_signup_tracking_queues_importable_worker_tasks(monkeypatch):
    queued = []

    def fake_async_task(task_path, **kwargs):
        queued.append((task_path, kwargs))

    monkeypatch.setattr(page_views, "async_task", fake_async_task)
    monkeypatch.setattr(page_views, "track_activation_event", lambda *args, **kwargs: None)

    profile = SimpleNamespace(
        id=42,
        user=SimpleNamespace(email="user@example.com", username="user"),
    )
    tracking = page_views.SignupTrackingMixin()
    tracking.user = SimpleNamespace(profile=profile)
    tracking.request = SimpleNamespace(COOKIES={"sessionid": "private"})
    tracking._track_signup()

    task_paths = [task_path for task_path, _kwargs in queued]
    assert task_paths == [
        "apps.core.tasks.try_create_posthog_alias",
        "apps.core.tasks.track_event",
    ]
    assert [import_string(task_path).__name__ for task_path in task_paths] == [
        "try_create_posthog_alias",
        "track_event",
    ]
