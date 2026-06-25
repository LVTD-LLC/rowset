import json
from types import SimpleNamespace

import pytest
from mcp.server.streamable_http import MCP_SESSION_ID_HEADER
from starlette.testclient import TestClient

from apps.api.services import DatasetServiceError
from rowset.asgi import application

MCP_HEADERS = {
    "accept": "application/json, text/event-stream",
    "content-type": "application/json",
}
PROTOCOL_VERSION = "2025-06-18"


@pytest.fixture
def profile():
    user = SimpleNamespace(
        id=7,
        email="mcpasgiuser@example.com",
        username="mcpasgiuser",
        first_name="MCP",
        last_name="User",
        date_joined="2026-05-14T00:00:00Z",
        get_full_name=lambda: "MCP User",
    )
    return SimpleNamespace(
        id=11,
        key="rsk_test",
        user=user,
        state="signed_up",
        has_active_subscription=False,
    )


@pytest.fixture
def authenticated_mcp(monkeypatch, profile):
    # FastMCP's auth provider validates the bearer token before tool dispatch.
    monkeypatch.setattr(
        "apps.mcp_server.auth.resolve_api_key_profile",
        lambda _key: (profile, None),
    )
    # Rowset tool code then resolves the authenticated profile from the access token context.
    monkeypatch.setattr(
        "apps.mcp_server.server._get_access_token_profile",
        lambda: profile,
    )
    return profile


def _mcp_request(method, request_id, params=None):
    payload = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
    }
    if params is not None:
        payload["params"] = params
    return payload


def _authorization_headers(profile):
    return {
        **MCP_HEADERS,
        "authorization": f"Bearer {profile.key}",
    }


def _assert_stateless_json_response(response):
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert MCP_SESSION_ID_HEADER not in response.headers


def _assert_jsonrpc_result(response):
    _assert_stateless_json_response(response)
    payload = response.json()
    assert "result" in payload, payload
    assert "error" not in payload, payload
    return payload["result"]


def test_mcp_initialize_uses_stateless_json_response(authenticated_mcp):
    with TestClient(application) as client:
        initialize_response = client.post(
            "/mcp/",
            headers=_authorization_headers(authenticated_mcp),
            json=_mcp_request(
                "initialize",
                1,
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "rowset-test", "version": "0.1"},
                },
            ),
        )

    result = _assert_jsonrpc_result(initialize_response)
    assert result["protocolVersion"] == PROTOCOL_VERSION
    assert result["serverInfo"]["name"] == "Rowset"


def test_mcp_tools_list_uses_stateless_json_response(authenticated_mcp):
    with TestClient(application) as client:
        tools_response = client.post(
            "/mcp/",
            headers=_authorization_headers(authenticated_mcp),
            json=_mcp_request("tools/list", 2),
        )

    result = _assert_jsonrpc_result(tools_response)
    tools = result["tools"]
    assert tools
    tool_names = {tool["name"] for tool in tools}
    assert "get_user_info" in tool_names
    assert "list_dataset_rows" in tool_names


def test_mcp_get_user_info_uses_stateless_json_response(authenticated_mcp):
    with TestClient(application) as client:
        user_response = client.post(
            "/mcp/",
            headers=_authorization_headers(authenticated_mcp),
            json=_mcp_request(
                "tools/call",
                3,
                {"name": "get_user_info", "arguments": {}},
            ),
        )

    result = _assert_jsonrpc_result(user_response)
    content = result["content"]
    assert content
    assert content[0]["type"] == "text"
    assert "mcpasgiuser@example.com" in content[0]["text"]


def test_mcp_tool_service_errors_return_structured_error_envelope(
    authenticated_mcp,
    monkeypatch,
):
    def missing_row(profile, dataset_key, row_id):
        raise DatasetServiceError(404, "Row not found.")

    monkeypatch.setattr("apps.mcp_server.server.get_profile_dataset_row", missing_row)

    with TestClient(application) as client:
        row_response = client.post(
            "/mcp/",
            headers=_authorization_headers(authenticated_mcp),
            json=_mcp_request(
                "tools/call",
                4,
                {
                    "name": "get_dataset_row",
                    "arguments": {"dataset_key": "dataset-key", "row_id": 999},
                },
            ),
        )

    result = _assert_jsonrpc_result(row_response)
    assert result["isError"] is True
    error = json.loads(result["content"][0]["text"])
    assert error == {
        "code": "ROW_NOT_FOUND",
        "message": "Row not found.",
        "retryable": False,
        "suggested_action": "Check the row id or index value and try again.",
        "details": {"http_status": 404},
    }


def test_mcp_tool_permission_errors_return_structured_error_envelope(
    authenticated_mcp,
    monkeypatch,
):
    def reject():
        raise PermissionError("Invalid Rowset API key")

    monkeypatch.setattr("apps.mcp_server.server._authenticate_profile", reject)

    with TestClient(application) as client:
        user_response = client.post(
            "/mcp/",
            headers=_authorization_headers(authenticated_mcp),
            json=_mcp_request(
                "tools/call",
                5,
                {"name": "get_user_info", "arguments": {}},
            ),
        )

    result = _assert_jsonrpc_result(user_response)
    assert result["isError"] is True
    error = json.loads(result["content"][0]["text"])
    assert error == {
        "code": "AUTHENTICATION_FAILED",
        "message": "Invalid Rowset API key.",
        "retryable": False,
        "suggested_action": (
            "Check that the MCP request sends Authorization: Bearer <ROWSET_API_KEY> "
            "with an active Rowset API key."
        ),
        "details": {"http_status": 401},
    }
