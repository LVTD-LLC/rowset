import asyncio
import logging
from types import SimpleNamespace

import pytest
import structlog
from fastmcp.server.auth import AccessToken
from fastmcp.server.middleware import MiddlewareContext
from mcp.types import CallToolRequestParams, ListToolsRequest

from rowset.mcp_logging import RowsetMCPLoggingMiddleware


class CollectingHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.events: list[dict] = []

    def emit(self, record: logging.LogRecord) -> None:
        if isinstance(record.msg, dict):
            self.events.append(record.msg.copy())


@pytest.fixture
def captured_events():
    rowset_logger = logging.getLogger("rowset")
    handler = CollectingHandler()
    rowset_logger.addHandler(handler)
    try:
        yield handler.events
    finally:
        rowset_logger.removeHandler(handler)
        structlog.contextvars.clear_contextvars()


def _event(events: list[dict]) -> dict:
    return next(event for event in events if event.get("event") == "mcp.request.completed")


def _access_token() -> AccessToken:
    return AccessToken(
        token="secret-token-that-must-not-be-logged",
        client_id="rowset-agent-api-key",
        scopes=["rowset:mcp"],
        subject="11",
        claims={
            "profile_id": 11,
            "email": "private@example.com",
            "agent_api_key_id": 31,
            "agent_api_key_name": "Private agent name",
            "agent_api_key_access_level": "read_write",
        },
    )


def test_mcp_logging_emits_tool_name_identity_outcome_and_duration(
    captured_events,
    monkeypatch,
):
    monkeypatch.setattr("rowset.mcp_logging.get_access_token", _access_token)
    monkeypatch.setattr(
        "rowset.mcp_logging.get_http_request",
        lambda: SimpleNamespace(headers={"x-request-id": "mcp.req-1"}),
    )
    middleware = RowsetMCPLoggingMiddleware()
    context = MiddlewareContext(
        message=CallToolRequestParams(
            name="create_dataset",
            arguments={"rows": [{"private": "dataset value"}]},
        ),
        method="tools/call",
        type="request",
        source="client",
    )
    expected_result = SimpleNamespace(
        is_error=False,
        content=[{"private": "tool result"}],
    )

    async def call_next(_context):
        return expected_result

    result = asyncio.run(middleware.on_request(context, call_next))

    event = _event(captured_events)
    assert event["request.id"] == "mcp.req-1"
    assert event["request.interface"] == "mcp"
    assert event["mcp.tool.name"] == "create_dataset"
    assert event["rpc.method"] == "tools/call"
    assert event["profile_id"] == 11
    assert event["posthogDistinctId"] == "11"
    assert event["agent_api_key_id"] == 31
    assert event["agent_api_key_access_level"] == "read_write"
    assert event["outcome"] == "success"
    assert event["duration_ms"] >= 0
    assert "arguments" not in event
    assert "content" not in event
    assert "email" not in event
    assert "agent_api_key_name" not in event
    assert "secret-token-that-must-not-be-logged" not in str(event)
    assert result is expected_result
    assert structlog.contextvars.get_contextvars() == {}


def test_mcp_logging_emits_only_error_type_when_request_raises(captured_events, monkeypatch):
    monkeypatch.setattr("rowset.mcp_logging.get_access_token", lambda: None)

    def missing_http_request():
        raise RuntimeError("No active HTTP request")

    monkeypatch.setattr("rowset.mcp_logging.get_http_request", missing_http_request)
    middleware = RowsetMCPLoggingMiddleware()
    context = MiddlewareContext(
        message=ListToolsRequest(),
        method="tools/list",
        type="request",
        source="client",
    )

    async def call_next(_context):
        raise ValueError("private MCP failure message")

    with pytest.raises(ValueError, match="private MCP failure message"):
        asyncio.run(middleware.on_request(context, call_next))

    event = _event(captured_events)
    assert event["rpc.method"] == "tools/list"
    assert event["outcome"] == "failure"
    assert event["error.type"] == "ValueError"
    assert "mcp.tool.name" not in event
    assert "private MCP failure message" not in str(event)
    assert structlog.contextvars.get_contextvars() == {}


def test_mcp_logging_treats_error_results_as_failed_outcomes(captured_events, monkeypatch):
    monkeypatch.setattr("rowset.mcp_logging.get_access_token", lambda: None)
    monkeypatch.setattr(
        "rowset.mcp_logging.get_http_request",
        lambda: SimpleNamespace(headers={}),
    )
    middleware = RowsetMCPLoggingMiddleware()
    context = MiddlewareContext(
        message=CallToolRequestParams(name="get_dataset", arguments={}),
        method="tools/call",
        type="request",
        source="client",
    )

    async def call_next(_context):
        return SimpleNamespace(is_error=True, content=[{"private": "error detail"}])

    asyncio.run(middleware.on_request(context, call_next))

    event = _event(captured_events)
    assert event["outcome"] == "failure"
    assert "error detail" not in str(event)
