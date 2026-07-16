import json
from typing import Annotated, Any

from django.db import IntegrityError, close_old_connections
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_access_token
from pydantic import Field

from apps.api.services import (
    MAX_API_DATASET_CREATE_ROWS,
    DatasetServiceError,
    add_profile_dataset_column,
    archive_profile_dataset,
    archive_profile_project,
    archive_profile_project_section,
    attach_profile_dataset_audio_asset,
    attach_profile_dataset_image_asset,
    create_profile_dataset,
    create_profile_dataset_relationship,
    create_profile_dataset_row,
    create_profile_project,
    create_profile_project_section,
    delete_profile_dataset_relationship,
    delete_profile_dataset_row,
    drop_profile_dataset_column,
    get_profile_dataset,
    get_profile_dataset_row,
    get_profile_dataset_row_by_index,
    list_profile_dataset_relationships,
    list_profile_dataset_rows,
    patch_profile_dataset_row,
    patch_profile_dataset_row_by_index,
    rename_profile_dataset_column,
    reorder_profile_dataset_columns,
    resolve_profile_dataset_relationship,
    restore_profile_dataset,
    search_profile_dataset_rows,
    search_profile_datasets,
    search_profile_projects,
    search_profile_rows,
    serialize_dataset_detail,
    serialize_profile_archived_datasets,
    serialize_profile_dataset_asset,
    serialize_profile_datasets,
    serialize_profile_project_detail,
    serialize_profile_project_sections,
    serialize_profile_projects,
    serialize_user_info,
    update_profile_dataset_column_types,
    update_profile_dataset_metadata,
    update_profile_dataset_project,
    update_profile_dataset_public_preview,
    update_profile_project,
    update_profile_project_metadata,
    update_profile_project_section,
)
from apps.core.analytics import (
    ROWSET_GET_USER_INFO_SUCCEEDED,
    agent_api_key_tracking_properties,
    track_activation_event,
)
from apps.core.capabilities import rowset_capabilities_payload
from apps.core.choices import AgentApiKeyAccessLevel, FeedbackSource
from apps.core.models import AgentApiKey, Profile
from apps.core.services import (
    create_agent_api_key as create_agent_api_key_credential,
)
from apps.core.services import (
    require_agent_api_key_access,
    serialize_agent_api_key,
    serialize_feedback_submission_result,
    submit_profile_feedback,
)
from apps.core.trials import (
    TrialExpiredError,
    activate_or_require_trial_access,
    require_unexpired_trial_access,
)
from apps.datasets.types import ColumnTypeSpec, DatasetRowInput, JsonObject
from apps.mcp_server.auth import mcp_auth
from rowset.mcp_logging import RowsetMCPLoggingMiddleware
from rowset.utils import get_rowset_logger

logger = get_rowset_logger(__name__)
AGENT_API_KEY_PROFILE_ATTR = "_rowset_agent_api_key"
DATASET_IDENTIFIER_DESCRIPTION = "Rowset dataset key, public key, or Rowset dataset/row URL."
RETRYABLE_ERROR_CODES = {
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
mcp.add_middleware(RowsetMCPLoggingMiddleware())


def _attach_agent_api_key(
    profile: Profile,
    agent_api_key: AgentApiKey | None,
) -> Profile:
    setattr(profile, AGENT_API_KEY_PROFILE_ATTR, agent_api_key)
    return profile


def _agent_actor_kwargs(profile: Profile) -> dict[str, AgentApiKey]:
    agent_api_key = getattr(profile, AGENT_API_KEY_PROFILE_ATTR, None)
    if agent_api_key is None:
        return {}
    return {"agent_api_key": agent_api_key}


def _authenticate_profile() -> Profile:
    token_profile = _get_access_token_profile()
    if token_profile is not None:
        return token_profile

    raise PermissionError(
        "Missing Rowset authorization. Configure the Rowset MCP server request with "
        "Authorization: Bearer <ROWSET_API_KEY>."
    )


def _get_access_token_profile() -> Profile | None:
    access_token = get_access_token()
    if access_token is None:
        return None

    claims = access_token.claims or {}
    profile_identifier = access_token.subject or claims.get("profile_id")
    if not profile_identifier:
        return None

    try:
        profile = Profile.objects.select_related("user").get(id=profile_identifier)
    except (Profile.DoesNotExist, ValueError) as exc:
        logger.warning(
            "mcp.authentication.denied",
            error_type=type(exc).__name__,
            reason="profile_unresolved",
        )
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
                "mcp.authentication.denied",
                error_type=type(exc).__name__,
                reason="agent_api_key_unresolved",
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
    details: JsonObject | None = None,
) -> JsonObject:
    return {
        "code": code,
        "message": _error_message_sentence(message),
        "retryable": retryable,
        "suggested_action": suggested_action,
        "details": details or {},
    }


def _mcp_tool_error(payload: JsonObject) -> ToolError:
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
                ("project section not found", "PROJECT_SECTION_NOT_FOUND"),
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
            (("archived", "DATASET_ARCHIVED"),),
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
        "PROJECT_SECTION_NOT_FOUND": "Check the project section key and parent project key.",
        "COLUMN_NOT_FOUND": "Check the column name against the dataset headers and try again.",
        "VALIDATION_ERROR": "Check the tool arguments against the dataset schema and try again.",
        "DATASET_ARCHIVED": "Restore the dataset before making changes.",
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


