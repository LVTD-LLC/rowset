import json
from typing import Annotated, Any

from django.db import close_old_connections
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
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
    patch_profile_dataset_row_by_index,
    rename_profile_dataset_column,
    reorder_profile_dataset_columns,
    restore_profile_dataset,
    search_profile_datasets,
    search_profile_projects,
    serialize_dataset_summary,
    serialize_profile_datasets,
    serialize_profile_project_detail,
    serialize_profile_projects,
    serialize_user_info,
    update_profile_dataset_column_types,
    update_profile_dataset_metadata,
    update_profile_dataset_project,
    update_profile_dataset_public_preview,
)
from apps.core.models import AgentApiKey, Profile
from apps.core.services import resolve_api_key_profile
from apps.mcp_server.auth import mcp_auth
from filebridge.utils import get_filebridge_logger

logger = get_filebridge_logger(__name__)
AGENT_API_KEY_PROFILE_ATTR = "_rowset_agent_api_key"
DATASET_IDENTIFIER_DESCRIPTION = "Rowset dataset key, public key, or Rowset dataset/row URL."
ColumnTypeSpec = str | dict[str, Any]
RETRYABLE_ERROR_CODES = {
    "DATASET_NOT_READY",
    "RATE_LIMITED",
    "ROWSET_SERVICE_ERROR",
}

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


def _error_message_sentence(message: str) -> str:
    text = str(message or "Rowset request failed.").strip()
    if text.endswith((".", "?", "!")):
        return text
    return f"{text}."


def _mcp_error_payload(
    *,
    code: str,
    message: str,
    retryable: bool,
    suggested_action: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "message": _error_message_sentence(message),
        "retryable": retryable,
        "suggested_action": suggested_action,
        "details": details or {},
    }


def _mcp_tool_error(payload: dict[str, Any]) -> ToolError:
    return ToolError(json.dumps(payload, sort_keys=True))


def _message_error_code(
    message: str,
    matches: tuple[tuple[str, str], ...],
    fallback: str,
) -> str:
    for needle, code in matches:
        if needle in message:
            return code
    return fallback


def _dataset_service_error_code(exc: DatasetServiceError) -> str:
    status_code = exc.status_code
    message = exc.message.lower()
    if status_code == 404:
        return _message_error_code(
            message,
            (
                ("row not found", "ROW_NOT_FOUND"),
                ("dataset not found", "DATASET_NOT_FOUND"),
                ("project not found", "PROJECT_NOT_FOUND"),
                ("column not found", "COLUMN_NOT_FOUND"),
            ),
            "NOT_FOUND",
        )
    if status_code == 400:
        return "VALIDATION_ERROR"
    if status_code == 409:
        return _message_error_code(
            message,
            (
                ("archived", "DATASET_ARCHIVED"),
                ("not ready", "DATASET_NOT_READY"),
            ),
            "CONFLICT",
        )
    if status_code in {401, 403}:
        return "AUTHORIZATION_FAILED"
    if status_code == 429:
        return "RATE_LIMITED"
    if status_code >= 500:
        return "ROWSET_SERVICE_ERROR"
    return "ROWSET_ERROR"


def _dataset_service_error_suggested_action(code: str) -> str:
    suggestions = {
        "ROW_NOT_FOUND": "Check the row id or index value and try again.",
        "DATASET_NOT_FOUND": (
            "Check that dataset_key is a private key, public key, or Rowset URL "
            "for a dataset owned by this profile."
        ),
        "PROJECT_NOT_FOUND": "Check the project key and try again.",
        "COLUMN_NOT_FOUND": "Check the column name against the dataset headers and try again.",
        "VALIDATION_ERROR": "Check the tool arguments against the dataset schema and try again.",
        "DATASET_ARCHIVED": "Restore the dataset before making changes.",
        "DATASET_NOT_READY": "Confirm and wait for dataset import to finish before retrying.",
        "CONFLICT": "Refresh the dataset or row state, resolve the conflict, and try again.",
        "AUTHORIZATION_FAILED": "Check that the API key has access to this Rowset resource.",
        "RATE_LIMITED": "Back off before retrying the request.",
        "ROWSET_SERVICE_ERROR": "Retry the request. If it keeps failing, report the error.",
        "NOT_FOUND": "Check the identifier and try again.",
        "ROWSET_ERROR": "Check the request and try again.",
    }
    return suggestions.get(code, suggestions["ROWSET_ERROR"])


