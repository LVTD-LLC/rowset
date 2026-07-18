from typing import Any

from fastmcp import FastMCP
from fastmcp.server.auth import AuthContext
from mcp.types import ToolAnnotations

from apps.core.choices import AgentApiKeyAccessLevel
from apps.core.services import agent_api_key_access_level_allows

READ_ONLY_TOOL_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)
WRITE_TOOL_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=False,
)
IDEMPOTENT_WRITE_TOOL_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)
DESTRUCTIVE_TOOL_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=False,
    openWorldHint=False,
)
IDEMPOTENT_DESTRUCTIVE_TOOL_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=True,
    openWorldHint=False,
)


class RowsetToolPolicy:
    def __init__(self, mcp: FastMCP):
        self.mcp = mcp
        self._required_access_levels: dict[str, str] = {}

    @staticmethod
    def _access_check(required_access_level: str):
        def allows_access(context: AuthContext) -> bool:
            # FastMCP's in-memory transport has no HTTP bearer token. Tool bodies still enforce
            # access for that test/embedded path; hosted HTTP requests always reach this check
            # with the verified token produced by RowsetApiKeyAuthProvider.
            if context.token is None:
                return True
            return agent_api_key_access_level_allows(
                context.token.claims.get("agent_api_key_access_level"),
                required_access_level,
            )

        return allows_access

    def _tool(self, *, required_access_level: str, annotations: ToolAnnotations, **kwargs: Any):
        self._required_access_levels[kwargs["name"]] = required_access_level
        return self.mcp.tool(
            **kwargs,
            annotations=annotations,
            auth=self._access_check(required_access_level),
        )

    def allowed_tool_names(self, access_level: str | None) -> set[str]:
        return {
            name
            for name, required_access_level in self._required_access_levels.items()
            if agent_api_key_access_level_allows(access_level, required_access_level)
        }

    def read(self, **kwargs: Any):
        return self._tool(
            required_access_level=AgentApiKeyAccessLevel.READ,
            annotations=READ_ONLY_TOOL_ANNOTATIONS,
            **kwargs,
        )

    def write(self, **kwargs: Any):
        return self._tool(
            required_access_level=AgentApiKeyAccessLevel.READ_WRITE,
            annotations=WRITE_TOOL_ANNOTATIONS,
            **kwargs,
        )

    def idempotent_write(self, **kwargs: Any):
        return self._tool(
            required_access_level=AgentApiKeyAccessLevel.READ_WRITE,
            annotations=IDEMPOTENT_WRITE_TOOL_ANNOTATIONS,
            **kwargs,
        )

    def destructive(self, **kwargs: Any):
        return self._tool(
            required_access_level=AgentApiKeyAccessLevel.READ_WRITE,
            annotations=DESTRUCTIVE_TOOL_ANNOTATIONS,
            **kwargs,
        )

    def idempotent_destructive(self, **kwargs: Any):
        return self._tool(
            required_access_level=AgentApiKeyAccessLevel.READ_WRITE,
            annotations=IDEMPOTENT_DESTRUCTIVE_TOOL_ANNOTATIONS,
            **kwargs,
        )

    def admin(self, **kwargs: Any):
        return self._tool(
            required_access_level=AgentApiKeyAccessLevel.ADMIN,
            annotations=WRITE_TOOL_ANNOTATIONS,
            **kwargs,
        )
