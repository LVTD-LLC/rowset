import asyncio
from types import SimpleNamespace

import pytest
import structlog
from django.http import HttpResponse
from django.test import RequestFactory
from django.utils.functional import SimpleLazyObject
from django_htmx.middleware import HtmxDetails

from rowset.request_logging import RequestLoggingMiddleware
from rowset.utils import get_rowset_logger


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

    event = captured_events.event("http.request.completed")
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


def test_request_middleware_runs_natively_in_async_mode(captured_events):
    request = _request()

    async def async_response(_request):
        return HttpResponse(status=202)

    response = asyncio.run(RequestLoggingMiddleware(async_response)(request))

    event = captured_events.event("http.request.completed")
    assert response.status_code == 202
    assert event["http.response.status_code"] == 202
    assert event["outcome"] == "success"


def test_request_middleware_does_not_resolve_unused_lazy_session_user(captured_events):
    request = _request()
    evaluations = 0

    def load_user():
        nonlocal evaluations
        evaluations += 1
        return SimpleNamespace(id=3, is_authenticated=True, profile=SimpleNamespace(id=7))

    request.user = SimpleLazyObject(load_user)

    RequestLoggingMiddleware(lambda _request: HttpResponse(status=200))(request)

    event = captured_events.event("http.request.completed")
    assert evaluations == 0
    assert "user_id" not in event
    assert "profile_id" not in event


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

    domain_event = captured_events.event("dataset.operation.completed")
    request_event = captured_events.event("http.request.completed")
    assert domain_event["request.id"] == request_event["request.id"]
    assert request_event["user_id"] == 3
    assert request_event["profile_id"] == 7
    assert request_event["posthogDistinctId"] == "7"
    assert request_event["auth.method"] == "session"


def test_request_middleware_classifies_rest_requests(captured_events):
    request = RequestFactory().get(
        "/api/datasets",
        HTTP_USER_AGENT="Mozilla/5.0 Chrome/126.0.0.0 Safari/537.36",
    )
    request.user = SimpleNamespace(is_authenticated=False)
    request.resolver_match = SimpleNamespace(view_name="api-datasets", route="api/datasets")

    RequestLoggingMiddleware(lambda _request: HttpResponse(status=404))(request)

    event = captured_events.event("http.request.completed")
    assert event["request.interface"] == "rest"
    assert event["traffic_category"] == "api_client"
    assert "user_agent" not in event
    assert "Mozilla/5.0 Chrome/126.0.0.0 Safari/537.36" not in str(event)
    assert event["http.response.status_class"] == "4xx"
    assert event["outcome"] == "failure"


def test_request_middleware_adds_server_derived_traffic_category_to_nested_logs(captured_events):
    request = RequestFactory().get("/pricing", HTTP_USER_AGENT="ChatGPT-User/1.0")
    request.user = SimpleNamespace(is_authenticated=False)
    request.resolver_match = SimpleNamespace(view_name="pricing", route="pricing")
    domain_logger = get_rowset_logger("request-test-domain")

    def response_with_domain_log(_request):
        domain_logger.info("page.rendered")
        return HttpResponse()

    RequestLoggingMiddleware(response_with_domain_log)(request)

    assert captured_events.event("page.rendered")["traffic_category"] == "ai_agent"
    assert captured_events.event("http.request.completed")["traffic_category"] == "ai_agent"


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

    event = captured_events.event("http.request.completed")
    assert event["sessionId"] == "session-123_abc"


def test_request_middleware_rejects_unsafe_posthog_session_id(captured_events):
    request = RequestFactory().get(
        "/datasets/",
        HTTP_X_POSTHOG_SESSION_ID="private\nsession",
    )
    request.user = SimpleNamespace(is_authenticated=False)
    request.resolver_match = SimpleNamespace(view_name="dataset_list", route="datasets/")

    RequestLoggingMiddleware(lambda _request: HttpResponse())(request)

    event = captured_events.event("http.request.completed")
    assert "sessionId" not in event


def test_request_middleware_logs_server_error_type_and_clears_context(captured_events):
    request = _request("/broken/")
    request.resolver_match = SimpleNamespace(view_name="broken", route="broken/")

    def broken_response(_request):
        raise ValueError("private failure message")

    with pytest.raises(ValueError, match="private failure message"):
        RequestLoggingMiddleware(broken_response)(request)

    event = captured_events.event("http.request.completed")
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

    event = captured_events.event("http.request.completed")
    assert event["error.type"] == "KeyError"
    assert "private framework failure" not in str(event)


def test_request_middleware_skips_healthcheck_log_but_returns_request_id(captured_events):
    request = _request("/api/healthcheck")
    request.resolver_match = SimpleNamespace(view_name="api-1.0.0:healthcheck", route="healthcheck")

    response = RequestLoggingMiddleware(lambda _request: HttpResponse(status=200))(request)

    assert not any(event.get("event") == "http.request.completed" for event in captured_events)
    assert len(response.headers["X-Request-ID"]) == 32
    assert structlog.contextvars.get_contextvars() == {}