def _service_error_to_tool_error(exc: DatasetServiceError) -> ToolError:
    code = _dataset_service_error_code(exc)
    return _mcp_tool_error(
        _mcp_error_payload(
            code=code,
            message=exc.message,
            retryable=code in RETRYABLE_ERROR_CODES,
            suggested_action=_dataset_service_error_suggested_action(code),
            details={"http_status": exc.status_code},
        )
    )


def _permission_error_to_tool_error(exc: PermissionError) -> ToolError:
    raw_message = str(exc)
    normalized_message = raw_message.lower()
    if "missing" in normalized_message and "authorization" in normalized_message:
        code = "AUTHORIZATION_MISSING"
        suggested_action = "Configure the MCP request with Authorization: Bearer <ROWSET_API_KEY>."
    elif "no longer active" in normalized_message:
        code = "API_KEY_INACTIVE"
        suggested_action = "Create or select an active Rowset agent API key and retry."
    else:
        code = "AUTHENTICATION_FAILED"
        suggested_action = (
            "Check that the MCP request sends Authorization: Bearer <ROWSET_API_KEY> "
            "with an active Rowset API key."
        )

    return _mcp_tool_error(
        _mcp_error_payload(
            code=code,
            message=raw_message,
            retryable=False,
            suggested_action=suggested_action,
            details={"http_status": 401},
        )
    )


def _mcp_authenticated_profile() -> Profile:
    try:
        return _authenticate_profile()
    except PermissionError as exc:
        raise _permission_error_to_tool_error(exc) from exc


@mcp.tool(
    name="get_user_info",
    description="Return safe account and profile details for the authenticated Rowset user.",
)
def get_user_info() -> dict:
    """Return safe user/profile details for the authenticated Rowset user."""
    close_old_connections()
    profile = _mcp_authenticated_profile()
    try:
        return serialize_user_info(profile)
    except DatasetServiceError as exc:
        raise _service_error_to_tool_error(exc) from exc


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
    profile = _mcp_authenticated_profile()
    try:
        return serialize_profile_datasets(profile, limit=limit, offset=offset)
    except DatasetServiceError as exc:
        raise _service_error_to_tool_error(exc) from exc


