from __future__ import annotations

from asgiref.sync import sync_to_async
from django.db import close_old_connections
from fastmcp.server.auth import AccessToken, AuthProvider

from apps.core.services import resolve_api_key_profile
from rowset.utils import build_absolute_public_url

MCP_MOUNT_PATH = "/mcp"
MCP_INTERNAL_PATH = "/"
MCP_SCOPE = "rowset:mcp"
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
        resolved_profile_id = profile.id
        claims = {
            "iss": build_mcp_base_url(),
            "sub": str(resolved_profile_id),
            "profile_id": resolved_profile_id,
            "email": profile.user.email,
            "agent_api_key_id": agent_api_key.id,
            "agent_api_key_name": agent_api_key.name,
            "agent_api_key_access_level": agent_api_key.access_level,
            "setup_completed": profile.setup_completed_at is not None,
        }

        return AccessToken(
            token=token,
            client_id=AGENT_API_KEY_CLIENT_ID,
            scopes=[MCP_SCOPE],
            expires_at=None,
            subject=str(resolved_profile_id),
            claims=claims,
        )


mcp_auth = RowsetApiKeyAuthProvider()
