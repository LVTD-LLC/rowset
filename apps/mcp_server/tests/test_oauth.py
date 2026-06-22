from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import anyio
import pytest
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from fastmcp.server.auth import AccessToken
from mcp.server.auth.provider import AuthorizationParams
from mcp.shared.auth import OAuthClientInformationFull

from apps.core.services import create_agent_api_key
from apps.mcp_server.models import (
    McpOAuthAccessToken,
    McpOAuthAuthorizationCode,
    McpOAuthAuthorizationRequest,
    McpOAuthRefreshToken,
)
from apps.mcp_server.oauth import (
    AGENT_API_KEY_CLIENT_ID,
    LEGACY_API_KEY_CLIENT_ID,
    LEGACY_MCP_SCOPE,
    MCP_INTERNAL_PATH,
    MCP_SCOPE,
    RowsetOAuthProvider,
    get_authorization_request,
    hash_token,
    mcp_auth,
    prune_expired_oauth_artifacts,
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


def _provider() -> RowsetOAuthProvider:
    provider = RowsetOAuthProvider(base_url="https://rowset.example/mcp")
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


@override_settings(SITE_URL="https://rowset.example")
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
            resource="https://rowset.example/mcp/",
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


def test_oauth_load_access_token_normalizes_legacy_scope(profile):
    provider = _provider()
    expires_at = timezone.now() + timedelta(hours=1)
    McpOAuthAccessToken.objects.create(
        token_hash=hash_token("legacy-access"),
        client_id="client-1",
        profile=profile,
        scopes=[LEGACY_MCP_SCOPE],
        expires_at=expires_at,
    )

    access_token = anyio.run(provider.load_access_token, "legacy-access")

    assert access_token.scopes == [MCP_SCOPE]
    assert McpOAuthAccessToken.objects.get(token_hash=hash_token("legacy-access")).scopes == [
        MCP_SCOPE
    ]


def test_oauth_refresh_with_legacy_scope_issues_rowset_scope(profile):
    provider = _provider()
    client_info = _client()
    expires_at = timezone.now() + timedelta(hours=1)
    McpOAuthRefreshToken.objects.create(
        token_hash=hash_token("legacy-refresh"),
        client_id=client_info.client_id,
        profile=profile,
        scopes=[LEGACY_MCP_SCOPE],
        expires_at=expires_at,
    )

    loaded_refresh_token = anyio.run(
        provider.load_refresh_token,
        client_info,
        "legacy-refresh",
    )
    refreshed_token = anyio.run(
        provider.exchange_refresh_token,
        client_info,
        loaded_refresh_token,
        [],
    )
    access_token = anyio.run(provider.load_access_token, refreshed_token.access_token)

    assert loaded_refresh_token.scopes == [MCP_SCOPE]
    assert refreshed_token.scope == MCP_SCOPE
    assert access_token.scopes == [MCP_SCOPE]
    assert McpOAuthRefreshToken.objects.get(token_hash=hash_token("legacy-refresh")).revoked_at


@override_settings(SITE_URL="https://rowset.example")
def test_oauth_refresh_without_scope_reuses_original_scopes(auth_client):
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
            resource="https://rowset.example/mcp/",
        ),
    )
    transaction_id = parse_qs(urlsplit(authorization_url).query)["transaction"][0]
    response = auth_client.post(
        reverse("mcp_oauth_authorize"),
        {"transaction": transaction_id, "action": "approve"},
    )
    authorization_code = parse_qs(urlsplit(response["Location"]).query)["code"][0]

    loaded_code = anyio.run(provider.load_authorization_code, client_info, authorization_code)
    token = anyio.run(provider.exchange_authorization_code, client_info, loaded_code)
    loaded_refresh_token = anyio.run(
        provider.load_refresh_token,
        client_info,
        token.refresh_token,
    )

    refreshed_token = anyio.run(
        provider.exchange_refresh_token,
        client_info,
        loaded_refresh_token,
        [],
    )
    access_token = anyio.run(provider.load_access_token, refreshed_token.access_token)

    assert refreshed_token.scope == MCP_SCOPE
    assert access_token.scopes == [MCP_SCOPE]
    assert anyio.run(provider.load_refresh_token, client_info, token.refresh_token) is None


@override_settings(SITE_URL="https://rowset.example")
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
            resource="https://rowset.example/mcp/",
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


@override_settings(SITE_URL="https://rowset.example")
def test_oauth_authorization_rejects_unknown_post_action(auth_client):
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
            resource="https://rowset.example/mcp/",
        ),
    )
    transaction_id = parse_qs(urlsplit(authorization_url).query)["transaction"][0]

    response = auth_client.post(
        reverse("mcp_oauth_authorize"),
        {"transaction": transaction_id, "action": "unexpected"},
    )

    assert response.status_code == 400
    assert get_authorization_request(transaction_id) is not None


@override_settings(SITE_URL="https://rowset.example")
def test_oauth_authorization_handles_expired_post_race(auth_client, monkeypatch):
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
            resource="https://rowset.example/mcp/",
        ),
    )
    transaction_id = parse_qs(urlsplit(authorization_url).query)["transaction"][0]
    monkeypatch.setattr(
        "apps.mcp_server.views.approve_authorization_request",
        lambda *_args: (_ for _ in ()).throw(ValueError("Authorization request expired.")),
    )

    response = auth_client.post(
        reverse("mcp_oauth_authorize"),
        {"transaction": transaction_id, "action": "approve"},
    )

    assert response.status_code == 400
    assert b"Authorization request expired." in response.content


