from typing import Annotated, Any

from django.db import close_old_connections
from fastmcp import FastMCP
from fastmcp.server.dependencies import get_access_token, get_http_request
from pydantic import Field

from apps.api.services import (
    MAX_API_DATASET_CREATE_ROWS,
    DatasetServiceError,
    add_profile_dataset_column,
    archive_profile_dataset,
    create_profile_dataset,
    create_profile_dataset_row,
    create_profile_project,
    delete_profile_dataset_row,
    drop_profile_dataset_column,
    get_profile_dataset,
    get_profile_dataset_row,
    get_profile_dataset_row_by_index,
    list_profile_dataset_rows,
    patch_profile_dataset_row,
    rename_profile_dataset_column,
    reorder_profile_dataset_columns,
    restore_profile_dataset,
    serialize_dataset_summary,
    serialize_profile_datasets,
    serialize_profile_project_detail,
    serialize_profile_projects,
    serialize_user_info,
    update_profile_dataset_column_types,
    update_profile_dataset_project,
    update_profile_dataset_public_preview,
)
from apps.core.models import AgentApiKey, Profile
from apps.core.services import resolve_api_key_profile
from apps.mcp_server.auth import mcp_auth
from filebridge.utils import get_filebridge_logger

logger = get_filebridge_logger(__name__)
AGENT_API_KEY_PROFILE_ATTR = "_rowset_agent_api_key"