def _normalize_mcp_row_filters(filters: dict[str, Any] | str | None) -> dict[str, str]:
    if not filters:
        return {}
    if isinstance(filters, str):
        try:
            filters = json.loads(filters)
        except json.JSONDecodeError as exc:
            raise DatasetServiceError(
                400,
                "filters must be a JSON object keyed by dataset header.",
            ) from exc
    if not isinstance(filters, dict):
        raise DatasetServiceError(400, "filters must be a JSON object keyed by dataset header.")
    return {
        str(header): _stringify_mcp_row_filter_value(value) for header, value in filters.items()
    }


def _stringify_mcp_row_filter_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


def _permission_error_to_tool_error(exc: PermissionError) -> ToolError:
    raw_message = str(exc)
    normalized_message = raw_message.lower()
    if "missing" in normalized_message and "authorization" in normalized_message:
        code = "AUTHORIZATION_MISSING"
        suggested_action = "Configure the MCP request with Authorization: Bearer <ROWSET_API_KEY>."
        http_status = 401
    elif "no longer active" in normalized_message:
        code = "API_KEY_INACTIVE"
        suggested_action = "Create or select an active Rowset agent API key and retry."
        http_status = 401
    elif "requires" in normalized_message and "access" in normalized_message:
        code = "API_KEY_FORBIDDEN"
        suggested_action = "Use a Rowset API key with enough permissions for this action."
        http_status = 403
    else:
        code = "AUTHENTICATION_FAILED"
        suggested_action = (
            "Check that the MCP request sends Authorization: Bearer <ROWSET_API_KEY> "
            "with an active Rowset API key."
        )
        http_status = 401

    return _mcp_tool_error(
        _mcp_error_payload(
            code=code,
            message=raw_message,
            retryable=False,
            suggested_action=suggested_action,
            details={"http_status": http_status},
        )
    )


def _mcp_authenticated_profile(
    required_access_level: str = AgentApiKeyAccessLevel.READ,
    *,
    activate_trial: bool = True,
) -> Profile:
    try:
        profile = _authenticate_profile()
        require_agent_api_key_access(
            getattr(profile, AGENT_API_KEY_PROFILE_ATTR, None),
            required_access_level,
        )
        if activate_trial:
            activate_or_require_trial_access(profile)
        else:
            require_unexpired_trial_access(profile)
        return profile
    except TrialExpiredError as exc:
        raise _mcp_tool_error(
            _mcp_error_payload(
                code=exc.code,
                message=str(exc),
                retryable=False,
                suggested_action=f"Upgrade at {exc.upgrade_url}.",
                details={
                    "http_status": 402,
                    "trial_ended_at": exc.trial_ended_at.isoformat(),
                    "upgrade_url": exc.upgrade_url,
                },
            )
        ) from exc
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
        payload = serialize_user_info(profile)
    except DatasetServiceError as exc:
        raise _service_error_to_tool_error(exc) from exc
    track_activation_event(
        profile,
        ROWSET_GET_USER_INFO_SUCCEEDED,
        {
            "interface": "mcp",
            **agent_api_key_tracking_properties(getattr(profile, AGENT_API_KEY_PROFILE_ATTR, None)),
        },
        source_function="apps.mcp_server.server.get_user_info",
    )
    return payload


@mcp.tool(
    name="create_agent_api_key",
    description=(
        "Create a named Rowset API key for this account. Requires an admin Rowset API key. "
        "Use read for inspection-only agents, read_write for dataset updates, or admin "
        "when the new key must create other keys."
    ),
)
def create_agent_api_key_tool(
    name: Annotated[str, Field(description="Human-readable agent key name.")],
    access_level: Annotated[
        str,
        Field(
            default=AgentApiKeyAccessLevel.READ_WRITE,
            description="Permission level for the new key: read, read_write, or admin.",
        ),
    ] = AgentApiKeyAccessLevel.READ_WRITE,
) -> dict:
    close_old_connections()
    profile = _mcp_authenticated_profile(
        AgentApiKeyAccessLevel.ADMIN,
        activate_trial=False,
    )
    try:
        credential = create_agent_api_key_credential(profile, name, access_level)
    except ValueError as exc:
        raise _mcp_tool_error(
            _mcp_error_payload(
                code="VALIDATION_ERROR",
                message=str(exc),
                retryable=False,
                suggested_action="Use a unique key name and a supported permission level.",
                details={"http_status": 400},
            )
        ) from exc
    except IntegrityError as exc:
        raise _mcp_tool_error(
            _mcp_error_payload(
                code="AGENT_API_KEY_NAME_EXISTS",
                message="An agent API key with this name already exists.",
                retryable=False,
                suggested_action="Choose a different key name or revoke the existing key.",
                details={"http_status": 409},
            )
        ) from exc

    return {
        "status": "success",
        "message": f"Created an agent API key for {credential.agent_api_key.name}.",
        "agent_api_key": serialize_agent_api_key(credential.agent_api_key),
        "api_key": credential.raw_key,
    }


@mcp.tool(
    name="get_rowset_capabilities",
    description=(
        "Return the current Rowset feature guide, recommended startup sequence, "
        "MCP tool groups, REST fallback paths, use-case patterns, and safety guardrails."
    ),
)
def get_rowset_capabilities() -> dict:
    """Return the current Rowset feature guide for the authenticated agent."""
    close_old_connections()
    _mcp_authenticated_profile()
    return rowset_capabilities_payload()