@mcp.tool(
    name="search_datasets",
    description=(
        "Search and filter dataset metadata by name, project, header, status, or update time."
    ),
)
def search_datasets(
    query: Annotated[
        str | None,
        Field(
            default=None,
            description=(
                "Text to match against dataset name, original filename, project name, "
                "or project description."
            ),
        ),
    ] = None,
    project_key: Annotated[
        str | None,
        Field(default=None, description="Optional project key/UUID to restrict results."),
    ] = None,
    header_contains: Annotated[
        str | None,
        Field(default=None, description="Optional exact header name that results must contain."),
    ] = None,
    status: Annotated[
        str | None,
        Field(
            default=None,
            description=(
                "Optional dataset status filter. "
                "Accepted values: previewed, processing, ready, failed."
            ),
        ),
    ] = None,
    updated_after: Annotated[
        str | None,
        Field(
            default=None,
            description=(
                "Optional ISO date or datetime lower bound for updates. "
                "Values without a timezone offset, including bare dates, "
                "are interpreted as UTC."
            ),
        ),
    ] = None,
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
    profile = _mcp_authenticated_profile()
    try:
        return search_profile_datasets(
            profile,
            query=query,
            project_key=project_key,
            header_contains=header_contains,
            status=status,
            updated_after=updated_after,
            limit=limit,
            offset=offset,
        )
    except DatasetServiceError as exc:
        raise _service_error_to_tool_error(exc) from exc


@mcp.tool(
    name="get_dataset",
    description="Return metadata for one dataset owned by the authenticated Rowset profile.",
)
def get_dataset(
    dataset_key: Annotated[str, Field(description=DATASET_IDENTIFIER_DESCRIPTION)],
) -> dict:
    close_old_connections()
    profile = _mcp_authenticated_profile()
    try:
        return serialize_dataset_summary(get_profile_dataset(profile, dataset_key))
    except DatasetServiceError as exc:
        raise _service_error_to_tool_error(exc) from exc


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
    profile = _mcp_authenticated_profile()
    try:
        return serialize_profile_projects(profile, limit=limit, offset=offset)
    except DatasetServiceError as exc:
        raise _service_error_to_tool_error(exc) from exc


@mcp.tool(
    name="search_projects",
    description="Search project metadata by project name or description.",
)
def search_projects(
    query: Annotated[
        str | None,
        Field(default=None, description="Text to match against project names and descriptions."),
    ] = None,
    limit: Annotated[
        int,
        Field(default=100, ge=1, le=500, description="Maximum projects to return."),
    ] = 100,
    offset: Annotated[
        int,
        Field(default=0, ge=0, description="Number of projects to skip."),
    ] = 0,
) -> dict:
    close_old_connections()
    profile = _mcp_authenticated_profile()
    try:
        return search_profile_projects(profile, query=query, limit=limit, offset=offset)
    except DatasetServiceError as exc:
        raise _service_error_to_tool_error(exc) from exc


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
    profile = _mcp_authenticated_profile()
    try:
        return create_profile_project(profile, name=name, description=description)
    except DatasetServiceError as exc:
        raise _service_error_to_tool_error(exc) from exc


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
    profile = _mcp_authenticated_profile()
    try:
        return serialize_profile_project_detail(
            profile,
            project_key,
            limit=limit,
            offset=offset,
        )
    except DatasetServiceError as exc:
        raise _service_error_to_tool_error(exc) from exc


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
    description: Annotated[
        str | None,
        Field(
            default=None,
            description=(
                "Optional concise description of what the dataset represents and why it exists."
            ),
        ),
    ] = None,
    instructions: Annotated[
        str | None,
        Field(
            default=None,
            description=(
                "Optional persistent operating instructions for agents that use this dataset."
            ),
        ),
    ] = None,
    metadata: Annotated[
        dict[str, Any] | None,
        Field(
            default=None,
            description=(
                "Optional machine-readable JSON object for workflow rules, status values, "
                "owners, or other dataset-specific conventions."
            ),
        ),
    ] = None,
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
        dict[str, ColumnTypeSpec] | None,
        Field(
            default=None,
            description=(
                "Optional mapping from header name to semantic column type or metadata. "
                "Supported types include text, choice, integer, number, currency, boolean, "
                "date, datetime, email, and url. For choice columns, pass metadata like "
                '{"type": "choice", "choices": ["Ready to do", "Doing", "Done"]}.'
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
    profile = _mcp_authenticated_profile()
    try:
        return create_profile_dataset(
            profile,
            name=name,
            description=description,
            instructions=instructions,
            metadata=metadata,
            headers=headers,
            rows=rows,
            index_column=index_column,
            column_types=column_types,
            project_key=project_key,
            **_agent_actor_kwargs(profile),
        )
    except DatasetServiceError as exc:
        raise _service_error_to_tool_error(exc) from exc


@mcp.tool(
    name="update_dataset_metadata",
    description=(
        "Update persistent dataset context: description, agent instructions, and "
        "machine-readable JSON metadata."
    ),
)
def update_dataset_metadata(
    dataset_key: Annotated[str, Field(description=DATASET_IDENTIFIER_DESCRIPTION)],
    description: Annotated[
        str | None,
        Field(
            default=None,
            description=(
                "Optional new dataset description. Use an empty string to clear it; "
                "omit or pass null to keep the current value."
            ),
        ),
    ] = None,
    instructions: Annotated[
        str | None,
        Field(
            default=None,
            description=(
                "Optional new persistent agent instructions. Use an empty string to clear "
                "them; omit or pass null to keep the current value."
            ),
        ),
    ] = None,
    metadata: Annotated[
        dict[str, Any] | None,
        Field(
            default=None,
            description=(
                "Optional replacement JSON object for dataset-specific conventions. "
                "Pass an empty object to clear it; omit or pass null to keep the current value."
            ),
        ),
    ] = None,
) -> dict:
    close_old_connections()
    profile = _mcp_authenticated_profile()
    updates = {}
    if description is not None:
        updates["description"] = description
    if instructions is not None:
        updates["instructions"] = instructions
    if metadata is not None:
        updates["metadata"] = metadata
    try:
        return update_profile_dataset_metadata(
            profile,
            dataset_key,
            **updates,
            **_agent_actor_kwargs(profile),
        )
    except DatasetServiceError as exc:
        raise _service_error_to_tool_error(exc) from exc


@mcp.tool(
    name="update_dataset_column_types",
    description="Update semantic column type metadata for an existing Rowset dataset.",
)
def update_dataset_column_types(
    dataset_key: Annotated[str, Field(description=DATASET_IDENTIFIER_DESCRIPTION)],
    column_types: Annotated[
        dict[str, ColumnTypeSpec],
        Field(
            description=(
                "Mapping from dataset header to semantic type or metadata. Supported types "
                "include text, choice, integer, number, currency, boolean, date, datetime, "
                'email, and url. For choice columns, pass {"type": "choice", "choices": '
                '["Ready to do", "Doing", "Done"]}.'
            ),
        ),
    ],
) -> dict:
    close_old_connections()
    profile = _mcp_authenticated_profile()
    try:
        return update_profile_dataset_column_types(
            profile,
            dataset_key,
            column_types,
            **_agent_actor_kwargs(profile),
        )
    except DatasetServiceError as exc:
        raise _service_error_to_tool_error(exc) from exc


@mcp.tool(
    name="add_column",
    description=(
        "Add one column to an existing ready Rowset dataset and backfill existing rows "
        "with a blank or default value."
    ),
)
def add_column(
    dataset_key: Annotated[str, Field(description=DATASET_IDENTIFIER_DESCRIPTION)],
    name: Annotated[str, Field(description="New dataset column name.")],
    default_value: Annotated[
        str | None,
        Field(
            default="",
            description="Optional value assigned to existing rows. Defaults to blank.",
        ),
    ] = "",
    column_type: Annotated[
        ColumnTypeSpec | None,
        Field(
            default=None,
            description=(
                "Optional semantic type or metadata for the new column. Supported types "
                "include text, choice, integer, number, currency, boolean, date, datetime, "
                'email, and url. For a choice column, pass {"type": "choice", "choices": '
                '["Ready to do", "Doing", "Done"]}.'
            ),
        ),
    ] = None,
) -> dict:
    close_old_connections()
    profile = _mcp_authenticated_profile()
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
        raise _service_error_to_tool_error(exc) from exc


@mcp.tool(
    name="rename_column",
    description=(
        "Rename one column on an existing ready Rowset dataset while preserving row values."
    ),
)
def rename_column(
    dataset_key: Annotated[str, Field(description=DATASET_IDENTIFIER_DESCRIPTION)],
    old_name: Annotated[str, Field(description="Existing dataset column name.")],
    new_name: Annotated[str, Field(description="New dataset column name.")],
) -> dict:
    close_old_connections()
    profile = _mcp_authenticated_profile()
    try:
        return rename_profile_dataset_column(
            profile,
            dataset_key,
            old_name=old_name,
            new_name=new_name,
            **_agent_actor_kwargs(profile),
        )
    except DatasetServiceError as exc:
        raise _service_error_to_tool_error(exc) from exc


@mcp.tool(
    name="drop_column",
    description="Drop one non-index column from an existing ready Rowset dataset and its rows.",
)
def drop_column(
    dataset_key: Annotated[str, Field(description=DATASET_IDENTIFIER_DESCRIPTION)],
    name: Annotated[str, Field(description="Existing non-index dataset column name.")],
) -> dict:
    close_old_connections()
    profile = _mcp_authenticated_profile()
    try:
        return drop_profile_dataset_column(
            profile,
            dataset_key,
            name=name,
            **_agent_actor_kwargs(profile),
        )
    except DatasetServiceError as exc:
        raise _service_error_to_tool_error(exc) from exc


@mcp.tool(
    name="reorder_columns",
    description=(
        "Set the display and export order for existing dataset columns. Provide each "
        "current header exactly once."
    ),
)
def reorder_columns(
    dataset_key: Annotated[str, Field(description=DATASET_IDENTIFIER_DESCRIPTION)],
    headers: Annotated[
        list[str],
        Field(description="All existing dataset headers in the desired order."),
    ],
) -> dict:
    close_old_connections()
    profile = _mcp_authenticated_profile()
    try:
        return reorder_profile_dataset_columns(
            profile,
            dataset_key,
            headers=headers,
            **_agent_actor_kwargs(profile),
        )
    except DatasetServiceError as exc:
        raise _service_error_to_tool_error(exc) from exc


@mcp.tool(
    name="update_dataset_project",
    description=(
        "Attach an existing Rowset dataset to a project, or detach it from its project by "
        "passing null for project_key."
    ),
)
def update_dataset_project(
    dataset_key: Annotated[str, Field(description=DATASET_IDENTIFIER_DESCRIPTION)],
    project_key: Annotated[
        str | None,
        Field(
            default=None,
            description="Rowset project key/UUID. Pass null to leave the dataset ungrouped.",
        ),
    ] = None,
) -> dict:
    close_old_connections()
    profile = _mcp_authenticated_profile()
    try:
        return update_profile_dataset_project(
            profile,
            dataset_key,
            project_key,
            **_agent_actor_kwargs(profile),
        )
    except DatasetServiceError as exc:
        raise _service_error_to_tool_error(exc) from exc


@mcp.tool(
    name="update_dataset_public_preview",
    description=(
        "Enable, disable, password-protect, or resize a read-only public preview for "
        "an existing ready Rowset dataset. Returns the public preview URL."
    ),
)
def update_dataset_public_preview(
    dataset_key: Annotated[str, Field(description=DATASET_IDENTIFIER_DESCRIPTION)],
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
    profile = _mcp_authenticated_profile()
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
        raise _service_error_to_tool_error(exc) from exc


@mcp.tool(
    name="archive_dataset",
    description=(
        "Archive an existing Rowset dataset without deleting rows. Archived datasets are "
        "omitted from normal dataset and project lists and can be restored."
    ),
)
def archive_dataset(
    dataset_key: Annotated[str, Field(description=DATASET_IDENTIFIER_DESCRIPTION)],
) -> dict:
    close_old_connections()
    profile = _mcp_authenticated_profile()
    try:
        return archive_profile_dataset(
            profile,
            dataset_key,
            **_agent_actor_kwargs(profile),
        )
    except DatasetServiceError as exc:
        raise _service_error_to_tool_error(exc) from exc


@mcp.tool(
    name="restore_dataset",
    description="Restore an archived Rowset dataset to normal dataset and project lists.",
)
def restore_dataset(
    dataset_key: Annotated[str, Field(description=DATASET_IDENTIFIER_DESCRIPTION)],
) -> dict:
    close_old_connections()
    profile = _mcp_authenticated_profile()
    try:
        return restore_profile_dataset(
            profile,
            dataset_key,
            **_agent_actor_kwargs(profile),
        )
    except DatasetServiceError as exc:
        raise _service_error_to_tool_error(exc) from exc


@mcp.tool(
    name="list_dataset_rows",
    description=(
        "Return a bounded page of rows for a ready dataset. Optionally search across "
        "row values, filter by column values, and sort by row_number or a dataset header."
    ),
)
def list_dataset_rows(
    dataset_key: Annotated[str, Field(description=DATASET_IDENTIFIER_DESCRIPTION)],
    limit: Annotated[int, Field(default=100, ge=1, le=500)] = 100,
    offset: Annotated[int, Field(default=0, ge=0)] = 0,
    query: Annotated[
        str | None,
        Field(default=None, description="Optional text to search across row values."),
    ] = None,
    filters: Annotated[
        dict[str, str] | None,
        Field(
            default=None,
            description=(
                "Optional mapping from dataset header to a value to filter by. "
                "Text-like filters use case-insensitive contains matching; boolean "
                "filters accept true/false, yes/no, y/n, or 1/0."
            ),
        ),
    ] = None,
    sort: Annotated[
        str | None,
        Field(
            default=None,
            description="Optional sort key: row_number or one of the dataset headers.",
        ),
    ] = None,
    direction: Annotated[
        str | None,
        Field(default=None, description="Optional sort direction: asc or desc."),
    ] = None,
) -> dict:
    close_old_connections()
    profile = _mcp_authenticated_profile()
    try:
        return list_profile_dataset_rows(
            profile,
            dataset_key,
            limit=limit,
            offset=offset,
            query=query,
            filters=filters,
            sort=sort,
            direction=direction,
        )
    except DatasetServiceError as exc:
        raise _service_error_to_tool_error(exc) from exc


@mcp.tool(
    name="get_dataset_row",
    description="Return one row from a ready dataset by internal row id.",
)
def get_dataset_row(
    dataset_key: Annotated[str, Field(description=DATASET_IDENTIFIER_DESCRIPTION)],
    row_id: Annotated[int, Field(ge=1, description="Internal Rowset row id.")],
) -> dict:
    close_old_connections()
    profile = _mcp_authenticated_profile()
    try:
        return get_profile_dataset_row(profile, dataset_key, row_id)
    except DatasetServiceError as exc:
        raise _service_error_to_tool_error(exc) from exc


@mcp.tool(
    name="get_dataset_row_by_index",
    description="Return one row from a ready dataset by its configured index value.",
)
def get_dataset_row_by_index(
    dataset_key: Annotated[str, Field(description=DATASET_IDENTIFIER_DESCRIPTION)],
    index_value: Annotated[str, Field(description="Value from the dataset index column.")],
) -> dict:
    close_old_connections()
    profile = _mcp_authenticated_profile()
    try:
        return get_profile_dataset_row_by_index(profile, dataset_key, index_value)
    except DatasetServiceError as exc:
        raise _service_error_to_tool_error(exc) from exc


@mcp.tool(
    name="create_dataset_row",
    description="Create one row in a ready dataset. Provide values keyed by dataset header.",
)
def create_dataset_row(
    dataset_key: Annotated[str, Field(description=DATASET_IDENTIFIER_DESCRIPTION)],
    data: Annotated[dict[str, str], Field(description="Row values keyed by dataset header.")],
) -> dict:
    close_old_connections()
    profile = _mcp_authenticated_profile()
    try:
        return create_profile_dataset_row(
            profile,
            dataset_key,
            data,
            **_agent_actor_kwargs(profile),
        )
    except DatasetServiceError as exc:
        raise _service_error_to_tool_error(exc) from exc


@mcp.tool(
    name="update_dataset_row",
    description="Patch one row in a ready dataset. Unknown headers are ignored.",
)
def update_dataset_row(
    dataset_key: Annotated[str, Field(description=DATASET_IDENTIFIER_DESCRIPTION)],
    row_id: Annotated[int, Field(ge=1, description="Internal Rowset row id.")],
    data: Annotated[dict[str, str], Field(description="Header values to update on the row.")],
) -> dict:
    close_old_connections()
    profile = _mcp_authenticated_profile()
    try:
        return patch_profile_dataset_row(
            profile,
            dataset_key,
            row_id,
            data,
            **_agent_actor_kwargs(profile),
        )
    except DatasetServiceError as exc:
        raise _service_error_to_tool_error(exc) from exc


@mcp.tool(
    name="update_dataset_row_by_index",
    description="Patch one row in a ready dataset by its configured index value.",
)
def update_dataset_row_by_index(
    dataset_key: Annotated[str, Field(description=DATASET_IDENTIFIER_DESCRIPTION)],
    index_value: Annotated[str, Field(description="Value from the dataset index column.")],
    data: Annotated[dict[str, str], Field(description="Header values to update on the row.")],
) -> dict:
    close_old_connections()
    profile = _mcp_authenticated_profile()
    try:
        return patch_profile_dataset_row_by_index(
            profile,
            dataset_key,
            index_value,
            data,
            **_agent_actor_kwargs(profile),
        )
    except DatasetServiceError as exc:
        raise _service_error_to_tool_error(exc) from exc


@mcp.tool(
    name="delete_dataset_row",
    description="Delete one row from a ready dataset by internal row id.",
)
def delete_dataset_row(
    dataset_key: Annotated[str, Field(description=DATASET_IDENTIFIER_DESCRIPTION)],
    row_id: Annotated[int, Field(ge=1, description="Internal Rowset row id.")],
) -> dict:
    close_old_connections()
    profile = _mcp_authenticated_profile()
    try:
        return delete_profile_dataset_row(
            profile,
            dataset_key,
            row_id,
            **_agent_actor_kwargs(profile),
        )
    except DatasetServiceError as exc:
        raise _service_error_to_tool_error(exc) from exc
