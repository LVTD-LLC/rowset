from __future__ import annotations

import time
from typing import Any

import structlog
from asgiref.sync import sync_to_async
from django.db import DatabaseError
from fastmcp.server.dependencies import get_access_token, get_http_request
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext

from apps.core.services import mark_profile_setup_completed
from rowset.logging_context import bind_actor_context, correlation_id_or_new
from rowset.traffic import classify_traffic
from rowset.utils import get_rowset_logger

logger = get_rowset_logger(__name__)


def _request_id() -> str:
    try:
        request = get_http_request()
    except RuntimeError:
        return correlation_id_or_new(None)
    return correlation_id_or_new(request.headers.get("x-request-id"))


def _bind_access_token_actor() -> dict[str, Any] | None:
    try:
        access_token = get_access_token()
    except RuntimeError:
        return
    if access_token is None:
        return

    claims = access_token.claims or {}
    profile_identifier = access_token.subject or claims.get("profile_id")
    try:
        profile_id = int(profile_identifier)
    except TypeError:
        return
    except ValueError:
        return

    agent_api_key_identifier = claims.get("agent_api_key_id")
    try:
        agent_api_key_id = (
            int(agent_api_key_identifier) if agent_api_key_identifier is not None else None
        )
    except TypeError:
        agent_api_key_id = None
    except ValueError:
        agent_api_key_id = None

    bind_actor_context(
        profile_id=profile_id,
        agent_api_key_id=agent_api_key_id,
        agent_api_key_access_level=str(claims.get("agent_api_key_access_level") or ""),
        auth_method="mcp_bearer",
    )
    if agent_api_key_id is not None and not claims.get("setup_completed"):
        return {
            "profile_id": profile_id,
            "agent_api_key_id": agent_api_key_id,
            "agent_api_key_access_level": str(claims.get("agent_api_key_access_level") or ""),
        }
    return None


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
            "traffic_category": classify_traffic(request_interface="mcp", user_agent=None),
        }
        tool_name = getattr(context.message, "name", "") if context.method == "tools/call" else ""
        if tool_name:
            request_context["mcp.tool.name"] = str(tool_name)
        structlog.contextvars.bind_contextvars(**request_context)
        setup_actor = _bind_access_token_actor()

        outcome = "success"
        error_type = ""
        try:
            result = await call_next(context)
            if bool(getattr(result, "is_error", False)):
                outcome = "failure"
            elif setup_actor is not None:
                try:
                    await sync_to_async(mark_profile_setup_completed, thread_sensitive=True)(
                        setup_actor["profile_id"],
                        interface="mcp",
                        agent_api_key_id=setup_actor["agent_api_key_id"],
                        agent_api_key_access_level=setup_actor["agent_api_key_access_level"],
                    )
                except DatabaseError as exc:
                    logger.warning(
                        "agent_setup.completion_failed",
                        error_type=type(exc).__name__,
                        profile_id=setup_actor["profile_id"],
                        request_interface="mcp",
                    )
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