@mcp.tool(
    name="submit_feedback",
    description=(
        "Submit concise product feedback about Rowset from the authenticated agent. "
        "Use this for setup friction, confusing MCP/API behavior, missing docs, or "
        "feature requests. Rowset stores it in the private Rowset/CX Feedback dataset. "
        "Do not include API keys, secrets, or private dataset contents."
    ),
)
def submit_feedback(
    feedback: Annotated[
        str,
        Field(
            min_length=1,
            max_length=2000,
            description="Concise feedback text. Do not include secrets or private row data.",
        ),
    ],
    page: Annotated[
        str | None,
        Field(
            default=None,
            max_length=255,
            description=(
                "Optional Rowset page, API path, MCP tool, or workflow where this came up."
            ),
        ),
    ] = None,
    context: Annotated[
        JsonObject | None,
        Field(
            default=None,
            description=(
                "Optional small JSON object with non-sensitive context such as tool name, "
                "category, or workflow."
            ),
        ),
    ] = None,
) -> dict:
    try:
        profile = _mcp_authenticated_profile(AgentApiKeyAccessLevel.READ_WRITE)
        try:
            result = submit_profile_feedback(
                profile=profile,
                feedback=feedback,
                page=page,
                source=FeedbackSource.MCP,
                metadata=context,
                **_agent_actor_kwargs(profile),
            )
        except DatasetServiceError as exc:
            raise _service_error_to_tool_error(exc) from exc
        except ValueError as exc:
            raise _mcp_tool_error(
                _mcp_error_payload(
                    code="VALIDATION_ERROR",
                    message=str(exc),
                    retryable=False,
                    suggested_action="Provide non-empty feedback up to 2,000 characters.",
                    details={"http_status": 400},
                )
            ) from exc

        return serialize_feedback_submission_result(
            result,
            feedback_context=context or {},
            include_feedback_id=True,
        )
    finally:
        close_old_connections()


