from __future__ import annotations

from typing import Any

from asgiref.sync import sync_to_async
from django.db import close_old_connections
from fastmcp.server.auth import AccessToken, AuthProvider

from apps.core.services import resolve_api_key_profile
from rowset.utils import build_absolute_public_url

MCP_MOUNT_PATH = "/mcp"
MCP_INTERNAL_PATH = "/"
MCP_SCOPE = "rowset:mcp"
LEGACY_API_KEY_CLIENT_ID = "rowset-api-key"
AGENT_API_KEY_CLIENT_ID = "rowset-agent-api-key"


def build_mcp_base_url() -> str:
    return build_absolute_public_url(MCP_MOUNT_PATH).rstrip("/")


def _profile_id(profile: Any) -> int:
    return profile.id


def _profile_user_email(profile: Any) -> str:
    return profile.user.email


def _agent_api_key_id(agent_api_key: Any) -> int:
    return agent_api_key.id


class RowsetApiKeyAuthProvider(AuthProvider):
    def __init__(self):
        super().__init__(required_scopes=[MCP_SCOPE])

    async def verify_token(self, token: str) -> AccessToken | None:
        return await sync_to_async(
            self._verify_token_with_fresh_db_connection,
            thread_sensitive=True,
        )(token)

    def _verify_token_with_fresh_db_connection(self, token: str) -> AccessToken | None:
        close_old_connections()
        try:
            return self._verify_token_sync(token)
        finally:
            close_old_connections()

    def _verify_token_sync(self, token: str) -> AccessToken | None:
        resolved = resolve_api_key_profile(token)
        if resolved is None:
            return None

        profile, agent_api_key = resolved
        client_id = (
            AGENT_API_KEY_CLIENT_ID if agent_api_key is not None else LEGACY_API_KEY_CLIENT_ID
        )
        claims = {
            "iss": build_mcp_base_url(),
            "sub": str(_profile_id(profile)),
            "profile_id": _profile_id(profile),
            "email": _profile_user_email(profile),
            "legacy_api_key": agent_api_key is None,
        }
        if agent_api_key is not None:
            claims["agent_api_key_id"] = _agent_api_key_id(agent_api_key)
            claims["agent_api_key_name"] = agent_api_key.name
            claims["agent_api_key_access_level"] = agent_api_key.access_level

        return AccessToken(
            token=token,
            client_id=client_id,
            scopes=[MCP_SCOPE],
            expires_at=None,
            subject=str(_profile_id(profile)),
            claims=claims,
        )


mcp_auth = RowsetApiKeyAuthProvider()
