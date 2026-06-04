from urllib.parse import parse_qs, urlsplit

import anyio
import pytest
from django.test import override_settings
from django.urls import reverse
from fastmcp.server.auth import AccessToken
from mcp.server.auth.provider import AuthorizationParams
from mcp.shared.auth import OAuthClientInformationFull

from apps.mcp_server.oauth import (
    LEGACY_API_KEY_CLIENT_ID,
    MCP_INTERNAL_PATH,
    MCP_SCOPE,
    FileBridgeOAuthProvider,
    mcp_auth,
)
from apps.mcp_server.server import _authenticate_profile

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def user(django_user_model, monkeypatch):
    monkeypatch.setattr("apps.core.models.async_task", lambda *args, **kwargs: None)
    return django_user_model.objects.create_user(
        username="oauthuser",
        email="oauthuser@example.com",
        password="password123",
    )


@pytest.fixture
def auth_client(client, user):
    client.force_login(user)
    return client


@pytest.fixture
def profile(user):
    return user.profile


def _provider() -> FileBridgeOAuthProvider:
    provider = FileBridgeOAuthProvider(base_url="https://filebridge.example/mcp")
    provider.set_mcp_path(MCP_INTERNAL_PATH)
    return provider


def _client() -> OAuthClientInformationFull:
    return OAuthClientInformationFull(
        client_id="client-1",
        client_secret="secret",
        client_id_issued_at=1,
        redirect_uris=["http://127.0.0.1:8765/callback"],
        token_endpoint_auth_method="client_secret_post",
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        scope=MCP_SCOPE,
        client_name="Local Agent",
    )


@override_settings(SITE_URL="https://filebridge.example")
def test_oauth_authorization_approval_issues_access_token(auth_client, profile):
    provider = _provider()
    client_info = _client()

    anyio.run(provider.register_client, client_info)
    authorization_url = anyio.run(
        provider.authorize,
        client_info,
        AuthorizationParams(
            state="state-123",
            scopes=[MCP_SCOPE],
            code_challenge="challenge",
            redirect_uri="http://127.0.0.1:8765/callback",
            redirect_uri_provided_explicitly=True,
            resource="https://filebridge.example/mcp/",
        ),
    )

    authorization_parts = urlsplit(authorization_url)
    transaction_id = parse_qs(authorization_parts.query)["transaction"][0]

    response = auth_client.post(
        reverse("mcp_oauth_authorize"),
        {"transaction": transaction_id, "action": "approve"},
    )

    assert response.status_code == 302
    redirect_parts = urlsplit(response["Location"])
    redirect_query = parse_qs(redirect_parts.query)
    authorization_code = redirect_query["code"][0]
    assert redirect_query["state"] == ["state-123"]

    loaded_code = anyio.run(provider.load_authorization_code, client_info, authorization_code)
    token = anyio.run(provider.exchange_authorization_code, client_info, loaded_code)
    access_token = anyio.run(provider.load_access_token, token.access_token)

    assert token.refresh_token
    assert token.scope == MCP_SCOPE
    assert access_token.subject == str(profile.id)
    assert access_token.claims["email"] == profile.user.email
    assert access_token.scopes == [MCP_SCOPE]
    assert anyio.run(provider.load_authorization_code, client_info, authorization_code) is None


@override_settings(SITE_URL="https://filebridge.example")
def test_oauth_authorization_denial_redirects_with_error(auth_client):
    provider = _provider()
    client_info = _client()

    anyio.run(provider.register_client, client_info)
    authorization_url = anyio.run(
        provider.authorize,
        client_info,
        AuthorizationParams(
            state="state-123",
            scopes=[MCP_SCOPE],
            code_challenge="challenge",
            redirect_uri="http://127.0.0.1:8765/callback",
            redirect_uri_provided_explicitly=True,
            resource="https://filebridge.example/mcp/",
        ),
    )
    transaction_id = parse_qs(urlsplit(authorization_url).query)["transaction"][0]

    response = auth_client.post(
        reverse("mcp_oauth_authorize"),
        {"transaction": transaction_id, "action": "deny"},
    )

    assert response.status_code == 302
    redirect_query = parse_qs(urlsplit(response["Location"]).query)
    assert redirect_query["error"] == ["access_denied"]
    assert redirect_query["state"] == ["state-123"]


def test_oauth_provider_accepts_legacy_bearer_api_key(profile):
    provider = _provider()

    access_token = anyio.run(provider.load_access_token, profile.key)

    assert access_token.client_id == LEGACY_API_KEY_CLIENT_ID
    assert access_token.subject == str(profile.id)
    assert access_token.claims["legacy_api_key"] is True


def test_authenticate_profile_uses_oauth_access_token(monkeypatch, profile):
    monkeypatch.setattr(
        "apps.mcp_server.server.get_access_token",
        lambda: AccessToken(
            token="token",
            client_id="client-1",
            scopes=[MCP_SCOPE],
            subject=str(profile.id),
        ),
    )

    assert _authenticate_profile() == profile


def test_root_well_known_routes_include_mounted_mcp_metadata():
    paths = [route.path for route in mcp_auth.get_well_known_routes(mcp_path=MCP_INTERNAL_PATH)]

    assert "/.well-known/oauth-authorization-server/mcp" in paths
    assert "/.well-known/oauth-protected-resource/mcp/" in paths
