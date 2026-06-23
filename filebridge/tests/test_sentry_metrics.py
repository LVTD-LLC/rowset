from types import SimpleNamespace

import pytest
from django.http import HttpResponse
from django.test import RequestFactory, override_settings

from filebridge.sentry_metrics import (
    MIDDLEWARE_PATH,
    SentryMetricsMiddleware,
    install_sentry_metrics_middleware,
)


def test_install_sentry_metrics_middleware_wraps_full_stack():
    middleware = [
        "django.middleware.security.SecurityMiddleware",
        "whitenoise.middleware.WhiteNoiseMiddleware",
        "django.contrib.sessions.middleware.SessionMiddleware",
    ]

    install_sentry_metrics_middleware(middleware)
    install_sentry_metrics_middleware(middleware)

    assert middleware[0] == MIDDLEWARE_PATH
    assert middleware.count(MIDDLEWARE_PATH) == 1


@override_settings(SENTRY_ENABLE_METRICS=True)
def test_sentry_metrics_middleware_records_request_metrics(monkeypatch):
    counts = []
    distributions = []

    def record_count(*args, **kwargs):
        counts.append((args, kwargs))

    def record_distribution(*args, **kwargs):
        distributions.append((args, kwargs))

    monkeypatch.setattr("filebridge.sentry_metrics.metrics.count", record_count)
    monkeypatch.setattr(
        "filebridge.sentry_metrics.metrics.distribution",
        record_distribution,
    )

    request = RequestFactory().get("/datasets/")
    request.resolver_match = SimpleNamespace(view_name="dataset_list", route="")
    middleware = SentryMetricsMiddleware(lambda _request: HttpResponse(status=201))

    response = middleware(request)

    assert response.status_code == 201
    assert counts == [
        (
            ("http.server.requests", 1),
            {
                "attributes": {
                    "method": "GET",
                    "route": "dataset_list",
                    "status_code": 201,
                    "status_class": "2xx",
                }
            },
        )
    ]
    assert distributions[0][0][0] == "http.server.duration"
    assert distributions[0][1]["unit"] == "millisecond"
    assert distributions[0][1]["attributes"]["route"] == "dataset_list"


@override_settings(SENTRY_ENABLE_METRICS=True)
def test_sentry_metrics_middleware_records_raised_exceptions(monkeypatch):
    counts = []

    def record_count(*args, **kwargs):
        counts.append((args, kwargs))

    monkeypatch.setattr("filebridge.sentry_metrics.metrics.count", record_count)
    monkeypatch.setattr(
        "filebridge.sentry_metrics.metrics.distribution",
        lambda *args, **kwargs: None,
    )

    request = RequestFactory().get("/broken/")
    request.resolver_match = SimpleNamespace(view_name="broken_view", route="")

    def broken_response(_request):
        raise ValueError("boom")

    middleware = SentryMetricsMiddleware(broken_response)

    with pytest.raises(ValueError, match="boom"):
        middleware(request)

    assert counts[0][1]["attributes"] == {
        "method": "GET",
        "route": "broken_view",
        "status_code": 500,
        "status_class": "5xx",
    }


@override_settings(SENTRY_ENABLE_METRICS=False)
def test_sentry_metrics_middleware_can_be_disabled(monkeypatch):
    monkeypatch.setattr(
        "filebridge.sentry_metrics.metrics.count",
        lambda *args, **kwargs: pytest.fail("metrics should be disabled"),
    )

    request = RequestFactory().get("/datasets/")
    middleware = SentryMetricsMiddleware(lambda _request: HttpResponse(status=200))

    response = middleware(request)

    assert response.status_code == 200
