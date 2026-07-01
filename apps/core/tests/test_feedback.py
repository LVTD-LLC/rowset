import sys
from types import SimpleNamespace

import pytest
from django.test import override_settings

from apps.core.choices import AgentApiKeyAccessLevel, FeedbackSource
from apps.core.models import Feedback
from apps.core.services import create_agent_api_key, submit_profile_feedback
from apps.core.tasks import notify_feedback_apprise


@pytest.mark.django_db
@override_settings(ROWSET_FEEDBACK_APPRISE_URLS=("slack://token-a/token-b/token-c/#feedback",))
def test_submit_profile_feedback_persists_agent_context_and_queues_notification(
    profile,
    monkeypatch,
    django_capture_on_commit_callbacks,
):
    credential = create_agent_api_key(
        profile,
        "Read Agent",
        AgentApiKeyAccessLevel.READ,
    )
    queued = []

    def fake_async_task(func_path, feedback_id, **kwargs):
        queued.append((func_path, feedback_id, kwargs))
        return "task-id"

    monkeypatch.setattr("apps.core.services.async_task", fake_async_task)

    with django_capture_on_commit_callbacks(execute=True):
        feedback = submit_profile_feedback(
            profile=profile,
            feedback="  The MCP schema for rows is hard to follow.  ",
            page="mcp:submit_feedback",
            source=FeedbackSource.MCP,
            metadata={"tool": "create_dataset", "category": "docs"},
            agent_api_key=credential.agent_api_key,
        )

    feedback.refresh_from_db()
    assert feedback.feedback == "The MCP schema for rows is hard to follow."
    assert feedback.page == "mcp:submit_feedback"
    assert feedback.source == FeedbackSource.MCP
    assert feedback.metadata == {"tool": "create_dataset", "category": "docs"}
    assert feedback.agent_api_key == credential.agent_api_key
    assert queued == [
        (
            "apps.core.tasks.notify_feedback_apprise",
            feedback.id,
            {"group": "Feedback Notification"},
        )
    ]


@pytest.mark.django_db
def test_submit_profile_feedback_rejects_blank_feedback(profile):
    with pytest.raises(ValueError, match="Feedback is required"):
        submit_profile_feedback(profile=profile, feedback="   ")


@pytest.mark.django_db
@override_settings(
    ROWSET_FEEDBACK_APPRISE_URLS=("slack://token-a/token-b/token-c/#feedback",),
    ROWSET_FEEDBACK_APPRISE_TITLE="New Rowset feedback",
)
def test_notify_feedback_apprise_sends_configured_notification(profile, monkeypatch):
    feedback = Feedback.objects.create(
        profile=profile,
        feedback="Agent could not tell whether public previews were authenticated.",
        page="mcp:submit_feedback",
        source=FeedbackSource.MCP,
        metadata={"tool": "update_dataset_public_preview"},
    )
    calls = []

    class FakeApprise:
        def __init__(self):
            calls.append(("init",))

        def add(self, url):
            calls.append(("add", url))
            return True

        def notify(self, *, title, body):
            calls.append(("notify", title, body))
            return True

    monkeypatch.setitem(sys.modules, "apprise", SimpleNamespace(Apprise=FakeApprise))

    result = notify_feedback_apprise(feedback.id)

    assert result == f"Sent Apprise feedback notification for feedback {feedback.id}."
    assert calls[0] == ("init",)
    assert calls[1] == ("add", "slack://token-a/token-b/token-c/#feedback")
    _, title, body = calls[2]
    assert title == "New Rowset feedback"
    assert "Source: MCP" in body
    assert "User: testuser@example.com" in body
    assert "Agent could not tell whether public previews were authenticated." in body
    assert "Context keys: tool" in body


@override_settings(ROWSET_FEEDBACK_APPRISE_URLS=())
def test_notify_feedback_apprise_skips_when_unconfigured():
    assert notify_feedback_apprise(123) == "Apprise feedback notifications are not configured."