@mcp.tool(
    name="get_all_datasets",
    description=(
        "Return compact discovery cards for datasets available to the authenticated Rowset "
        "profile. Call get_dataset for full context after selecting one."
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
    """Return a bounded page of datasets for the authenticated Rowset user."""
    close_old_connections()
    profile = _mcp_authenticated_profile()
    try:
        return serialize_profile_datasets(profile, limit=limit, offset=offset)
    except DatasetServiceError as exc:
        raise _service_error_to_tool_error(exc) from exc


@mcp.tool(
    name="get_archived_datasets",
    description=(
        "Return compact discovery cards for archived datasets owned by the authenticated "
        "Rowset profile. Call get_dataset for full context after selecting one."
    ),
)
def get_archived_datasets(
    limit: Annotated[
        int,
        Field(default=100, ge=1, le=500, description="Maximum archived datasets to return."),
    ] = 100,
    offset: Annotated[
        int,
        Field(default=0, ge=0, description="Number of archived datasets to skip."),
    ] = 0,
) -> dict:
    """Return a bounded page of archived datasets for the authenticated Rowset user."""
    close_old_connections()
    profile = _mcp_authenticated_profile()
    try:
        return serialize_profile_archived_datasets(profile, limit=limit, offset=offset)
    except DatasetServiceError as exc:
        raise _service_error_to_tool_error(exc) from exc


@mcp.tool(
    name="search_datasets",
    description=(
        "Search active datasets and return compact discovery cards. Filter by name, project, "
        "section, header, or update time, then call get_dataset for full context."
    ),
)
def search_datasets(
    query: Annotated[
        str | None,
        Field(
            default=None,
            description=(
                "Text to match against dataset name, description, instructions, project text, "
                "or section text."
            ),
        ),
    ] = None,
    project_key: Annotated[
        str | None,
        Field(default=None, description="Optional project key/UUID to restrict results."),
    ] = None,
    section_key: Annotated[
        str | None,
        Field(default=None, description="Optional project section key/UUID to restrict results."),
    ] = None,
    header_contains: Annotated[
        str | None,
        Field(default=None, description="Optional exact header name that results must contain."),
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
            section_key=section_key,
            header_contains=header_contains,
            updated_after=updated_after,
            limit=limit,
            offset=offset,
        )
    except DatasetServiceError as exc:
        raise _service_error_to_tool_error(exc) from exc


@mcp.tool(
    name="get_dataset",
    description=(
        "Return full context for one owned dataset, including instructions, metadata, headers, "
        "semantic schema, index settings, relationships, references, and preview configuration. "
        "Call this after discovery and before row operations."
    ),
)
def get_dataset(
    dataset_key: Annotated[str, Field(description=DATASET_IDENTIFIER_DESCRIPTION)],
) -> dict:
    close_old_connections()
    profile = _mcp_authenticated_profile()
    try:
        return serialize_dataset_detail(get_profile_dataset(profile, dataset_key))
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
    description="Search project metadata by project name, description, or JSON metadata.",
)
def search_projects(
    query: Annotated[
        str | None,
        Field(
            default=None,
            description="Text to match against project names, descriptions, and JSON metadata.",
        ),
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
    metadata: Annotated[
        JsonObject | None,
        Field(
            default=None,
            description=(
                "Optional JSON object for arbitrary project metadata, such as source links "
                "or agent workflow context."
            ),
        ),
    ] = None,
) -> dict:
    close_old_connections()
    profile = _mcp_authenticated_profile(AgentApiKeyAccessLevel.READ_WRITE)
    try:
        return create_profile_project(
            profile,
            name=name,
            description=description,
            metadata=metadata,
        )
    except DatasetServiceError as exc:
        raise _service_error_to_tool_error(exc) from exc


@mcp.tool(
    name="get_project_sections",
    description="Return sections inside one Rowset project for grouping related datasets.",
)
def get_project_sections(
    project_key: Annotated[str, Field(description="Rowset project key/UUID.")],
    limit: Annotated[
        int,
        Field(default=100, ge=1, le=500, description="Maximum sections to return."),
    ] = 100,
    offset: Annotated[
        int,
        Field(default=0, ge=0, description="Number of sections to skip."),
    ] = 0,
) -> dict:
    close_old_connections()
    profile = _mcp_authenticated_profile()
    try:
        return serialize_profile_project_sections(
            profile,
            project_key,
            limit=limit,
            offset=offset,
        )
    except DatasetServiceError as exc:
        raise _service_error_to_tool_error(exc) from exc


@mcp.tool(
    name="create_project_section",
    description=(
        "Create a section inside a Rowset project, such as Blog or Sales, for grouping "
        "related datasets without changing access boundaries."
    ),
)
def create_project_section(
    project_key: Annotated[str, Field(description="Rowset project key/UUID.")],
    name: Annotated[str, Field(description="Human-readable section name.")],
    description: Annotated[
        str | None,
        Field(default=None, description="Optional section description."),
    ] = None,
    metadata: Annotated[
        JsonObject | None,
        Field(
            default=None,
            description="Optional JSON object for arbitrary section metadata.",
        ),
    ] = None,
) -> dict:
    close_old_connections()
    profile = _mcp_authenticated_profile(AgentApiKeyAccessLevel.READ_WRITE)
    try:
        return create_profile_project_section(
            profile,
            project_key,
            name=name,
            description=description,
            metadata=metadata,
        )
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
    name="update_project",
    description=(
        "Update a semantic project name or description for the authenticated Rowset profile."
    ),
)
def update_project(
    project_key: Annotated[str, Field(description="Rowset project key/UUID.")],
    name: Annotated[
        str | None,
        Field(
            default=None,
            description=("Optional new project name. Omit or pass null to keep the current name."),
        ),
    ] = None,
    description: Annotated[
        str | None,
        Field(
            default=None,
            description=(
                "Optional new project description. Use an empty string to clear it; "
                "omit or pass null to keep the current description."
            ),
        ),
    ] = None,
) -> dict:
    close_old_connections()
    profile = _mcp_authenticated_profile(AgentApiKeyAccessLevel.READ_WRITE)
    updates = {}
    if name is not None:
        updates["name"] = name
    if description is not None:
        updates["description"] = description
    try:
        return update_profile_project(profile, project_key, **updates)
    except DatasetServiceError as exc:
        raise _service_error_to_tool_error(exc) from exc


@mcp.tool(
    name="update_project_metadata",
    description=(
        "Replace arbitrary JSON metadata for a Rowset project. Pass an empty object to clear it."
    ),
)
def update_project_metadata(
    project_key: Annotated[str, Field(description="Rowset project key/UUID.")],
    metadata: Annotated[
        JsonObject,
        Field(
            description=(
                "Replacement JSON object for arbitrary project metadata. Pass {} to clear it."
            ),
        ),
    ],
) -> dict:
    close_old_connections()
    profile = _mcp_authenticated_profile(AgentApiKeyAccessLevel.READ_WRITE)
    try:
        return update_profile_project_metadata(profile, project_key, metadata=metadata)
    except DatasetServiceError as exc:
        raise _service_error_to_tool_error(exc) from exc


@mcp.tool(
    name="update_project_section",
    description="Update a Rowset project section name or description.",
)
def update_project_section(
    project_key: Annotated[str, Field(description="Rowset project key/UUID.")],
    section_key: Annotated[str, Field(description="Rowset project section key/UUID.")],
    name: Annotated[
        str | None,
        Field(
            default=None,
            description=("Optional new section name. Omit or pass null to keep the current name."),
        ),
    ] = None,
    description: Annotated[
        str | None,
        Field(
            default=None,
            description=(
                "Optional new section description. Use an empty string to clear it; "
                "omit or pass null to keep the current description."
            ),
        ),
    ] = None,
) -> dict:
    close_old_connections()
    profile = _mcp_authenticated_profile(AgentApiKeyAccessLevel.READ_WRITE)
    updates = {}
    if name is not None:
        updates["name"] = name
    if description is not None:
        updates["description"] = description
    try:
        return update_profile_project_section(profile, project_key, section_key, **updates)
    except DatasetServiceError as exc:
        raise _service_error_to_tool_error(exc) from exc


@mcp.tool(
    name="archive_project_section",
    description=(
        "Archive a Rowset project section without deleting datasets. Datasets remain in "
        "the parent project and become unsectioned."
    ),
)
def archive_project_section(
    project_key: Annotated[str, Field(description="Rowset project key/UUID.")],
    section_key: Annotated[str, Field(description="Rowset project section key/UUID.")],
) -> dict:
    close_old_connections()
    profile = _mcp_authenticated_profile(AgentApiKeyAccessLevel.READ_WRITE)
    try:
        return archive_profile_project_section(profile, project_key, section_key)
    except DatasetServiceError as exc:
        raise _service_error_to_tool_error(exc) from exc


@mcp.tool(
    name="archive_project",
    description=(
        "Archive a Rowset project without deleting or archiving its datasets. "
        "Archived projects are omitted from normal project lists and cannot receive "
        "new dataset assignments."
    ),
)
def archive_project(
    project_key: Annotated[str, Field(description="Rowset project key/UUID.")],
) -> dict:
    close_old_connections()
    profile = _mcp_authenticated_profile(AgentApiKeyAccessLevel.READ_WRITE)
    try:
        return archive_profile_project(profile, project_key)
    except DatasetServiceError as exc:
        raise _service_error_to_tool_error(exc) from exc


@mcp.tool(
    name="create_dataset",
    description=(
        "Create an API-backed dataset for the authenticated Rowset profile. "
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
        JsonObject | None,
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
        list[DatasetRowInput] | None,
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
                "Supported types include text, tags, image, audio, choice, integer, number, "
                "currency, boolean, date, datetime, email, url, and reference. For choice "
                "columns, pass metadata "
                "like "
                '{"type": "choice", "choices": ["Ready to do", "Doing", "Done"]}. '
                "Use tags for comma-separated string values; Rowset returns the original "
                "string unchanged and renders nonblank segments as UI pills. "
                'For a dataset or project reference column, pass {"type": "reference", '
                '"target": "dataset"} or {"type": "reference", "target": "project"}. '
                'Add "description" to any metadata object to give agents column context.'
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
    section_key: Annotated[
        str | None,
        Field(
            default=None,
            description=(
                "Optional Rowset project section key. Requires project_key and must belong "
                "to the same project."
            ),
        ),
    ] = None,
) -> dict:
    close_old_connections()
    profile = _mcp_authenticated_profile(AgentApiKeyAccessLevel.READ_WRITE)
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
            section_key=section_key,
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
        JsonObject | None,
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
    profile = _mcp_authenticated_profile(AgentApiKeyAccessLevel.READ_WRITE)
    updates = {}
    if description is not None:
        updates["description"] = description
    if instructions is not None:
        updates["instructions"] = instructions
    if metadata is not None:
        updates["metadata"] = metadata
    updates.update(_agent_actor_kwargs(profile))
    try:
        return update_profile_dataset_metadata(
            profile,
            dataset_key,
            **updates,
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
                "include text, tags, image, audio, choice, integer, number, currency, boolean, "
                "date, datetime, email, url, reference, and calculated. For choice columns, pass "
                '{"type": "choice", '
                '"choices": ["Ready to do", "Doing", "Done"]}. '
                "Use tags for comma-separated string values; Rowset returns the original "
                "string unchanged and renders nonblank segments as UI pills. "
                'For a dataset or project reference column, pass {"type": "reference", '
                '"target": "dataset"} or '
                '{"type": "reference", "target": "project"}. For a calculated count from an '
                'incoming relationship, pass {"type": "calculated", "calculation": '
                '"relationship_count", "relationship_key": "..."}. Add '
                '"description" to any metadata object to give agents column context.'
            ),
        ),
    ],
) -> dict:
    close_old_connections()
    profile = _mcp_authenticated_profile(AgentApiKeyAccessLevel.READ_WRITE)
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
        "Add one column to an existing active Rowset dataset and backfill existing rows "
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
                "include text, tags, image, audio, choice, integer, number, currency, boolean, "
                "date, datetime, email, url, reference, and calculated. For a choice column, pass "
                '{"type": "choice", '
                '"choices": ["Ready to do", "Doing", "Done"]}. '
                "Use tags for comma-separated string values; Rowset returns the original "
                "string unchanged and renders nonblank segments as UI pills. "
                'For a dataset or project reference column, pass {"type": "reference", '
                '"target": "dataset"} or '
                '{"type": "reference", "target": "project"}. For a calculated count from an '
                'incoming relationship, pass {"type": "calculated", "calculation": '
                '"relationship_count", "relationship_key": "..."}. Add '
                '"description" to the metadata object to give agents column context.'
            ),
        ),
    ] = None,
) -> dict:
    close_old_connections()
    profile = _mcp_authenticated_profile(AgentApiKeyAccessLevel.READ_WRITE)
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
        "Rename one column on an existing active Rowset dataset while preserving row values."
    ),
)
def rename_column(
    dataset_key: Annotated[str, Field(description=DATASET_IDENTIFIER_DESCRIPTION)],
    old_name: Annotated[str, Field(description="Existing dataset column name.")],
    new_name: Annotated[str, Field(description="New dataset column name.")],
) -> dict:
    close_old_connections()
    profile = _mcp_authenticated_profile(AgentApiKeyAccessLevel.READ_WRITE)
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
    description="Drop one non-index column from an existing active Rowset dataset and its rows.",
)
def drop_column(
    dataset_key: Annotated[str, Field(description=DATASET_IDENTIFIER_DESCRIPTION)],
    name: Annotated[str, Field(description="Existing non-index dataset column name.")],
) -> dict:
    close_old_connections()
    profile = _mcp_authenticated_profile(AgentApiKeyAccessLevel.READ_WRITE)
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
    profile = _mcp_authenticated_profile(AgentApiKeyAccessLevel.READ_WRITE)
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
        "Attach an existing Rowset dataset to a project and optional section, or detach "
        "it from its project by passing null for project_key."
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
    section_key: Annotated[
        str | None,
        Field(
            default=None,
            description=(
                "Optional Rowset project section key. Requires project_key and clears the "
                "section when omitted or null."
            ),
        ),
    ] = None,
) -> dict:
    close_old_connections()
    profile = _mcp_authenticated_profile(AgentApiKeyAccessLevel.READ_WRITE)
    try:
        return update_profile_dataset_project(
            profile,
            dataset_key,
            project_key,
            section_key=section_key,
            **_agent_actor_kwargs(profile),
        )
    except DatasetServiceError as exc:
        raise _service_error_to_tool_error(exc) from exc