mcp = FastMCP(
    name="Rowset",
    instructions=(
        "Rowset lets AI agents create, inspect, update, and share API-addressable datasets. "
        "For hosted MCP requests, add the Rowset MCP server URL to your MCP client "
        "and configure the agent API key as an Authorization: Bearer token."
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


def _attach_agent_api_key(
    profile: Profile,
    agent_api_key: AgentApiKey | None,
) -> Profile:
    setattr(profile, AGENT_API_KEY_PROFILE_ATTR, agent_api_key)
    return profile


def _agent_actor_kwargs(profile: Profile) -> dict:
    agent_api_key = getattr(profile, AGENT_API_KEY_PROFILE_ATTR, None)
    if agent_api_key is None:
        return {}
    return {"agent_api_key": agent_api_key}


def _authenticate_profile(api_key: str | None = None) -> Profile:
    token_profile = _get_access_token_profile()
    if token_profile is not None:
        return token_profile

    key = (api_key or "").strip() or _get_request_api_key()
    if not key:
        raise PermissionError(
            "Missing Rowset authorization. Configure the Rowset MCP server request with "
            "Authorization: Bearer <ROWSET_API_KEY>."
        )

    resolved = resolve_api_key_profile(key)
    if resolved is None:
        logger.warning("[MCP] Invalid API key")
        raise PermissionError("Invalid Rowset API key.")
    profile, agent_api_key = resolved
    return _attach_agent_api_key(profile, agent_api_key)


def _get_access_token_profile() -> Profile | None:
    access_token = get_access_token()
    if access_token is None:
        return None

    claims = access_token.claims or {}
    profile_id = access_token.subject or claims.get("profile_id")
    if not profile_id:
        return None

    try:
        profile = Profile.objects.select_related("user").get(id=profile_id)
    except (Profile.DoesNotExist, ValueError) as exc:
        logger.warning("[MCP] API-key token profile could not be resolved", error=str(exc))
        return None

    agent_api_key = None
    agent_api_key_id = claims.get("agent_api_key_id")
    if agent_api_key_id:
        try:
            agent_api_key = AgentApiKey.objects.get(
                id=agent_api_key_id,
                profile=profile,
                revoked_at__isnull=True,
            )
        except (AgentApiKey.DoesNotExist, ValueError) as exc:
            logger.warning(
                "[MCP] OAuth token agent API key could not be resolved",
                error=str(exc),
                agent_api_key_id=agent_api_key_id,
                profile_id=profile.id,
            )
            raise PermissionError(
                "The Rowset agent API key for this token is no longer active."
            ) from exc

    return _attach_agent_api_key(profile, agent_api_key)


def _service_error_to_value_error(exc: DatasetServiceError) -> ValueError:
    return ValueError(f"{exc.status_code}: {exc.message}")


@mcp.tool(
    name="get_user_info",
    description="Return safe account and profile details for the authenticated Rowset user.",
)
def get_user_info() -> dict:
    """Return safe user/profile details for the authenticated Rowset user."""
    close_old_connections()
    profile = _authenticate_profile()
    return serialize_user_info(profile)


@mcp.tool(
    name="get_all_datasets",
    description=("Return metadata for all datasets available to the authenticated Rowset profile."),
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
    """Return a bounded page of datasets for the authenticated Rowset user."""
    close_old_connections()
    profile = _authenticate_profile()
    return serialize_profile_datasets(profile, limit=limit, offset=offset)


@mcp.tool(
    name="get_dataset",
    description="Return metadata for one dataset owned by the authenticated Rowset profile.",
)
def get_dataset(
    dataset_key: Annotated[str, Field(description="Rowset dataset key/UUID.")],
) -> dict:
    close_old_connections()
    profile = _authenticate_profile()
    try:
        return serialize_dataset_summary(get_profile_dataset(profile, dataset_key))
    except DatasetServiceError as exc:
        raise _service_error_to_value_error(exc) from exc


@mcp.tool(
    name="get_all_projects",
    description=("Return semantic dataset projects available to the authenticated Rowset profile."),
)
def get_all_projects(
    limit: Annotated[
        int,
        Field(default=100, ge=1, le=500, description="Maximum projects to return."),
    ] = 100,
    offset: Annotated[
        int,
        Field(default=0, ge=0, description="Number of projects to skip."),
    ] = 0,
) -> dict:
    """Return a bounded page of projects for the authenticated Rowset user."""
    close_old_connections()
    profile = _authenticate_profile()
    return serialize_profile_projects(profile, limit=limit, offset=offset)


@mcp.tool(
    name="create_project",
    description="Create a semantic project for grouping Rowset datasets.",
)
def create_project(
    name: Annotated[str, Field(description="Human-readable project name.")],
    description: Annotated[
        str | None,
        Field(default=None, description="Optional project description."),
    ] = None,
) -> dict:
    close_old_connections()
    profile = _authenticate_profile()
    try:
        return create_profile_project(profile, name=name, description=description)
    except DatasetServiceError as exc:
        raise _service_error_to_value_error(exc) from exc


@mcp.tool(
    name="get_project",
    description="Return one project and a bounded page of datasets assigned to it.",
)
def get_project(
    project_key: Annotated[str, Field(description="Rowset project key/UUID.")],
    limit: Annotated[
        int,
        Field(default=100, ge=1, le=500, description="Maximum datasets to return."),
    ] = 100,
    offset: Annotated[
        int,
        Field(default=0, ge=0, description="Number of datasets to skip."),
    ] = 0,
) -> dict:
    close_old_connections()
    profile = _authenticate_profile()
    try:
        return serialize_profile_project_detail(
            profile,
            project_key,
            limit=limit,
            offset=offset,
        )
    except DatasetServiceError as exc:
        raise _service_error_to_value_error(exc) from exc


@mcp.tool(
    name="create_dataset",
    description=(
        "Create a ready API-backed dataset for the authenticated Rowset profile. "
        "Provide headers, rows, or both. If index_column is omitted, Rowset generates "
        "a rowset_id index column so the dataset can be used immediately."
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
    column_types: Annotated[
        dict[str, str] | None,
        Field(
            default=None,
            description=(
                "Optional mapping from header name to semantic column type. "
                "Supported values include text, integer, number, currency, boolean, "
                "date, datetime, email, and url."
            ),
        ),
    ] = None,
    index_column: Annotated[
        str | None,
        Field(
            default=None,
            description=(
                "Optional unique, non-blank header to use as the row index. "
                "Omit to generate a rowset_id index."
            ),
        ),
    ] = None,
    project_key: Annotated[
        str | None,
        Field(
            default=None,
            description=(
                "Optional Rowset project key. When supplied, the new dataset is assigned "
                "to that project. Omit for an ungrouped dataset."
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
            column_types=column_types,
            project_key=project_key,
            **_agent_actor_kwargs(profile),
        )
    except DatasetServiceError as exc:
        raise _service_error_to_value_error(exc) from exc


@mcp.tool(
    name="update_dataset_column_types",
    description="Update semantic column type metadata for an existing Rowset dataset.",
)
def update_dataset_column_types(
    dataset_key: Annotated[str, Field(description="Rowset dataset key/UUID.")],
    column_types: Annotated[
        dict[str, str],
        Field(
            description=(
                "Mapping from dataset header to semantic type. Supported values include "
                "text, integer, number, currency, boolean, date, datetime, email, and url."
            ),
        ),
    ],
) -> dict:
    close_old_connections()
    profile = _authenticate_profile()
    try:
        return update_profile_dataset_column_types(
            profile,
            dataset_key,
            column_types,
            **_agent_actor_kwargs(profile),
        )
    except DatasetServiceError as exc:
        raise _service_error_to_value_error(exc) from exc


@mcp.tool(
    name="add_column",
    description=(
        "Add one column to an existing ready Rowset dataset and backfill existing rows "
        "with a blank or default value."
    ),
)
def add_column(
    dataset_key: Annotated[str, Field(description="Rowset dataset key/UUID.")],
    name: Annotated[str, Field(description="New dataset column name.")],
    default_value: Annotated[
        str | None,
        Field(
            default="",
            description="Optional value assigned to existing rows. Defaults to blank.",
        ),
    ] = "",
    column_type: Annotated[
        str | None,
        Field(
            default=None,
            description=(
                "Optional semantic type for the new column. Supported values include text, "
                "integer, number, currency, boolean, date, datetime, email, and url."
            ),
        ),
    ] = None,
) -> dict:
    close_old_connections()
    profile = _authenticate_profile()
    try:
        return add_profile_dataset_column(
            profile,
            dataset_key,
            name=name,
            default_value=default_value,
            column_type=column_type,
            **_agent_actor_kwargs(profile),
        )
    except DatasetServiceError as exc:
        raise _service_error_to_value_error(exc) from exc


@mcp.tool(
    name="rename_column",
    description=(
        "Rename one column on an existing ready Rowset dataset while preserving row values."
    ),
)
def rename_column(
    dataset_key: Annotated[str, Field(description="Rowset dataset key/UUID.")],
    old_name: Annotated[str, Field(description="Existing dataset column name.")],
    new_name: Annotated[str, Field(description="New dataset column name.")],
) -> dict:
    close_old_connections()
    profile = _authenticate_profile()
    try:
        return rename_profile_dataset_column(
            profile,
            dataset_key,
            old_name=old_name,
            new_name=new_name,
            **_agent_actor_kwargs(profile),
        )
    except DatasetServiceError as exc:
        raise _service_error_to_value_error(exc) from exc


@mcp.tool(
    name="drop_column",
    description="Drop one non-index column from an existing ready Rowset dataset and its rows.",
)
def drop_column(
    dataset_key: Annotated[str, Field(description="Rowset dataset key/UUID.")],
    name: Annotated[str, Field(description="Existing non-index dataset column name.")],
) -> dict:
    close_old_connections()
    profile = _authenticate_profile()
    try:
        return drop_profile_dataset_column(
            profile,
            dataset_key,
            name=name,
            **_agent_actor_kwargs(profile),
        )
    except DatasetServiceError as exc:
        raise _service_error_to_value_error(exc) from exc


@mcp.tool(
    name="reorder_columns",
    description=(
        "Set the display and export order for existing dataset columns. Provide each "
        "current header exactly once."
    ),
)
def reorder_columns(
    dataset_key: Annotated[str, Field(description="Rowset dataset key/UUID.")],
    headers: Annotated[
        list[str],
        Field(description="All existing dataset headers in the desired order."),
    ],
) -> dict:
    close_old_connections()
    profile = _authenticate_profile()
    try:
        return reorder_profile_dataset_columns(
            profile,
            dataset_key,
            headers=headers,
            **_agent_actor_kwargs(profile),
        )
    except DatasetServiceError as exc:
        raise _service_error_to_value_error(exc) from exc


@mcp.tool(
    name="update_dataset_project",
    description=(
        "Attach an existing Rowset dataset to a project, or detach it from its project by "
        "passing null for project_key."
    ),
)
def update_dataset_project(
    dataset_key: Annotated[str, Field(description="Rowset dataset key/UUID.")],
    project_key: Annotated[
        str | None,
        Field(
            default=None,
            description="Rowset project key/UUID. Pass null to leave the dataset ungrouped.",
        ),
    ] = None,
) -> dict:
    close_old_connections()
    profile = _authenticate_profile()
    try:
        return update_profile_dataset_project(
            profile,
            dataset_key,
            project_key,
            **_agent_actor_kwargs(profile),
        )
    except DatasetServiceError as exc:
        raise _service_error_to_value_error(exc) from exc


@mcp.tool(
    name="update_dataset_public_preview",
    description=(
        "Enable, disable, password-protect, or resize a read-only public preview for "
        "an existing ready Rowset dataset. Returns the public preview URL."
    ),
)
def update_dataset_public_preview(
    dataset_key: Annotated[str, Field(description="Rowset dataset key/UUID.")],
    public_enabled: Annotated[
        bool | None,
        Field(
            default=None,
            description=(
                "Set true or false to enable or disable the public preview. Omit to keep "
                "the current enabled state while updating page size or password settings."
            ),
        ),
    ] = None,
    public_page_size: Annotated[
        int | None,
        Field(
            default=None,
            ge=1,
            le=100,
            description="Optional number of rows to show per public preview page.",
        ),
    ] = None,
    public_password: Annotated[
        str | None,
        Field(
            default=None,
            description="Optional password to require before viewing the public preview.",
        ),
    ] = None,
    clear_public_password: Annotated[
        bool,
        Field(default=False, description="Set true to remove the existing preview password."),
    ] = False,
) -> dict:
    close_old_connections()
    profile = _authenticate_profile()
    try:
        return update_profile_dataset_public_preview(
            profile,
            dataset_key,
            public_enabled=public_enabled,
            public_page_size=public_page_size,
            public_password=public_password,
            clear_public_password=clear_public_password,
            **_agent_actor_kwargs(profile),
        )
    except DatasetServiceError as exc:
        raise _service_error_to_value_error(exc) from exc


@mcp.tool(
    name="archive_dataset",
    description=(
        "Archive an existing Rowset dataset without deleting rows. Archived datasets are "
        "omitted from normal dataset and project lists and can be restored."
    ),
)
def archive_dataset(
    dataset_key: Annotated[str, Field(description="Rowset dataset key/UUID.")],
) -> dict:
    close_old_connections()
    profile = _authenticate_profile()
    try:
        return archive_profile_dataset(
            profile,
            dataset_key,
            **_agent_actor_kwargs(profile),
        )
    except DatasetServiceError as exc:
        raise _service_error_to_value_error(exc) from exc


@mcp.tool(
    name="restore_dataset",
    description="Restore an archived Rowset dataset to normal dataset and project lists.",
)
def restore_dataset(
    dataset_key: Annotated[str, Field(description="Rowset dataset key/UUID.")],
) -> dict:
    close_old_connections()
    profile = _authenticate_profile()
    try:
        return restore_profile_dataset(
            profile,
            dataset_key,
            **_agent_actor_kwargs(profile),
        )
    except DatasetServiceError as exc:
        raise _service_error_to_value_error(exc) from exc


@mcp.tool(
    name="list_dataset_rows",
    description="Return a bounded page of rows for a ready dataset.",
)
def list_dataset_rows(
    dataset_key: Annotated[str, Field(description="Rowset dataset key/UUID.")],
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
    dataset_key: Annotated[str, Field(description="Rowset dataset key/UUID.")],
    row_id: Annotated[int, Field(ge=1, description="Internal Rowset row id.")],
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
    dataset_key: Annotated[str, Field(description="Rowset dataset key/UUID.")],
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
    dataset_key: Annotated[str, Field(description="Rowset dataset key/UUID.")],
    data: Annotated[dict[str, str], Field(description="Row values keyed by dataset header.")],
) -> dict:
    close_old_connections()
    profile = _authenticate_profile()
    try:
        return create_profile_dataset_row(
            profile,
            dataset_key,
            data,
            **_agent_actor_kwargs(profile),
        )
    except DatasetServiceError as exc:
        raise _service_error_to_value_error(exc) from exc


@mcp.tool(
    name="update_dataset_row",
    description="Patch one row in a ready dataset. Unknown headers are ignored.",
)
def update_dataset_row(
    dataset_key: Annotated[str, Field(description="Rowset dataset key/UUID.")],
    row_id: Annotated[int, Field(ge=1, description="Internal Rowset row id.")],
    data: Annotated[dict[str, str], Field(description="Header values to update on the row.")],
) -> dict:
    close_old_connections()
    profile = _authenticate_profile()
    try:
        return patch_profile_dataset_row(
            profile,
            dataset_key,
            row_id,
            data,
            **_agent_actor_kwargs(profile),
        )
    except DatasetServiceError as exc:
        raise _service_error_to_value_error(exc) from exc


@mcp.tool(
    name="delete_dataset_row",
    description="Delete one row from a ready dataset by internal row id.",
)
def delete_dataset_row(
    dataset_key: Annotated[str, Field(description="Rowset dataset key/UUID.")],
    row_id: Annotated[int, Field(ge=1, description="Internal Rowset row id.")],
) -> dict:
    close_old_connections()
    profile = _authenticate_profile()
    try:
        return delete_profile_dataset_row(
            profile,
            dataset_key,
            row_id,
            **_agent_actor_kwargs(profile),
        )
    except DatasetServiceError as exc:
        raise _service_error_to_value_error(exc) from exc