def test_prune_expired_oauth_artifacts_removes_stale_rows(profile):
    now = timezone.now()
    expired_at = now - timedelta(seconds=1)
    future_at = now + timedelta(hours=1)

    McpOAuthAuthorizationRequest.objects.create(
        transaction_id="expired-request",
        client_id="client-1",
        scopes=[MCP_SCOPE],
        code_challenge="challenge",
        redirect_uri="http://127.0.0.1:8765/callback",
        expires_at=expired_at,
    )
    McpOAuthAuthorizationRequest.objects.create(
        transaction_id="valid-request",
        client_id="client-1",
        scopes=[MCP_SCOPE],
        code_challenge="challenge",
        redirect_uri="http://127.0.0.1:8765/callback",
        expires_at=future_at,
    )
    McpOAuthAuthorizationCode.objects.create(
        code_hash=hash_token("expired-code"),
        client_id="client-1",
        profile=profile,
        scopes=[MCP_SCOPE],
        code_challenge="challenge",
        redirect_uri="http://127.0.0.1:8765/callback",
        expires_at=expired_at,
    )
    McpOAuthAuthorizationCode.objects.create(
        code_hash=hash_token("valid-code"),
        client_id="client-1",
        profile=profile,
        scopes=[MCP_SCOPE],
        code_challenge="challenge",
        redirect_uri="http://127.0.0.1:8765/callback",
        expires_at=future_at,
    )
    McpOAuthAccessToken.objects.create(
        token_hash=hash_token("expired-access"),
        client_id="client-1",
        profile=profile,
        scopes=[MCP_SCOPE],
        expires_at=expired_at,
    )
    McpOAuthAccessToken.objects.create(
        token_hash=hash_token("valid-access"),
        client_id="client-1",
        profile=profile,
        scopes=[MCP_SCOPE],
        expires_at=future_at,
    )
    McpOAuthRefreshToken.objects.create(
        token_hash=hash_token("revoked-refresh"),
        client_id="client-1",
        profile=profile,
        scopes=[MCP_SCOPE],
        expires_at=future_at,
        revoked_at=now,
    )
    McpOAuthRefreshToken.objects.create(
        token_hash=hash_token("valid-refresh"),
        client_id="client-1",
        profile=profile,
        scopes=[MCP_SCOPE],
        expires_at=future_at,
    )

    counts = prune_expired_oauth_artifacts()

    assert counts == {
        "authorization_requests": 1,
        "authorization_codes": 1,
        "access_tokens": 1,
        "refresh_tokens": 1,
    }
    assert McpOAuthAuthorizationRequest.objects.filter(transaction_id="valid-request").exists()
    assert McpOAuthAuthorizationCode.objects.filter(code_hash=hash_token("valid-code")).exists()
    assert McpOAuthAccessToken.objects.filter(token_hash=hash_token("valid-access")).exists()
    assert McpOAuthRefreshToken.objects.filter(token_hash=hash_token("valid-refresh")).exists()


def test_oauth_provider_accepts_legacy_bearer_api_key(profile):
    provider = _provider()

    access_token = anyio.run(provider.load_access_token, profile.key)

    assert access_token.client_id == LEGACY_API_KEY_CLIENT_ID
    assert access_token.subject == str(profile.id)
    assert access_token.claims["legacy_api_key"] is True


def test_oauth_provider_accepts_named_agent_api_key(profile):
    provider = _provider()
    credential = create_agent_api_key(profile, "Codex")

    access_token = anyio.run(provider.load_access_token, credential.raw_key)

    assert access_token.client_id == AGENT_API_KEY_CLIENT_ID
    assert access_token.subject == str(profile.id)
    assert access_token.claims["legacy_api_key"] is False
    assert access_token.claims["agent_api_key_id"] == credential.agent_api_key.id
    assert access_token.claims["agent_api_key_name"] == "Codex"
    credential.agent_api_key.refresh_from_db()
    assert credential.agent_api_key.last_used_at is not None


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


def test_authenticate_profile_prefers_oauth_access_token_over_explicit_api_key(
    monkeypatch,
    profile,
):
    monkeypatch.setattr(
        "apps.mcp_server.server.get_access_token",
        lambda: AccessToken(
            token="token",
            client_id="client-1",
            scopes=[MCP_SCOPE],
            subject=str(profile.id),
        ),
    )
    monkeypatch.setattr(
        "apps.mcp_server.server.resolve_api_key_profile",
        lambda _key: (_ for _ in ()).throw(AssertionError("unexpected key lookup")),
    )

    assert _authenticate_profile(api_key="ignored-api-key") == profile


def test_authenticate_profile_accepts_explicit_named_agent_api_key(profile):
    credential = create_agent_api_key(profile, "OpenClaw")

    assert _authenticate_profile(api_key=credential.raw_key) == profile


def test_root_well_known_routes_include_mounted_mcp_metadata():
    paths = [route.path for route in mcp_auth.get_well_known_routes(mcp_path=MCP_INTERNAL_PATH)]

    assert "/.well-known/oauth-authorization-server/mcp" in paths
    assert "/.well-known/oauth-protected-resource/mcp/" in paths
