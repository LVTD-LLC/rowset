from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import structlog
from asgiref.sync import iscoroutinefunction, markcoroutinefunction
from django.core.exceptions import ObjectDoesNotExist
from django.http import HttpRequest, HttpResponse
from django.utils.functional import LazyObject, empty

from rowset.logging_context import (
    bind_actor_context,
    correlation_id_or_new,
    route_name,
    validate_correlation_id,
)
from rowset.utils import get_rowset_logger

logger = get_rowset_logger(__name__)

_HEALTHCHECK_PATHS = frozenset({"/api/healthcheck"})
_PUBLIC_ACCESS_STATES = frozenset({"available", "locked", "denied", "disabled", "not_found"})
_PUBLIC_CONTENT_SURFACES = frozenset({"preview", "row_detail", "markdown", "export"})


def _request_id(request: HttpRequest) -> str:
    return correlation_id_or_new(request.headers.get("X-Request-ID"))


def _posthog_session_id(request: HttpRequest) -> str:
    return validate_correlation_id(request.headers.get("X-PostHog-Session-ID")) or ""


def _request_interface(request: HttpRequest) -> str:
    if request.path.startswith("/api/"):
        return "rest"
    if bool(getattr(request, "htmx", False)):
        return "htmx"
    return "web"


def _bind_session_actor(request: HttpRequest) -> None:
    user = getattr(request, "user", None)
    if isinstance(user, LazyObject) and user._wrapped is empty:
        return
    if user is None or not getattr(user, "is_authenticated", False):
        return

    structlog.contextvars.bind_contextvars(user_id=user.id)
    user_state = getattr(user, "_state", None)
    if user_state is not None and "profile" not in user_state.fields_cache:
        return
    try:
        profile = user.profile
    except AttributeError:
        return
    except ObjectDoesNotExist:
        return
    bind_actor_context(profile_id=profile.id, auth_method="session")


def _is_healthcheck(request: HttpRequest) -> bool:
    return request.path.rstrip("/") in _HEALTHCHECK_PATHS


class RequestLoggingMiddleware:
    sync_capable = True
    async_capable = True

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]):
        self.get_response = get_response
        self.async_mode = iscoroutinefunction(get_response)
        if self.async_mode:
            markcoroutinefunction(self)

    def _begin_request(self, request: HttpRequest) -> tuple[float, str]:
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
        return started_at, request_id

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if self.async_mode:
            return self.__acall__(request)
        return self.__scall__(request)

    def __scall__(self, request: HttpRequest) -> HttpResponse:
        started_at, request_id = self._begin_request(request)

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

    async def __acall__(self, request: HttpRequest) -> HttpResponse:
        started_at, request_id = self._begin_request(request)

        status_code = 500
        error_type = str(getattr(request, "_rowset_error_type", ""))
        try:
            response = await self.get_response(request)
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
        # Pick up identity resolved by the view without forcing authentication or profile queries.
        _bind_session_actor(request)
        htmx = getattr(request, "htmx", None)
        attributes: dict[str, Any] = {
            "http.request.method": request.method,
            "http.route": route_name(request),
            "http.response.status_code": status_code,
            "http.response.status_class": f"{status_code // 100}xx",
            "http.is_htmx": bool(htmx),
            "htmx.boosted": bool(getattr(htmx, "boosted", False)),
            "htmx.history_restore_request": bool(getattr(htmx, "history_restore_request", False)),
            "duration_ms": round((time.perf_counter() - started_at) * 1_000, 2),
            "outcome": "failure" if status_code >= 400 else "success",
        }
        if error_type:
            attributes["error.type"] = error_type

        public_access_state = getattr(request, "_rowset_public_access_state", "")
        if public_access_state == "available" and status_code >= 400:
            public_access_state = ""
        if public_access_state in _PUBLIC_ACCESS_STATES and status_code < 500:
            attributes["public_access_state"] = public_access_state
            attributes["content_group"] = "public_dataset"
            content_surface = getattr(request, "_rowset_public_content_surface", "")
            if content_surface in _PUBLIC_CONTENT_SURFACES:
                attributes["content_surface"] = content_surface
            content_id = getattr(request, "_rowset_public_content_id", "")
            if public_access_state == "available" and content_id:
                attributes["content_id"] = content_id

        log_method = logger.error if status_code >= 500 else logger.info
        log_method("http.request.completed", **attributes)
