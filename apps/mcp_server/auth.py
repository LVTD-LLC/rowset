from __future__ import annotations

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
            "sub": str(profile.id),
            "profile_id": profile.id,
            "email": profile.user.email,
            "legacy_api_key": agent_api_key is None,
        }
        if agent_api_key is not None:
            claims["agent_api_key_id"] = agent_api_key.id
            claims["agent_api_key_name"] = agent_api_key.name

        return AccessToken(
            token=token,
            client_id=client_id,
            scopes=[MCP_SCOPE],
            expires_at=None,
            subject=str(profile.id),
            claims=claims,
        )


mcp_auth = RowsetApiKeyAuthProvider()