@mcp.tool(
    name="list_dataset_relationships",
    description=(
        "Return relationship definitions where the source dataset has a column that stores "
        "another dataset row's index value."
    ),
)
def list_dataset_relationships(
    dataset_key: Annotated[str, Field(description=DATASET_IDENTIFIER_DESCRIPTION)],
) -> dict:
    close_old_connections()
    profile = _mcp_authenticated_profile()
    try:
        return list_profile_dataset_relationships(profile, dataset_key)
    except DatasetServiceError as exc:
        raise _service_error_to_tool_error(exc) from exc


@mcp.tool(
    name="create_dataset_relationship",
    description=(
        "Create one relationship from a source dataset column to another active dataset's "
        "index column. When enforcement is true, row writes fail if the source value does "
        "not match an existing target row index."
    ),
)
def create_dataset_relationship(
    dataset_key: Annotated[str, Field(description=DATASET_IDENTIFIER_DESCRIPTION)],
    source_column: Annotated[
        str,
        Field(description="Source dataset column that stores target row index values."),
    ],
    target_dataset_key: Annotated[
        str,
        Field(description="Ready Rowset dataset key that the source column points to."),
    ],
    name: Annotated[
        str | None,
        Field(default=None, description="Optional relationship name. Defaults from the column."),
    ] = None,
    enforce_integrity: Annotated[
        bool,
        Field(
            default=True,
            description="When true, validate non-blank source values against target row indexes.",
        ),
    ] = True,
) -> dict:
    close_old_connections()
    profile = _mcp_authenticated_profile(AgentApiKeyAccessLevel.READ_WRITE)
    try:
        return create_profile_dataset_relationship(
            profile,
            dataset_key,
            source_column=source_column,
            target_dataset_key=target_dataset_key,
            name=name,
            enforce_integrity=enforce_integrity,
            **_agent_actor_kwargs(profile),
        )
    except DatasetServiceError as exc:
        raise _service_error_to_tool_error(exc) from exc


