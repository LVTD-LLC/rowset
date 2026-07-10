from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

import structlog
from django.http import HttpRequest

_SAFE_CORRELATION_ID = re.compile(r"[A-Za-z0-9._-]{1,128}")


def validate_correlation_id(value: str | None) -> str | None:
    candidate = (value or "").strip()
    return candidate if _SAFE_CORRELATION_ID.fullmatch(candidate) else None


def correlation_id_or_new(value: str | None) -> str:
    return validate_correlation_id(value) or uuid4().hex


def route_name(request: HttpRequest) -> str:
    resolver_match = getattr(request, "resolver_match", None)
    if resolver_match is None:
        return "unresolved"
    return resolver_match.view_name or getattr(resolver_match, "route", "") or "unresolved"


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
