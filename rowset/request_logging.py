from __future__ import annotations

import re
import time
from collections.abc import Callable
from typing import Any
from uuid import uuid4

import structlog
from django.core.exceptions import ObjectDoesNotExist
from django.http import HttpRequest, HttpResponse

from rowset.utils import get_rowset_logger

logger = get_rowset_logger(__name__)

_SAFE_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,128}")
_HEALTHCHECK_PATHS = frozenset({"/api/healthcheck"})


def bind_actor_context(
    *,
    profile_id: int,
    agent_api_key_id: int | None = None,
    agent_api_key_access_level: str = "",
    auth_method: str,
) -> None:
    context: dict[str, Any] = {
        "profile_id": profile_id,
        "posthogDistinctId": str(profile_id),
        "auth.method": auth_method,
    }
    if agent_api_key_id is not None:
        context["agent_api_key_id"] = agent_api_key_id
    if agent_api_key_access_level:
        context["agent_api_key_access_level"] = agent_api_key_access_level
    structlog.contextvars.bind_contextvars(**context)


def _request_id(request: HttpRequest) -> str:
    supplied = request.headers.get("X-Request-ID", "").strip()
    if _SAFE_REQUEST_ID.fullmatch(supplied):
        return supplied
    return uuid4().hex


def _posthog_session_id(request: HttpRequest) -> str:
    supplied = request.headers.get("X-PostHog-Session-ID", "").strip()
    if _SAFE_REQUEST_ID.fullmatch(supplied):
        return supplied
    return ""


def _request_interface(request: HttpRequest) -> str:
    if request.path.startswith("/api/"):
        return "rest"
    if bool(getattr(request, "htmx", False)):
        return "htmx"
    return "web"


def _route_name(request: HttpRequest) -> str:
    resolver_match = getattr(request, "resolver_match", None)
    if resolver_match is None:
        return "unresolved"
    return resolver_match.view_name or getattr(resolver_match, "route", "") or "unresolved"


def _bind_session_actor(request: HttpRequest) -> None:
    user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_authenticated", False):
        return

    structlog.contextvars.bind_contextvars(user_id=user.id)
    try:
        profile = user.profile
    except AttributeError, ObjectDoesNotExist:
        return
    bind_actor_context(profile_id=profile.id, auth_method="session")


def _is_healthcheck(request: HttpRequest) -> bool:
    return request.path.rstrip("/") in _HEALTHCHECK_PATHS


class RequestLoggingMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        structlog.contextvars.clear_contextvars()
        started_at = time.perf_counter()
        request_id = _request_id(request)
        request_interface = _request_interface(request)
        structlog.contextvars.bind_contextvars(
            **{
                "request.id": request_id,
                "request.interface": request_interface,
            }
        )
        session_id = _posthog_session_id(request)
        if session_id:
            structlog.contextvars.bind_contextvars(sessionId=session_id)
        _bind_session_actor(request)

        status_code = 500
        error_type = str(getattr(request, "_rowset_error_type", ""))
        try:
            response = self.get_response(request)
            status_code = response.status_code
            error_type = error_type or str(getattr(request, "_rowset_error_type", ""))
            response.headers["X-Request-ID"] = request_id
            return response
        except Exception as exc:
            error_type = type(exc).__name__
            raise
        finally:
            try:
                if not _is_healthcheck(request):
                    self._log_completion(
                        request,
                        status_code=status_code,
                        started_at=started_at,
                        error_type=error_type,
                    )
            finally:
                structlog.contextvars.clear_contextvars()

    @staticmethod
    def process_exception(request: HttpRequest, exception: Exception) -> None:
        request._rowset_error_type = type(exception).__name__

    @staticmethod
    def _log_completion(
        request: HttpRequest,
        *,
        status_code: int,
        started_at: float,
        error_type: str,
    ) -> None:
        htmx = getattr(request, "htmx", None)
        attributes: dict[str, Any] = {
            "http.request.method": request.method,
            "http.route": _route_name(request),
            "http.response.status_code": status_code,
            "http.response.status_class": f"{status_code // 100}xx",
            "http.is_htmx": bool(htmx),
            "htmx.boosted": bool(getattr(htmx, "boosted", False)),
            "htmx.history_restore_request": bool(getattr(htmx, "history_restore_request", False)),
            "duration_ms": round((time.perf_counter() - started_at) * 1_000, 2),
            "outcome": "failure" if status_code >= 500 else "success",
        }
        if error_type:
            attributes["error.type"] = error_type

        log_method = logger.error if status_code >= 500 else logger.info
        log_method("http.request.completed", **attributes)
