import anyio
import pytest
from django.test import override_settings
from fastmcp.server.auth import AccessToken

from apps.core.choices import AgentApiKeyAccessLevel
from apps.core.services import create_agent_api_key
from apps.mcp_server.auth import (
    AGENT_API_KEY_CLIENT_ID,
    MCP_INTERNAL_PATH,
    MCP_SCOPE,
    RowsetApiKeyAuthProvider,
    mcp_auth,
)
from apps.mcp_server.server import (
    AGENT_API_KEY_PROFILE_ATTR,
    _attach_agent_api_key,
    _authenticate_profile,
    _mcp_authenticated_profile,
)

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def user(django_user_model, monkeypatch):
    monkeypatch.setattr("apps.core.models.async_task", lambda *args, **kwargs: None)
    return django_user_model.objects.create_user(
        username="mcpauthuser",
        email="mcpauthuser@example.com",
        password="password123",
    )


@pytest.fixture
def profile(user):
    return user.profile


def _provider() -> RowsetApiKeyAuthProvider:
    return RowsetApiKeyAuthProvider()


@override_settings(SITE_URL="https://rowset.example")
def test_api_key_provider_accepts_named_agent_api_key(profile):
    provider = _provider()
    credential = create_agent_api_key(profile, "Codex", AgentApiKeyAccessLevel.ADMIN)

    access_token = anyio.run(provider.verify_token, credential.raw_key)

    assert access_token.client_id == AGENT_API_KEY_CLIENT_ID
    assert access_token.subject == str(profile.id)
    assert access_token.claims["iss"] == "https://rowset.example/mcp"
    assert access_token.claims["agent_api_key_id"] == credential.agent_api_key.id
    assert access_token.claims["agent_api_key_name"] == "Codex"
    assert access_token.claims["agent_api_key_access_level"] == AgentApiKeyAccessLevel.ADMIN
    assert access_token.claims["setup_completed"] is False
    credential.agent_api_key.refresh_from_db()
    assert credential.agent_api_key.last_used_at is not None
    profile.refresh_from_db()
    assert profile.trial_started_at is None
    assert profile.trial_ends_at is None


def test_api_key_provider_rejects_invalid_key():
    provider = _provider()

    assert anyio.run(provider.verify_token, "not-a-rowset-key") is None


def test_authenticate_profile_uses_access_token(monkeypatch, profile):
    monkeypatch.setattr(
        "apps.mcp_server.server.get_access_token",
        lambda: AccessToken(
            token="token",
            client_id=AGENT_API_KEY_CLIENT_ID,
            scopes=[MCP_SCOPE],
            subject=str(profile.id),
        ),
    )

    assert _authenticate_profile() == profile


def test_authenticate_profile_rejects_missing_access_token(monkeypatch):
    monkeypatch.setattr("apps.mcp_server.server.get_access_token", lambda: None)

    with pytest.raises(PermissionError, match="Authorization: Bearer"):
        _authenticate_profile()


def test_authorized_read_mcp_tool_request_does_not_start_trial(monkeypatch, profile):
    credential = create_agent_api_key(profile, "OpenClaw")
    monkeypatch.setattr(
        "apps.mcp_server.server._authenticate_profile",
        lambda: _attach_agent_api_key(profile, credential.agent_api_key),
    )

    authenticated_profile = _mcp_authenticated_profile()

    assert authenticated_profile == profile
    profile.refresh_from_db()
    assert profile.trial_started_at is None
    assert profile.trial_ends_at is None


def test_authorized_write_mcp_tool_request_starts_trial(monkeypatch, profile):
    credential = create_agent_api_key(profile, "OpenClaw")
    monkeypatch.setattr(
        "apps.mcp_server.server._authenticate_profile",
        lambda: _attach_agent_api_key(profile, credential.agent_api_key),
    )

    authenticated_profile = _mcp_authenticated_profile(AgentApiKeyAccessLevel.READ_WRITE)

    assert authenticated_profile == profile
    profile.refresh_from_db()
    assert profile.trial_started_at is not None
    assert profile.trial_ends_at is not None


def test_authenticate_profile_attaches_named_agent_api_key_from_access_token(
    monkeypatch,
    profile,
):
    credential = create_agent_api_key(profile, "OpenClaw")
    monkeypatch.setattr(
        "apps.mcp_server.server.get_access_token",
        lambda: AccessToken(
            token="token",
            client_id=AGENT_API_KEY_CLIENT_ID,
            scopes=[MCP_SCOPE],
            subject=str(profile.id),
            claims={
                "profile_id": profile.id,
                "agent_api_key_id": credential.agent_api_key.id,
                "agent_api_key_name": "OpenClaw",
            },
        ),
    )

    authenticated_profile = _authenticate_profile()

    assert authenticated_profile == profile
    assert getattr(authenticated_profile, AGENT_API_KEY_PROFILE_ATTR) == credential.agent_api_key


def test_authenticate_profile_rejects_stale_agent_api_key_access_token(monkeypatch, profile):
    monkeypatch.setattr(
        "apps.mcp_server.server.get_access_token",
        lambda: AccessToken(
            token="token",
            client_id=AGENT_API_KEY_CLIENT_ID,
            scopes=[MCP_SCOPE],
            subject=str(profile.id),
            claims={
                "profile_id": profile.id,
                "agent_api_key_id": 999999,
                "agent_api_key_name": "Deleted Agent",
            },
        ),
    )

    with pytest.raises(PermissionError, match="no longer active"):
        _authenticate_profile()


def test_mcp_auth_exposes_no_oauth_well_known_routes():
    assert mcp_auth.get_well_known_routes(mcp_path=MCP_INTERNAL_PATH) == []


def test_removed_mcp_authorize_route_is_404(client):
    response = client.get("/oauth/mcp/authorize/")

    assert response.status_code == 404
