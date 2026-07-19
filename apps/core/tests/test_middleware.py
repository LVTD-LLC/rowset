from types import SimpleNamespace

from django.db import DatabaseError
from django.http import HttpResponse
from django.test import RequestFactory

from apps.core.middleware import AgentSetupCompletionMiddleware


def _request(*, completed=False):
    request = RequestFactory().get("/api/user")
    request.auth = SimpleNamespace(
        id=11,
        setup_completed_at=object() if completed else None,
    )
    request.agent_api_key = SimpleNamespace(profile_id=11)
    return request


def test_rest_setup_completion_failure_preserves_successful_response(monkeypatch):
    def fail_to_mark(_profile_id, **_kwargs):
        raise DatabaseError("database unavailable")

    monkeypatch.setattr("apps.core.middleware.mark_profile_setup_completed", fail_to_mark)
    middleware = AgentSetupCompletionMiddleware(lambda _request: HttpResponse(status=200))

    response = middleware(_request())

    assert response.status_code == 200


def test_rest_setup_completion_skips_marker_when_profile_is_already_complete(monkeypatch):
    completed_profile_ids = []
    monkeypatch.setattr(
        "apps.core.middleware.mark_profile_setup_completed",
        completed_profile_ids.append,
    )
    middleware = AgentSetupCompletionMiddleware(lambda _request: HttpResponse(status=200))

    response = middleware(_request(completed=True))

    assert response.status_code == 200
    assert completed_profile_ids == []
