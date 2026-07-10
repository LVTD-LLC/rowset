import logging
from types import SimpleNamespace

import pytest
import structlog
from django.http import HttpResponse
from django.test import RequestFactory
from django_htmx.middleware import HtmxDetails

from rowset.request_logging import RequestLoggingMiddleware
from rowset.utils import get_rowset_logger


class CollectingHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.events: list[dict] = []

    def emit(self, record: logging.LogRecord) -> None:
        if isinstance(record.msg, dict):
            self.events.append(record.msg.copy())


@pytest.fixture
def captured_events():
    structlog.contextvars.clear_contextvars()
    rowset_logger = logging.getLogger("rowset")
    handler = CollectingHandler()
    rowset_logger.addHandler(handler)
    try:
        yield handler.events
    finally:
        rowset_logger.removeHandler(handler)
        structlog.contextvars.clear_contextvars()


def _event(events: list[dict], event_name: str) -> dict:
    return next(event for event in events if event.get("event") == event_name)


def _request(path: str = "/datasets/"):
    request = RequestFactory().get(path)
    request.user = SimpleNamespace(is_authenticated=False)
    request.resolver_match = SimpleNamespace(view_name="dataset_list", route="datasets/")
    return request


def test_request_middleware_emits_one_wide_htmx_event(captured_events):
    request = RequestFactory().get(
        "/datasets/",
        HTTP_HX_REQUEST="true",
        HTTP_HX_BOOSTED="true",
        HTTP_HX_HISTORY_RESTORE_REQUEST="true",
    )
    request.user = SimpleNamespace(is_authenticated=False)
    request.htmx = HtmxDetails(request)
    request.resolver_match = SimpleNamespace(view_name="dataset_list", route="datasets/")

    response = RequestLoggingMiddleware(lambda _request: HttpResponse(status=200))(request)

    event = _event(captured_events, "http.request.completed")
    assert event["request.interface"] == "htmx"
    assert event["http.request.method"] == "GET"
    assert event["http.route"] == "dataset_list"
    assert event["http.response.status_code"] == 200
    assert event["http.response.status_class"] == "2xx"
    assert event["http.is_htmx"] is True
    assert event["htmx.boosted"] is True
    assert event["htmx.history_restore_request"] is True
    assert event["outcome"] == "success"
    assert event["duration_ms"] >= 0
    assert response.headers["X-Request-ID"] == event["request.id"]


def test_request_middleware_binds_actor_and_correlation_context_to_nested_logs(captured_events):
    request = _request()
    request.user = SimpleNamespace(
        id=3,
        is_authenticated=True,
        profile=SimpleNamespace(id=7),
    )
    domain_logger = get_rowset_logger("request-test-domain")

    def response_with_domain_log(_request):
        domain_logger.info("dataset.operation.completed", dataset_id=9)
        return HttpResponse(status=201)

    RequestLoggingMiddleware(response_with_domain_log)(request)

    domain_event = _event(captured_events, "dataset.operation.completed")
    request_event = _event(captured_events, "http.request.completed")
    assert domain_event["request.id"] == request_event["request.id"]
    assert request_event["user_id"] == 3
    assert request_event["profile_id"] == 7
    assert request_event["posthogDistinctId"] == "7"
    assert request_event["auth.method"] == "session"


def test_request_middleware_classifies_rest_requests(captured_events):
    request = _request("/api/datasets")
    request.resolver_match = SimpleNamespace(view_name="api-datasets", route="api/datasets")

    RequestLoggingMiddleware(lambda _request: HttpResponse(status=404))(request)

    event = _event(captured_events, "http.request.completed")
    assert event["request.interface"] == "rest"
    assert event["http.response.status_class"] == "4xx"
    assert event["outcome"] == "success"


def test_request_middleware_uses_safe_incoming_request_id_and_replaces_unsafe_one(captured_events):
    trusted = RequestFactory().get("/datasets/", HTTP_X_REQUEST_ID="edge.req-123")
    trusted.user = SimpleNamespace(is_authenticated=False)
    trusted.resolver_match = SimpleNamespace(view_name="dataset_list", route="datasets/")
    RequestLoggingMiddleware(lambda _request: HttpResponse())(trusted)

    unsafe = RequestFactory().get("/datasets/", HTTP_X_REQUEST_ID="secret\nheader")
    unsafe.user = SimpleNamespace(is_authenticated=False)
    unsafe.resolver_match = SimpleNamespace(view_name="dataset_list", route="datasets/")
    RequestLoggingMiddleware(lambda _request: HttpResponse())(unsafe)

    events = [event for event in captured_events if event.get("event") == "http.request.completed"]
    assert events[0]["request.id"] == "edge.req-123"
    assert events[1]["request.id"] != "secret\nheader"
    assert len(events[1]["request.id"]) == 32


def test_request_middleware_binds_safe_posthog_session_id(captured_events):
    request = RequestFactory().get(
        "/datasets/",
        HTTP_X_POSTHOG_SESSION_ID="session-123_abc",
    )
    request.user = SimpleNamespace(is_authenticated=False)
    request.resolver_match = SimpleNamespace(view_name="dataset_list", route="datasets/")

    RequestLoggingMiddleware(lambda _request: HttpResponse())(request)

    event = _event(captured_events, "http.request.completed")
    assert event["sessionId"] == "session-123_abc"


def test_request_middleware_rejects_unsafe_posthog_session_id(captured_events):
    request = RequestFactory().get(
        "/datasets/",
        HTTP_X_POSTHOG_SESSION_ID="private\nsession",
    )
    request.user = SimpleNamespace(is_authenticated=False)
    request.resolver_match = SimpleNamespace(view_name="dataset_list", route="datasets/")

    RequestLoggingMiddleware(lambda _request: HttpResponse())(request)

    event = _event(captured_events, "http.request.completed")
    assert "sessionId" not in event


def test_request_middleware_logs_server_error_type_and_clears_context(captured_events):
    request = _request("/broken/")
    request.resolver_match = SimpleNamespace(view_name="broken", route="broken/")

    def broken_response(_request):
        raise ValueError("private failure message")

    with pytest.raises(ValueError, match="private failure message"):
        RequestLoggingMiddleware(broken_response)(request)

    event = _event(captured_events, "http.request.completed")
    assert event["http.response.status_code"] == 500
    assert event["outcome"] == "failure"
    assert event["error.type"] == "ValueError"
    assert "private failure message" not in str(event)
    assert structlog.contextvars.get_contextvars() == {}


def test_request_middleware_process_exception_enriches_framework_generated_500(captured_events):
    request = _request("/broken/")
    request.resolver_match = SimpleNamespace(view_name="broken", route="broken/")
    middleware = RequestLoggingMiddleware(lambda _request: HttpResponse(status=500))

    middleware.process_exception(request, KeyError("private framework failure"))
    middleware(request)

    event = _event(captured_events, "http.request.completed")
    assert event["error.type"] == "KeyError"
    assert "private framework failure" not in str(event)


def test_request_middleware_skips_healthcheck_log_but_returns_request_id(captured_events):
    request = _request("/api/healthcheck")
    request.resolver_match = SimpleNamespace(view_name="api-1.0.0:healthcheck", route="healthcheck")

    response = RequestLoggingMiddleware(lambda _request: HttpResponse(status=200))(request)

    assert not any(event.get("event") == "http.request.completed" for event in captured_events)
    assert len(response.headers["X-Request-ID"]) == 32
    assert structlog.contextvars.get_contextvars() == {}
