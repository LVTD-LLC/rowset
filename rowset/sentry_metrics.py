import time
from collections.abc import Callable
from typing import Any

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from sentry_sdk import metrics

MIDDLEWARE_PATH = "rowset.sentry_metrics.SentryMetricsMiddleware"


def install_sentry_metrics_middleware(middleware: list[str]) -> None:
    if MIDDLEWARE_PATH in middleware:
        middleware.remove(MIDDLEWARE_PATH)
    middleware.insert(0, MIDDLEWARE_PATH)


def _route_name(request: HttpRequest) -> str:
    resolver_match = getattr(request, "resolver_match", None)
    if resolver_match is None:
        return "unresolved"

    if resolver_match.view_name:
        return resolver_match.view_name

    route = getattr(resolver_match, "route", "")
    return route or "unresolved"


def _attributes(request: HttpRequest, status_code: int) -> dict[str, Any]:
    status_class = f"{status_code // 100}xx"
    return {
        "method": request.method,
        "route": _route_name(request),
        "status_code": status_code,
        "status_class": status_class,
    }


class SentryMetricsMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        start = time.perf_counter()

        try:
            response = self.get_response(request)
        except Exception:
            self._record(request, 500, start)
            raise

        self._record(request, response.status_code, start)
        return response

    def _record(self, request: HttpRequest, status_code: int, start: float) -> None:
        if not getattr(settings, "SENTRY_ENABLE_METRICS", False):
            return

        attributes = _attributes(request, status_code)
        duration_ms = (time.perf_counter() - start) * 1000

        metrics.count("http.server.requests", 1, attributes=attributes)
        metrics.distribution(
            "http.server.duration",
            duration_ms,
            unit="millisecond",
            attributes=attributes,
        )
