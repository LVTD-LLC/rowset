import json
from types import SimpleNamespace

import pytest
from mcp.server.streamable_http import MCP_SESSION_ID_HEADER
from starlette.testclient import TestClient

from apps.api.services import DatasetServiceError
from apps.core.choices import AgentApiKeyAccessLevel
from apps.mcp_server.server import AGENT_API_KEY_PROFILE_ATTR, mcp
from rowset.asgi import application

MCP_HEADERS = {
    "accept": "application/json, text/event-stream",
    "content-type": "application/json",
}
PROTOCOL_VERSION = "2025-06-18"


def _mcp_logging_globals():
    middleware = next(
        item for item in mcp.middleware if item.__class__.__name__ == "RowsetMCPLoggingMiddleware"
    )
    return middleware.on_request.__func__.__globals__


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
    agent_api_key = SimpleNamespace(
        id=31,
        name="ASGI Test Agent",
        access_level=AgentApiKeyAccessLevel.READ_WRITE,
    )
    profile = SimpleNamespace(
        id=11,
        key="rsk_test",
        user=user,
        state="signed_up",
        has_active_subscription=False,
        trial_started_at=None,
        trial_ends_at=None,
        setup_completed_at=None,
        agent_api_key=agent_api_key,
    )
    setattr(profile, AGENT_API_KEY_PROFILE_ATTR, agent_api_key)
    return profile


@pytest.fixture
def authenticated_mcp(monkeypatch, profile):
    # FastMCP's auth provider validates the bearer token before tool dispatch.
    monkeypatch.setattr(
        "apps.mcp_server.auth.resolve_api_key_profile",
        lambda _key: (profile, profile.agent_api_key),
    )
    # Rowset tool code then resolves the authenticated profile from the access token context.
    monkeypatch.setattr(
        "apps.mcp_server.server._get_access_token_profile",
        lambda: profile,
    )
    monkeypatch.setattr(
        "apps.mcp_server.server.activate_or_require_trial_access",
        lambda _profile: None,
    )
    monkeypatch.setitem(
        _mcp_logging_globals(),
        "mark_profile_setup_completed",
        lambda _profile_id, **_kwargs: None,
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


def test_mcp_initialize_includes_essential_workflow_and_safety_instructions(authenticated_mcp):
    with TestClient(application) as client:
        response = client.post(
            "/mcp/",
            headers=_authorization_headers(authenticated_mcp),
            json=_mcp_request(
                "initialize",
                1,
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "clean-client", "version": "0.1"},
                },
            ),
        )

    instructions = _assert_jsonrpc_result(response)["instructions"].lower()
    required_guidance = (
        "small limits",
        "get_dataset",
        "before dataset-specific writes",
        "stable index",
        "by-index",
        "explicit user intent",
        "delete",
        "archive",
        "destructive schema changes",
        "clear preview passwords",
        "enable public access",
        "public previews",
        "read-only sharing surfaces",
        "not authentication",
    )
    missing_guidance = [guidance for guidance in required_guidance if guidance not in instructions]
    assert missing_guidance == []


@pytest.mark.parametrize(
    ("url", "headers"),
    [
        ("/mcp/?api_key=rsk_test", MCP_HEADERS),
        ("/mcp/", {**MCP_HEADERS, "x-api-key": "rsk_test"}),
    ],
)
def test_mcp_rejects_non_bearer_api_keys(authenticated_mcp, url, headers):
    with TestClient(application) as client:
        response = client.post(
            url,
            headers=headers,
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

    assert response.status_code == 401


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
    assert "get_rowset_capabilities" in tool_names
    assert "list_dataset_rows" in tool_names
    image_tool = next(tool for tool in tools if tool["name"] == "attach_image_to_dataset_row")
    assert "The target row must already exist" in image_tool["description"]
    assert "Hosted MCP cannot read local file paths" in image_tool["description"]
    image_base64_schema = image_tool["inputSchema"]["properties"]["image_base64"]
    assert "base64 or a data URI" in image_base64_schema["description"]
    audio_tool = next(tool for tool in tools if tool["name"] == "attach_audio_to_dataset_row")
    assert "The target row must already exist" in audio_tool["description"]
    assert "Hosted MCP cannot read local file paths" in audio_tool["description"]
    audio_base64_schema = audio_tool["inputSchema"]["properties"]["audio_base64"]
    assert "base64 or a data URI" in audio_base64_schema["description"]


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


def test_successful_mcp_requests_invoke_setup_completion(authenticated_mcp, monkeypatch):
    completed_profile_ids = []

    def record_setup_completion(profile_id, **_kwargs):
        completed_profile_ids.append(profile_id)

    monkeypatch.setitem(
        _mcp_logging_globals(),
        "mark_profile_setup_completed",
        record_setup_completion,
    )
    monkeypatch.setitem(
        _mcp_logging_globals(),
        "_bind_access_token_actor",
        lambda: authenticated_mcp.id,
    )

    with TestClient(application) as client:
        response = client.post(
            "/mcp/",
            headers=_authorization_headers(authenticated_mcp),
            json=_mcp_request(
                "initialize",
                90,
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "rowset-test", "version": "0.1"},
                },
            ),
        )

    _assert_jsonrpc_result(response)
    assert completed_profile_ids == [authenticated_mcp.id]
