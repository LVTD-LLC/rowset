from typing import Annotated

from django.db import close_old_connections
from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_request
from pydantic import Field

from apps.api.services import serialize_user_info
from apps.core.models import Profile
from filebridge.utils import get_filebridge_logger

logger = get_filebridge_logger(__name__)

mcp = FastMCP(
    name="FileBridge",
    instructions=(
        "FileBridge turns uploaded files into API-addressable datasets. "
        "Authenticate hosted MCP requests with an API key using one of: "
        "Authorization: Bearer <api_key>, X-API-Key: <api_key>, "
        "the api_key query parameter on the MCP URL, or the api_key tool argument."
    ),
)


def _get_request_api_key() -> str:
    try:
        request = get_http_request()
    except RuntimeError:
        return ""

    authorization = request.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() == "bearer" and token.strip():
        return token.strip()

    header_key = request.headers.get("x-api-key", "").strip()
    if header_key:
        return header_key

    return request.query_params.get("api_key", "").strip()


def _authenticate_profile(api_key: str | None = None) -> Profile:
    key = (api_key or "").strip() or _get_request_api_key()
    if not key:
        raise PermissionError(
            "Missing FileBridge API key. Provide Authorization: Bearer <api_key>, "
            "X-API-Key, ?api_key=, or the api_key tool argument."
        )

    try:
        return Profile.objects.select_related("user").get(key=key)
    except Profile.DoesNotExist as exc:
        logger.warning("[MCP] Invalid API key")
        raise PermissionError("Invalid FileBridge API key.") from exc


@mcp.tool(
    name="get_user_info",
    description="Return safe account and profile details for the authenticated FileBridge user.",
)
def get_user_info(
    api_key: Annotated[
        str | None,
        Field(
            default=None,
            description=(
                "Optional FileBridge API key. Hosted clients may instead send it as "
                "Authorization: Bearer <api_key>, X-API-Key, or ?api_key= on the MCP URL."
            ),
        ),
    ] = None,
) -> dict:
    """Return safe user/profile details for the authenticated FileBridge API key."""
    close_old_connections()
    profile = _authenticate_profile(api_key)
    return serialize_user_info(profile)