@mcp.tool(
    name="resolve_dataset_relationship",
    description=(
        "Resolve one source row through a dataset relationship and return the related "
        "target row when the source column has a target index value."
    ),
)
def resolve_dataset_relationship(
    dataset_key: Annotated[str, Field(description=DATASET_IDENTIFIER_DESCRIPTION)],
    relationship_key: Annotated[str, Field(description="Relationship key returned by Rowset.")],
    source_index_value: Annotated[
        str,
        Field(description="Index value of the source dataset row to resolve."),
    ],
) -> dict:
    close_old_connections()
    profile = _mcp_authenticated_profile()
    try:
        return resolve_profile_dataset_relationship(
            profile,
            dataset_key,
            relationship_key,
            source_index_value=source_index_value,
        )
    except DatasetServiceError as exc:
        raise _service_error_to_tool_error(exc) from exc


@mcp.tool(
    name="delete_dataset_relationship",
    description="Delete one dataset relationship definition without changing rows.",
)
def delete_dataset_relationship(
    dataset_key: Annotated[str, Field(description=DATASET_IDENTIFIER_DESCRIPTION)],
    relationship_key: Annotated[str, Field(description="Relationship key returned by Rowset.")],
) -> dict:
    close_old_connections()
    profile = _mcp_authenticated_profile(AgentApiKeyAccessLevel.READ_WRITE)
    try:
        return delete_profile_dataset_relationship(
            profile,
            dataset_key,
            relationship_key,
            **_agent_actor_kwargs(profile),
        )
    except DatasetServiceError as exc:
        raise _service_error_to_tool_error(exc) from exc


