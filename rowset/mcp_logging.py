from __future__ import annotations

import re
import time
from typing import Any
from uuid import uuid4

import structlog
from fastmcp.server.dependencies import get_access_token, get_http_request
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext

from rowset.request_logging import bind_actor_context
from rowset.utils import get_rowset_logger

logger = get_rowset_logger(__name__)

_SAFE_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,128}")


def _request_id() -> str:
    try:
        request = get_http_request()
    except RuntimeError:
        return uuid4().hex
    supplied = request.headers.get("x-request-id", "").strip()
    if _SAFE_REQUEST_ID.fullmatch(supplied):
        return supplied
    return uuid4().hex


def _bind_access_token_actor() -> None:
    try:
        access_token = get_access_token()
    except RuntimeError:
        return
    if access_token is None:
        return

    claims = access_token.claims or {}
    profile_identifier = claims.get("profile_id") or access_token.subject
    try:
        profile_id = int(profile_identifier)
    except TypeError, ValueError:
        return

    agent_api_key_identifier = claims.get("agent_api_key_id")
    try:
        agent_api_key_id = (
            int(agent_api_key_identifier) if agent_api_key_identifier is not None else None
        )
    except TypeError, ValueError:
        agent_api_key_id = None

    bind_actor_context(
        profile_id=profile_id,
        agent_api_key_id=agent_api_key_id,
        agent_api_key_access_level=str(claims.get("agent_api_key_access_level") or ""),
        auth_method="mcp_bearer",
    )


class RowsetMCPLoggingMiddleware(Middleware):
    async def on_request(
        self,
        context: MiddlewareContext[Any],
        call_next: CallNext[Any, Any],
    ) -> Any:
        structlog.contextvars.clear_contextvars()
        started_at = time.perf_counter()
        request_context: dict[str, Any] = {
            "request.id": _request_id(),
            "request.interface": "mcp",
            "rpc.method": context.method or "unknown",
        }
        tool_name = getattr(context.message, "name", "") if context.method == "tools/call" else ""
        if tool_name:
            request_context["mcp.tool.name"] = str(tool_name)
        structlog.contextvars.bind_contextvars(**request_context)
        _bind_access_token_actor()

        outcome = "success"
        error_type = ""
        try:
            result = await call_next(context)
            if bool(getattr(result, "is_error", False)):
                outcome = "failure"
            return result
        except Exception as exc:
            outcome = "failure"
            error_type = type(exc).__name__
            raise
        finally:
            try:
                attributes: dict[str, Any] = {
                    "duration_ms": round((time.perf_counter() - started_at) * 1_000, 2),
                    "outcome": outcome,
                }
                if error_type:
                    attributes["error.type"] = error_type
                log_method = logger.error if error_type else logger.info
                log_method("mcp.request.completed", **attributes)
            finally:
                structlog.contextvars.clear_contextvars()
