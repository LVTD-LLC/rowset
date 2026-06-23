from types import SimpleNamespace

import pytest
from mcp.server.streamable_http import MCP_SESSION_ID_HEADER
from starlette.testclient import TestClient

from filebridge.asgi import application

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


def test_mcp_asgi_mount_uses_stateless_json_responses(monkeypatch, profile):
    monkeypatch.setattr(
        "apps.mcp_server.auth.resolve_api_key_profile",
        lambda _key: (profile, None),
    )
    monkeypatch.setattr(
        "apps.mcp_server.server._get_access_token_profile",
        lambda: profile,
    )

    with TestClient(application) as client:
        initialize_response = client.post(
            "/mcp/",
            headers=_authorization_headers(profile),
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
        tools_response = client.post(
            "/mcp/",
            headers=_authorization_headers(profile),
            json=_mcp_request("tools/list", 2),
        )
        user_response = client.post(
            "/mcp/",
            headers=_authorization_headers(profile),
            json=_mcp_request(
                "tools/call",
                3,
                {"name": "get_user_info", "arguments": {}},
            ),
        )

    assert initialize_response.status_code == 200
    assert initialize_response.headers["content-type"].startswith("application/json")
    assert MCP_SESSION_ID_HEADER not in initialize_response.headers

    assert tools_response.status_code == 200
    assert MCP_SESSION_ID_HEADER not in tools_response.headers
    tool_names = {
        tool["name"] for tool in tools_response.json()["result"]["tools"]
    }
    assert "get_user_info" in tool_names
    assert "list_dataset_rows" in tool_names

    assert user_response.status_code == 200
    assert MCP_SESSION_ID_HEADER not in user_response.headers
    content = user_response.json()["result"]["content"]
    assert content[0]["type"] == "text"
    assert "mcpasgiuser@example.com" in content[0]["text"]