@mcp.tool(
    name="update_dataset_public_preview",
    description=(
        "Enable, disable, password-protect, or resize a read-only public preview for "
        "an existing active Rowset dataset. Returns the public preview URL."
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
    profile = _mcp_authenticated_profile(AgentApiKeyAccessLevel.READ_WRITE)
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
    profile = _mcp_authenticated_profile(AgentApiKeyAccessLevel.READ_WRITE)
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
    profile = _mcp_authenticated_profile(AgentApiKeyAccessLevel.READ_WRITE)
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
        "Return a bounded page of rows for a dataset, including archived datasets "
        "when addressed directly. Optionally search across row values, filter by column "
        "values, and sort by row_number or a dataset header."
    ),
)
def list_dataset_rows(
    dataset_key: Annotated[str, Field(description=DATASET_IDENTIFIER_DESCRIPTION)],
    limit: Annotated[int | None, Field(default=100, ge=1, le=500)] = 100,
    offset: Annotated[int | None, Field(default=0, ge=0)] = 0,
    query: Annotated[
        str | None,
        Field(default=None, description="Optional text to search across row values."),
    ] = None,
    filters: Annotated[
        dict[str, Any] | str | None,
        Field(
            default=None,
            description=(
                "Optional mapping, or JSON object string, from dataset header to a value "
                "to filter by. "
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
            limit=100 if limit is None else limit,
            offset=0 if offset is None else offset,
            query=query,
            filters=_normalize_mcp_row_filters(filters),
            sort=sort,
            direction=direction,
        )
    except DatasetServiceError as exc:
        raise _service_error_to_tool_error(exc) from exc


@mcp.tool(
    name="search_rows",
    description=(
        "Search rows across the authenticated Rowset profile with hybrid vector and lexical "
        "retrieval. Use this when the relevant dataset is unknown or when searching across "
        "multiple datasets."
    ),
)
def search_rows(
    query: Annotated[str, Field(description="Natural language or keyword search text.")],
    filters: Annotated[
        dict[str, Any] | str | None,
        Field(
            default=None,
            description=(
                "Optional JSON object string or mapping from dataset header to a row "
                "filter value. Non-string JSON values are converted to strings. "
                "Datasets missing these headers are excluded."
            ),
        ),
    ] = None,
    filter_operators: Annotated[
        dict[str, str] | None,
        Field(
            default=None,
            description=(
                "Optional row filter operators keyed by header, such as contains, is, above, "
                "or below."
            ),
        ),
    ] = None,
    dataset_key: Annotated[
        str | None,
        Field(default=None, description="Optional Rowset dataset key, public key, or URL."),
    ] = None,
    project_key: Annotated[
        str | None,
        Field(default=None, description="Optional project key to restrict searched datasets."),
    ] = None,
    section_key: Annotated[
        str | None,
        Field(
            default=None,
            description="Optional project section key to restrict searched datasets.",
        ),
    ] = None,
    archived: Annotated[
        bool | None,
        Field(
            default=False,
            description=(
                "False searches active datasets, true searches archived datasets, "
                "null searches both."
            ),
        ),
    ] = False,
    sort: Annotated[
        str | None,
        Field(default="rank", description="Optional result sort: rank, dataset, or row_number."),
    ] = "rank",
    direction: Annotated[
        str | None,
        Field(default=None, description="Optional sort direction: asc or desc."),
    ] = None,
    limit: Annotated[
        int | None,
        Field(default=10, ge=1, le=50, description="Maximum ranked results to return."),
    ] = 10,
) -> dict:
    close_old_connections()
    profile = _mcp_authenticated_profile()
    try:
        return search_profile_rows(
            profile,
            query=query,
            filters=_normalize_mcp_row_filters(filters),
            filter_operators=filter_operators,
            dataset_key=dataset_key,
            project_key=project_key,
            section_key=section_key,
            archived=archived,
            sort=sort,
            direction=direction,
            limit=10 if limit is None else limit,
        )
    except DatasetServiceError as exc:
        raise _service_error_to_tool_error(exc) from exc


@mcp.tool(
    name="search_dataset_rows",
    description=(
        "Search one dataset, including archived datasets when addressed directly, "
        "with hybrid vector and lexical retrieval. Results are hydrated from Rowset rows "
        "and include match metadata."
    ),
)
def search_dataset_rows(
    dataset_key: Annotated[str, Field(description=DATASET_IDENTIFIER_DESCRIPTION)],
    query: Annotated[str, Field(description="Search text to match semantically and exactly.")],
    filters: Annotated[
        dict[str, Any] | str | None,
        Field(
            default=None,
            description=(
                "Optional JSON object string or mapping from dataset header to canonical "
                "row filter value. Non-string JSON values are converted to strings."
            ),
        ),
    ] = None,
    limit: Annotated[
        int | None,
        Field(default=10, ge=1, le=50, description="Maximum ranked results to return."),
    ] = 10,
) -> dict:
    close_old_connections()
    profile = _mcp_authenticated_profile()
    try:
        return search_profile_dataset_rows(
            profile,
            dataset_key,
            query=query,
            filters=_normalize_mcp_row_filters(filters),
            limit=10 if limit is None else limit,
        )
    except DatasetServiceError as exc:
        raise _service_error_to_tool_error(exc) from exc


@mcp.tool(
    name="get_dataset_row",
    description=(
        "Return one row from a dataset by internal row id, including archived "
        "datasets when addressed directly."
    ),
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
    description=(
        "Return one row from a dataset by its configured index value, including "
        "archived datasets when addressed directly."
    ),
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
    description="Create one row in an active dataset. Provide values keyed by dataset header.",
)
def create_dataset_row(
    dataset_key: Annotated[str, Field(description=DATASET_IDENTIFIER_DESCRIPTION)],
    data: Annotated[DatasetRowInput, Field(description="Row values keyed by dataset header.")],
) -> dict:
    close_old_connections()
    profile = _mcp_authenticated_profile(AgentApiKeyAccessLevel.READ_WRITE)
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
    name="attach_image_to_dataset_row",
    description=(
        "Attach or replace one image asset in an image column for an active dataset row. "
        "The target row must already exist. Provide exactly one of row_id or index_value. "
        "The row cell will store an opaque asset reference, not raw image bytes. For a "
        "local file, read the bytes in the agent environment and pass base64 or a data "
        "URI. Hosted MCP cannot read local file paths."
    ),
)
def attach_image_to_dataset_row(
    dataset_key: Annotated[str, Field(description=DATASET_IDENTIFIER_DESCRIPTION)],
    column_name: Annotated[
        str,
        Field(description="Image column header to attach the asset to."),
    ],
    image_base64: Annotated[
        str,
        Field(
            description=(
                "JPEG, PNG, or WebP image bytes encoded as base64 or a data URI. Do "
                "not pass a local file path; read the bytes client-side and encode them."
            )
        ),
    ],
    row_id: Annotated[
        int | None,
        Field(default=None, ge=1, description="Internal Rowset row id."),
    ] = None,
    index_value: Annotated[
        str | None,
        Field(default=None, description="Value from the dataset index column."),
    ] = None,
    filename: Annotated[
        str | None,
        Field(default=None, description="Optional image filename for display metadata."),
    ] = None,
    content_type: Annotated[
        str | None,
        Field(default=None, description="Optional supplied content type, such as image/png."),
    ] = None,
) -> dict:
    close_old_connections()
    profile = _mcp_authenticated_profile(AgentApiKeyAccessLevel.READ_WRITE)
    try:
        return attach_profile_dataset_image_asset(
            profile,
            dataset_key,
            row_id=row_id,
            index_value=index_value,
            column_name=column_name,
            image_base64=image_base64,
            filename=filename,
            content_type=content_type,
            **_agent_actor_kwargs(profile),
        )
    except DatasetServiceError as exc:
        raise _service_error_to_tool_error(exc) from exc


@mcp.tool(
    name="get_dataset_image_asset",
    description=(
        "Return metadata plus authenticated content URLs for one image asset. "
        "When a dataset public preview is enabled without password protection, "
        "the response also includes public_content_url and public_thumbnail_url "
        "for browser sharing."
    ),
)
def get_dataset_image_asset(
    dataset_key: Annotated[str, Field(description=DATASET_IDENTIFIER_DESCRIPTION)],
    asset_key: Annotated[str, Field(description="Image asset key returned by Rowset.")],
) -> dict:
    close_old_connections()
    profile = _mcp_authenticated_profile()
    try:
        return serialize_profile_dataset_asset(profile, dataset_key, asset_key)
    except DatasetServiceError as exc:
        raise _service_error_to_tool_error(exc) from exc


@mcp.tool(
    name="attach_audio_to_dataset_row",
    description=(
        "Attach or replace one audio asset in an audio column for an active dataset row. "
        "The target row must already exist. Provide exactly one of row_id or index_value. "
        "The row cell will store an opaque asset reference, not raw audio bytes. For a "
        "local file, read the bytes in the agent environment and pass base64 or a data "
        "URI. Hosted MCP cannot read local file paths."
    ),
)
def attach_audio_to_dataset_row(
    dataset_key: Annotated[str, Field(description=DATASET_IDENTIFIER_DESCRIPTION)],
    column_name: Annotated[
        str,
        Field(description="Audio column header to attach the asset to."),
    ],
    audio_base64: Annotated[
        str,
        Field(
            description=(
                "MP3, WAV, M4A, AAC, Ogg, FLAC, or WebM audio bytes encoded as "
                "base64 or a data URI. Do not pass a local file path; read the bytes "
                "client-side and encode them."
            )
        ),
    ],
    row_id: Annotated[
        int | None,
        Field(default=None, ge=1, description="Internal Rowset row id."),
    ] = None,
    index_value: Annotated[
        str | None,
        Field(default=None, description="Value from the dataset index column."),
    ] = None,
    filename: Annotated[
        str | None,
        Field(default=None, description="Optional audio filename for display metadata."),
    ] = None,
    content_type: Annotated[
        str | None,
        Field(default=None, description="Optional supplied content type, such as audio/wav."),
    ] = None,
) -> dict:
    close_old_connections()
    profile = _mcp_authenticated_profile(AgentApiKeyAccessLevel.READ_WRITE)
    try:
        return attach_profile_dataset_audio_asset(
            profile,
            dataset_key,
            row_id=row_id,
            index_value=index_value,
            column_name=column_name,
            audio_base64=audio_base64,
            filename=filename,
            content_type=content_type,
            **_agent_actor_kwargs(profile),
        )
    except DatasetServiceError as exc:
        raise _service_error_to_tool_error(exc) from exc


@mcp.tool(
    name="get_dataset_audio_asset",
    description=(
        "Return metadata plus authenticated content URLs for one audio asset. "
        "When a dataset public preview is enabled without password protection, "
        "the response also includes public_content_url for browser sharing."
    ),
)
def get_dataset_audio_asset(
    dataset_key: Annotated[str, Field(description=DATASET_IDENTIFIER_DESCRIPTION)],
    asset_key: Annotated[str, Field(description="Audio asset key returned by Rowset.")],
) -> dict:
    close_old_connections()
    profile = _mcp_authenticated_profile()
    try:
        return serialize_profile_dataset_asset(profile, dataset_key, asset_key)
    except DatasetServiceError as exc:
        raise _service_error_to_tool_error(exc) from exc


@mcp.tool(
    name="update_dataset_row",
    description="Patch one row in an active dataset. Unknown headers are ignored.",
)
def update_dataset_row(
    dataset_key: Annotated[str, Field(description=DATASET_IDENTIFIER_DESCRIPTION)],
    row_id: Annotated[int, Field(ge=1, description="Internal Rowset row id.")],
    data: Annotated[DatasetRowInput, Field(description="Header values to update on the row.")],
) -> dict:
    close_old_connections()
    profile = _mcp_authenticated_profile(AgentApiKeyAccessLevel.READ_WRITE)
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
    description="Patch one row in an active dataset by its configured index value.",
)
def update_dataset_row_by_index(
    dataset_key: Annotated[str, Field(description=DATASET_IDENTIFIER_DESCRIPTION)],
    index_value: Annotated[str, Field(description="Value from the dataset index column.")],
    data: Annotated[DatasetRowInput, Field(description="Header values to update on the row.")],
) -> dict:
    close_old_connections()
    profile = _mcp_authenticated_profile(AgentApiKeyAccessLevel.READ_WRITE)
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
    description="Delete one row from an active dataset by internal row id.",
)
def delete_dataset_row(
    dataset_key: Annotated[str, Field(description=DATASET_IDENTIFIER_DESCRIPTION)],
    row_id: Annotated[int, Field(ge=1, description="Internal Rowset row id.")],
) -> dict:
    close_old_connections()
    profile = _mcp_authenticated_profile(AgentApiKeyAccessLevel.READ_WRITE)
    try:
        return delete_profile_dataset_row(
            profile,
            dataset_key,
            row_id,
            **_agent_actor_kwargs(profile),
        )
    except DatasetServiceError as exc:
        raise _service_error_to_tool_error(exc) from exc
