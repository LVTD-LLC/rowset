from typing import Annotated, Any

from django.db import close_old_connections
from fastmcp import FastMCP
from fastmcp.server.dependencies import get_access_token, get_http_request
from pydantic import Field

from apps.api.services import (
    MAX_API_DATASET_CREATE_ROWS,
    DatasetServiceError,
    create_profile_dataset,
    create_profile_dataset_row,
    delete_profile_dataset_row,
    get_profile_dataset,
    get_profile_dataset_row,
    get_profile_dataset_row_by_index,
    list_profile_dataset_rows,
    patch_profile_dataset_row,
    serialize_dataset_summary,
    serialize_profile_datasets,
    serialize_user_info,
)
from apps.core.models import Profile
from apps.mcp_server.oauth import LEGACY_API_KEY_CLIENT_ID, mcp_auth
from filebridge.utils import get_filebridge_logger

logger = get_filebridge_logger(__name__)

mcp = FastMCP(
    name="FileBridge",
    instructions=(
        "FileBridge turns uploaded files into API-addressable datasets. "
        "For hosted MCP requests, add the FileBridge MCP server URL to your MCP client "
        "and complete the browser-based OAuth authorization flow when prompted."
    ),
    auth=mcp_auth,
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
    token_profile = _get_access_token_profile()
    if token_profile is not None and not api_key:
        return token_profile

    key = (api_key or "").strip() or _get_request_api_key()
    if not key:
        raise PermissionError(
            "Missing FileBridge authorization. Add the FileBridge MCP server URL to your "
            "MCP client and complete the browser-based authorization flow."
        )

    try:
        return Profile.objects.select_related("user").get(key=key)
    except Profile.DoesNotExist as exc:
        logger.warning("[MCP] Invalid API key")
        raise PermissionError("Invalid FileBridge API key.") from exc


def _get_access_token_profile() -> Profile | None:
    access_token = get_access_token()
    if access_token is None:
        return None

    profile_id = access_token.subject or access_token.claims.get("profile_id")
    if not profile_id:
        return None

    try:
        return Profile.objects.select_related("user").get(id=profile_id)
    except Profile.DoesNotExist, ValueError:
        if access_token.client_id != LEGACY_API_KEY_CLIENT_ID:
            logger.warning("[MCP] OAuth token profile no longer exists")
        return None


def _service_error_to_value_error(exc: DatasetServiceError) -> ValueError:
    return ValueError(f"{exc.status_code}: {exc.message}")


@mcp.tool(
    name="get_user_info",
    description="Return safe account and profile details for the authenticated FileBridge user.",
)
def get_user_info() -> dict:
    """Return safe user/profile details for the authenticated FileBridge user."""
    close_old_connections()
    profile = _authenticate_profile()
    return serialize_user_info(profile)


@mcp.tool(
    name="get_all_datasets",
    description=(
        "Return metadata for all datasets available to the authenticated FileBridge profile."
    ),
)
def get_all_datasets(
    limit: Annotated[
        int,
        Field(default=100, ge=1, le=500, description="Maximum datasets to return."),
    ] = 100,
    offset: Annotated[
        int,
        Field(default=0, ge=0, description="Number of datasets to skip."),
    ] = 0,
) -> dict:
    """Return a bounded page of datasets for the authenticated FileBridge user."""
    close_old_connections()
    profile = _authenticate_profile()
    return serialize_profile_datasets(profile, limit=limit, offset=offset)


@mcp.tool(
    name="get_dataset",
    description="Return metadata for one dataset owned by the authenticated FileBridge profile.",
)
def get_dataset(
    dataset_key: Annotated[str, Field(description="FileBridge dataset key/UUID.")],
) -> dict:
    close_old_connections()
    profile = _authenticate_profile()
    try:
        return serialize_dataset_summary(get_profile_dataset(profile, dataset_key))
    except DatasetServiceError as exc:
        raise _service_error_to_value_error(exc) from exc


@mcp.tool(
    name="create_dataset",
    description=(
        "Create a ready API-backed dataset for the authenticated FileBridge profile. "
        "Provide headers, rows, or both. If index_column is omitted, FileBridge generates "
        "a filebridge_id index column so the dataset can be used immediately."
    ),
)
def create_dataset(
    name: Annotated[str, Field(description="Human-readable dataset name.")],
    headers: Annotated[
        list[str] | None,
        Field(
            default=None,
            description=(
                "Optional ordered dataset headers. If omitted, headers are derived from rows."
            ),
        ),
    ] = None,
    rows: Annotated[
        list[dict[str, Any]] | None,
        Field(
            default=None,
            max_length=MAX_API_DATASET_CREATE_ROWS,
            description=(
                f"Optional initial rows keyed by dataset header. "
                f"Maximum {MAX_API_DATASET_CREATE_ROWS} rows."
            ),
        ),
    ] = None,
    index_column: Annotated[
        str | None,
        Field(
            default=None,
            description=(
                "Optional unique, non-blank header to use as the row index. "
                "Omit to generate a filebridge_id index."
            ),
        ),
    ] = None,
) -> dict:
    close_old_connections()
    profile = _authenticate_profile()
    try:
        return create_profile_dataset(
            profile,
            name=name,
            headers=headers,
            rows=rows,
            index_column=index_column,
        )
    except DatasetServiceError as exc:
        raise _service_error_to_value_error(exc) from exc


@mcp.tool(
    name="list_dataset_rows",
    description="Return a bounded page of rows for a ready dataset.",
)
def list_dataset_rows(
    dataset_key: Annotated[str, Field(description="FileBridge dataset key/UUID.")],
    limit: Annotated[int, Field(default=100, ge=1, le=500)] = 100,
    offset: Annotated[int, Field(default=0, ge=0)] = 0,
) -> dict:
    close_old_connections()
    profile = _authenticate_profile()
    try:
        return list_profile_dataset_rows(profile, dataset_key, limit=limit, offset=offset)
    except DatasetServiceError as exc:
        raise _service_error_to_value_error(exc) from exc


@mcp.tool(
    name="get_dataset_row",
    description="Return one row from a ready dataset by internal row id.",
)
def get_dataset_row(
    dataset_key: Annotated[str, Field(description="FileBridge dataset key/UUID.")],
    row_id: Annotated[int, Field(ge=1, description="Internal FileBridge row id.")],
) -> dict:
    close_old_connections()
    profile = _authenticate_profile()
    try:
        return get_profile_dataset_row(profile, dataset_key, row_id)
    except DatasetServiceError as exc:
        raise _service_error_to_value_error(exc) from exc


@mcp.tool(
    name="get_dataset_row_by_index",
    description="Return one row from a ready dataset by its configured index value.",
)
def get_dataset_row_by_index(
    dataset_key: Annotated[str, Field(description="FileBridge dataset key/UUID.")],
    index_value: Annotated[str, Field(description="Value from the dataset index column.")],
) -> dict:
    close_old_connections()
    profile = _authenticate_profile()
    try:
        return get_profile_dataset_row_by_index(profile, dataset_key, index_value)
    except DatasetServiceError as exc:
        raise _service_error_to_value_error(exc) from exc


@mcp.tool(
    name="create_dataset_row",
    description="Create one row in a ready dataset. Provide values keyed by dataset header.",
)
def create_dataset_row(
    dataset_key: Annotated[str, Field(description="FileBridge dataset key/UUID.")],
    data: Annotated[dict[str, str], Field(description="Row values keyed by dataset header.")],
) -> dict:
    close_old_connections()
    profile = _authenticate_profile()
    try:
        return create_profile_dataset_row(profile, dataset_key, data)
    except DatasetServiceError as exc:
        raise _service_error_to_value_error(exc) from exc


@mcp.tool(
    name="update_dataset_row",
    description="Patch one row in a ready dataset. Unknown headers are ignored.",
)
def update_dataset_row(
    dataset_key: Annotated[str, Field(description="FileBridge dataset key/UUID.")],
    row_id: Annotated[int, Field(ge=1, description="Internal FileBridge row id.")],
    data: Annotated[dict[str, str], Field(description="Header values to update on the row.")],
) -> dict:
    close_old_connections()
    profile = _authenticate_profile()
    try:
        return patch_profile_dataset_row(profile, dataset_key, row_id, data)
    except DatasetServiceError as exc:
        raise _service_error_to_value_error(exc) from exc


@mcp.tool(
    name="delete_dataset_row",
    description="Delete one row from a ready dataset by internal row id.",
)
def delete_dataset_row(
    dataset_key: Annotated[str, Field(description="FileBridge dataset key/UUID.")],
    row_id: Annotated[int, Field(ge=1, description="Internal FileBridge row id.")],
) -> dict:
    close_old_connections()
    profile = _authenticate_profile()
    try:
        return delete_profile_dataset_row(profile, dataset_key, row_id)
    except DatasetServiceError as exc:
        raise _service_error_to_value_error(exc) from exc
