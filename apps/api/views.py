import json
from typing import NoReturn

from django.core.cache import cache
from django.db import IntegrityError, connection
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.utils.cache import patch_vary_headers
from django.utils.http import content_disposition_header
from django.views.decorators.csrf import csrf_exempt
from ninja import Header, NinjaAPI
from ninja.errors import HttpError
from ninja.responses import Status

from apps.api.auth import (
    api_key_admin_auth,
    api_key_auth,
    api_key_write_auth,
    session_auth,
)
from apps.api.schemas import (
    AgentApiKeyCreateIn,
    AgentApiKeyCreateOut,
    AgentFeedbackSubmitOut,
    DatasetApiOut,
    DatasetArchiveOut,
    DatasetAssetApiOut,
    DatasetAudioAttachIn,
    DatasetAudioAttachOut,
    DatasetColumnAddIn,
    DatasetColumnDropIn,
    DatasetColumnMutationOut,
    DatasetColumnRenameIn,
    DatasetColumnReorderIn,
    DatasetColumnTypesOut,
    DatasetColumnTypesPatchIn,
    DatasetCreateIn,
    DatasetCreateOut,
    DatasetDetailOut,
    DatasetImageAttachIn,
    DatasetImageAttachOut,
    DatasetListOut,
    DatasetMetadataOut,
    DatasetMetadataPatchIn,
    DatasetProjectOut,
    DatasetProjectPatchIn,
    DatasetPublicPreviewOut,
    DatasetPublicPreviewPatchIn,
    DatasetRelationshipCreateIn,
    DatasetRelationshipCreateOut,
    DatasetRelationshipDeleteOut,
    DatasetRelationshipListOut,
    DatasetRelationshipResolveOut,
    DatasetRowIn,
    DatasetRowPatchIn,
    DatasetRowsOut,
    DatasetSearchIn,
    DatasetSearchOut,
    ProfileRowSearchIn,
    ProfileRowSearchOut,
    ProjectArchiveOut,
    ProjectCreateIn,
    ProjectCreateOut,
    ProjectDetailOut,
    ProjectListOut,
    ProjectMetadataOut,
    ProjectMetadataPatchIn,
    ProjectSectionArchiveOut,
    ProjectSectionCreateIn,
    ProjectSectionCreateOut,
    ProjectSectionListOut,
    ProjectSectionUpdateIn,
    ProjectSectionUpdateOut,
    ProjectUpdateIn,
    ProjectUpdateOut,
    PublicDatasetRowsOut,
    PublicDatasetSummaryOut,
    SubmitFeedbackIn,
    SubmitFeedbackOut,
    UserInfoOut,
    UserSettingsOut,
)
from apps.api.services import (
    AGENT_COLLECTION_DEFAULT_LIMIT,
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
    dataset_asset_content_field,
    delete_profile_dataset_relationship,
    delete_profile_dataset_row,
    drop_profile_dataset_column,
    get_profile_dataset,
    get_profile_dataset_asset,
    get_profile_dataset_row,
    get_profile_dataset_row_by_index,
    get_public_dataset,
    list_profile_dataset_relationships,
    list_profile_dataset_rows,
    list_public_dataset_rows,
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
    serialize_profile_project_detail,
    serialize_profile_project_sections,
    serialize_public_dataset_summary,
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
from apps.core.capabilities import CapabilitySelectionError, rowset_capabilities_payload
from apps.core.choices import FeedbackSource
from apps.core.post_deploy_smoke_auth import SMOKE_HEADER, read_smoke_token
from apps.core.services import (
    create_agent_api_key as create_agent_api_key_credential,
)
from apps.core.services import (
    serialize_agent_api_key,
    serialize_feedback,
    submit_profile_feedback,
)
from apps.core.trials import TrialExpiredError
from apps.datasets.public_previews import set_public_dataset_request_context
from apps.datasets.services import (
    DATASET_ASSET_CACHE_CONTROL,
    iter_export_row_data,
    rows_to_csv_text,
    rows_to_jsonl_text,
    rows_to_sqlite_bytes,
    rows_to_xlsx_bytes,
)
from rowset.utils import get_rowset_logger

logger = get_rowset_logger(__name__)

api = NinjaAPI()
DATASET_EXPORT_FORMATS = {
    "csv": ("text/csv; charset=utf-8", rows_to_csv_text),
    "jsonl": ("application/x-ndjson; charset=utf-8", rows_to_jsonl_text),
    "sqlite": ("application/vnd.sqlite3", rows_to_sqlite_bytes),
    "xlsx": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        rows_to_xlsx_bytes,
    ),
}


@api.exception_handler(TrialExpiredError)
def trial_expired_error_handler(request: HttpRequest, exc: TrialExpiredError):
    return api.create_response(
        request,
        {
            "code": exc.code,
            "message": str(exc),
            "upgrade_url": exc.upgrade_url,
            "trial_ended_at": exc.trial_ended_at.isoformat(),
        },
        status=402,
    )


def _raise_http_error(exc: DatasetServiceError) -> NoReturn:
    raise HttpError(exc.status_code, exc.message) from exc


def _parse_row_filters(filters: str | None) -> dict[str, str]:
    if not filters:
        return {}
    try:
        payload = json.loads(filters)
    except json.JSONDecodeError as exc:
        raise DatasetServiceError(
            400,
            "filters must be a JSON object keyed by dataset header.",
        ) from exc
    if not isinstance(payload, dict):
        raise DatasetServiceError(400, "filters must be a JSON object keyed by dataset header.")
    return {str(header): "" if value is None else str(value) for header, value in payload.items()}


def _export_dataset_response(dataset, export_format: str) -> HttpResponse:
    content_type, serializer = DATASET_EXPORT_FORMATS[export_format]
    response = HttpResponse(
        serializer(dataset.headers, iter_export_row_data(dataset)),
        content_type=content_type,
    )
    response["Content-Disposition"] = content_disposition_header(
        True,
        f"{dataset.name or 'dataset'}.{export_format}",
    )
    return response


def _dataset_asset_file_response(
    asset,
    variant: str,
    *,
    include_body: bool = True,
) -> HttpResponse:
    field = dataset_asset_content_field(asset, variant)
    if not field or not field.name:
        raise DatasetServiceError(404, "Dataset asset file not found.")
    normalized_variant = str(variant or "original").strip().lower()
    content_type = (
        "image/jpeg"
        if normalized_variant == "thumbnail" and asset.thumbnail
        else asset.content_type
    )
    if include_body:
        with field.open("rb") as asset_file:
            response = HttpResponse(asset_file.read(), content_type=content_type)
    else:
        response = HttpResponse(content_type=content_type)
    response["Content-Disposition"] = content_disposition_header(
        False,
        asset.original_filename or f"{asset.key}",
    )
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = DATASET_ASSET_CACHE_CONTROL
    patch_vary_headers(response, ["Authorization", "Cookie"])
    return response


def _agent_actor_kwargs(request: HttpRequest) -> dict:
    agent_api_key = getattr(request, "agent_api_key", None)
    if agent_api_key is None:
        return {}
    return {"agent_api_key": agent_api_key}


@csrf_exempt
def api_not_found(request: HttpRequest, unmatched: str = "") -> JsonResponse:
    return JsonResponse({"detail": "Not Found"}, status=404)


@api.get("/capabilities", auth=None, tags=["agent discovery"])
def get_rowset_capabilities(
    request: HttpRequest,
    topics: str | None = None,
    include_use_cases: bool = False,
    full: bool = False,
):
    selected_topics = topics.split(",") if topics else None
    try:
        return rowset_capabilities_payload(
            topics=selected_topics,
            include_use_cases=include_use_cases,
            full=full,
        )
    except CapabilitySelectionError as exc:
        raise HttpError(400, str(exc)) from exc


@api.get("/healthcheck", auth=None, include_in_schema=False, tags=["private"])
def healthcheck(request: HttpRequest):
    """
    Comprehensive healthcheck endpoint for monitoring and load balancers.

    Checks database and Redis connectivity.

    Returns:
    - 200 OK if all services are healthy
    - 503 if any service is down

    NOTE: We intentionally return boolean health fields (instead of "healthy"/"unhealthy"
    strings) to make healthcheck consumption trivial for load balancers and scripts.
    """

    checks = {
        "database": False,
        "redis": False,
    }

    # Check database connectivity
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        checks["database"] = True
    except Exception as exc:
        logger.error(
            "Healthcheck failed: Database connection error",
            error_type=type(exc).__name__,
            exc_info=True,
        )

    # Check Redis connectivity
    try:
        cache_key = "healthcheck_test"
        cache_value = "ok"
        cache.set(cache_key, cache_value, timeout=10)
        retrieved_value = cache.get(cache_key)

        if retrieved_value == cache_value:
            checks["redis"] = True
        else:
            logger.error(
                "Healthcheck failed: Redis value mismatch",
                expected=cache_value,
                retrieved=retrieved_value,
            )
    except Exception as exc:
        logger.error(
            "Healthcheck failed: Redis connection error",
            error_type=type(exc).__name__,
            exc_info=True,
        )

    healthy = all(checks.values())
    payload = {
        "healthy": healthy,
        "checks": checks,
    }

    if healthy:
        logger.debug("Healthcheck passed", **checks)
        return payload

    logger.error("Healthcheck failed", **checks)
    return 503, payload


@api.post(
    "/submit-feedback",
    response=SubmitFeedbackOut,
    auth=[session_auth],
    include_in_schema=False,
    tags=["private"],
)
def submit_feedback(request: HttpRequest, data: SubmitFeedbackIn):
    profile = request.auth
    try:
        result = submit_profile_feedback(
            profile=profile,
            feedback=data.feedback,
            page=data.page,
            source=FeedbackSource.BROWSER,
            metadata=data.context,
        )
        return {
            "success": True,
            "message": "Feedback submitted successfully",
            "row_url": result.row_url,
        }
    except ValueError as exc:
        return {"success": False, "message": str(exc)}
    except Exception as exc:
        logger.error(
            "Failed to submit feedback",
            error_type=type(exc).__name__,
            profile_id=profile.id,
        )
        return {"success": False, "message": "Failed to submit feedback. Please try again."}


def _is_post_deploy_smoke_request(request: HttpRequest) -> bool:
    """Recognize the short-lived identity and signed marker created by the smoke command."""
    profile = getattr(request, "auth", None)
    user = getattr(profile, "user", None)
    username = getattr(user, "username", "")
    marker = username.removeprefix("rowset-smoke-")
    agent_api_key = getattr(request, "agent_api_key", None)
    return bool(
        user
        and getattr(user, "is_active", False) is True
        and marker
        and marker != username
        and read_smoke_token(request.headers.get(SMOKE_HEADER, "")) == marker
        and getattr(agent_api_key, "name", "") == f"Post-deploy smoke {marker}"
    )


@api.get(
    "/user",
    response=UserInfoOut,
    auth=[api_key_auth],
    tags=["user"],
)
def get_user_info(request: HttpRequest):
    """Return safe profile and account details for the authenticated API key."""
    payload = serialize_user_info(request.auth)
    if not _is_post_deploy_smoke_request(request):
        track_activation_event(
            request.auth,
            ROWSET_GET_USER_INFO_SUCCEEDED,
            {
                "interface": "rest",
                **agent_api_key_tracking_properties(getattr(request, "agent_api_key", None)),
            },
            source_function="apps.api.views.get_user_info",
        )
    return payload


@api.post(
    "/feedback",
    response={201: AgentFeedbackSubmitOut},
    auth=[api_key_write_auth],
    tags=["feedback"],
)
def submit_agent_feedback(request: HttpRequest, payload: SubmitFeedbackIn):
    """Submit product feedback from an authenticated REST or agent client."""
    try:
        result = submit_profile_feedback(
            profile=request.auth,
            feedback=payload.feedback,
            page=payload.page,
            source=FeedbackSource.API,
            metadata=payload.context,
            agent_api_key=getattr(request, "agent_api_key", None),
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    except DatasetServiceError as exc:
        _raise_http_error(exc)

    return Status(
        201,
        {
            "status": "success",
            "message": "Feedback submitted successfully.",
            "feedback": serialize_feedback(result.feedback),
            "dataset": str(result.dataset.key) if result.dataset else "",
            "row": result.row.id if result.row else None,
            "row_url": result.row_url,
        },
    )


@api.post(
    "/search",
    response=ProfileRowSearchOut,
    auth=[api_key_auth],
    tags=["search"],
)
def search_rows(request: HttpRequest, payload: ProfileRowSearchIn):
    """Search rows across active datasets with hybrid vector and lexical retrieval."""
    try:
        return search_profile_rows(
            request.auth,
            query=payload.query,
            filters=payload.filters,
            filter_operators=payload.filter_operators,
            dataset_key=payload.dataset_key,
            project_key=payload.project_key,
            section_key=payload.section_key,
            archived=payload.archived,
            sort=payload.sort,
            direction=payload.direction,
            limit=payload.limit,
        )
    except DatasetServiceError as exc:
        _raise_http_error(exc)


@api.post(
    "/agent-api-keys",
    response={201: AgentApiKeyCreateOut},
    auth=[api_key_admin_auth],
    tags=["api-keys"],
)
def create_agent_api_key(request: HttpRequest, payload: AgentApiKeyCreateIn):
    """Create a named agent API key for the authenticated profile."""
    try:
        credential = create_agent_api_key_credential(
            request.auth,
            payload.name,
            payload.access_level,
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    except IntegrityError as exc:
        raise HttpError(409, "An agent API key with this name already exists.") from exc

    return Status(
        201,
        {
            "status": "success",
            "message": f"Created an agent API key for {credential.agent_api_key.name}.",
            "agent_api_key": serialize_agent_api_key(credential.agent_api_key),
            "api_key": credential.raw_key,
        },
    )


@api.get(
    "/user/settings",
    response=UserSettingsOut,
    auth=[session_auth],
    include_in_schema=False,
    tags=["private"],
)
def user_settings(request: HttpRequest):
    profile = request.auth
    try:
        profile_data = {
            "has_pro_subscription": profile.has_active_subscription,
        }
        data = {"profile": profile_data}

        return data
    except Exception as exc:
        logger.error(
            "Error fetching user settings",
            error_type=type(exc).__name__,
            profile_id=profile.id,
            exc_info=True,
        )
        raise HttpError(500, "An unexpected error occurred.") from exc


@api.get(
    "/projects",
    response=ProjectListOut,
    auth=[api_key_auth],
    tags=["projects"],
)
def list_projects(
    request: HttpRequest,
    limit: int = AGENT_COLLECTION_DEFAULT_LIMIT,
    offset: int = 0,
    query: str | None = None,
):
    """Return a page of semantic dataset projects for the authenticated profile."""
    try:
        return search_profile_projects(request.auth, query=query, limit=limit, offset=offset)
    except DatasetServiceError as exc:
        _raise_http_error(exc)


@api.post(
    "/projects",
    response={201: ProjectCreateOut},
    auth=[api_key_write_auth],
    tags=["projects"],
)
def create_project(request: HttpRequest, payload: ProjectCreateIn):
    """Create a semantic project for grouping datasets."""
    try:
        return Status(
            201,
            create_profile_project(
                request.auth,
                name=payload.name,
                description=payload.description,
                metadata=payload.metadata,
            ),
        )
    except DatasetServiceError as exc:
        _raise_http_error(exc)


@api.get(
    "/projects/{project_key}",
    response=ProjectDetailOut,
    auth=[api_key_auth],
    tags=["projects"],
)
def get_project(
    request: HttpRequest,
    project_key: str,
    limit: int = AGENT_COLLECTION_DEFAULT_LIMIT,
    offset: int = 0,
):
    """Return one project and a bounded page of assigned datasets."""
    try:
        return serialize_profile_project_detail(
            request.auth,
            project_key,
            limit=limit,
            offset=offset,
        )
    except DatasetServiceError as exc:
        _raise_http_error(exc)


@api.patch(
    "/projects/{project_key}",
    response=ProjectUpdateOut,
    auth=[api_key_write_auth],
    tags=["projects"],
)
def patch_project(request: HttpRequest, project_key: str, payload: ProjectUpdateIn):
    """Update semantic project metadata for the authenticated profile."""
    updates = payload.model_dump(exclude_unset=True)
    for key, value in updates.items():
        if value is None:
            raise HttpError(
                400,
                f"Project {key} cannot be null. Omit it to leave the current value unchanged.",
            )
    try:
        return update_profile_project(request.auth, project_key, **updates)
    except DatasetServiceError as exc:
        _raise_http_error(exc)


@api.patch(
    "/projects/{project_key}/metadata",
    response=ProjectMetadataOut,
    auth=[api_key_write_auth],
    tags=["projects"],
)
def patch_project_metadata(
    request: HttpRequest,
    project_key: str,
    payload: ProjectMetadataPatchIn,
):
    """Replace arbitrary JSON metadata for a project owned by the authenticated profile."""
    try:
        return update_profile_project_metadata(
            request.auth,
            project_key,
            metadata=payload.metadata,
        )
    except DatasetServiceError as exc:
        _raise_http_error(exc)


@api.get(
    "/projects/{project_key}/sections",
    response=ProjectSectionListOut,
    auth=[api_key_auth],
    tags=["projects"],
)
def list_project_sections(
    request: HttpRequest,
    project_key: str,
    limit: int = AGENT_COLLECTION_DEFAULT_LIMIT,
    offset: int = 0,
):
    """Return a page of active sections inside one project."""
    try:
        return serialize_profile_project_sections(
            request.auth,
            project_key,
            limit=limit,
            offset=offset,
        )
    except DatasetServiceError as exc:
        _raise_http_error(exc)


@api.post(
    "/projects/{project_key}/sections",
    response={201: ProjectSectionCreateOut},
    auth=[api_key_write_auth],
    tags=["projects"],
)
def create_project_section(
    request: HttpRequest,
    project_key: str,
    payload: ProjectSectionCreateIn,
):
    """Create a section for grouping datasets inside one project."""
    try:
        return Status(
            201,
            create_profile_project_section(
                request.auth,
                project_key,
                name=payload.name,
                description=payload.description,
                metadata=payload.metadata,
            ),
        )
    except DatasetServiceError as exc:
        _raise_http_error(exc)


@api.patch(
    "/projects/{project_key}/sections/{section_key}",
    response=ProjectSectionUpdateOut,
    auth=[api_key_write_auth],
    tags=["projects"],
)
def patch_project_section(
    request: HttpRequest,
    project_key: str,
    section_key: str,
    payload: ProjectSectionUpdateIn,
):
    """Update a section name or description inside one project."""
    updates = payload.model_dump(exclude_unset=True)
    for key, value in updates.items():
        if value is None:
            raise HttpError(
                400,
                (
                    f"Project section {key} cannot be null. "
                    "Omit it to leave the current value unchanged."
                ),
            )
    try:
        return update_profile_project_section(
            request.auth,
            project_key,
            section_key,
            **updates,
        )
    except DatasetServiceError as exc:
        _raise_http_error(exc)


@api.delete(
    "/projects/{project_key}/sections/{section_key}",
    response=ProjectSectionArchiveOut,
    auth=[api_key_write_auth],
    tags=["projects"],
)
def archive_project_section(
    request: HttpRequest,
    project_key: str,
    section_key: str,
):
    """Archive a section without deleting its datasets."""
    try:
        return archive_profile_project_section(request.auth, project_key, section_key)
    except DatasetServiceError as exc:
        _raise_http_error(exc)


@api.delete(
    "/projects/{project_key}",
    response=ProjectArchiveOut,
    auth=[api_key_write_auth],
    tags=["projects"],
)
def archive_project(request: HttpRequest, project_key: str):
    """Archive a project without deleting or archiving its datasets."""
    try:
        return archive_profile_project(request.auth, project_key)
    except DatasetServiceError as exc:
        _raise_http_error(exc)


@api.get(
    "/datasets",
    response=DatasetListOut,
    auth=[api_key_auth],
    tags=["datasets"],
)
def list_datasets(
    request: HttpRequest,
    limit: int = AGENT_COLLECTION_DEFAULT_LIMIT,
    offset: int = 0,
    query: str | None = None,
    project_key: str | None = None,
    section_key: str | None = None,
    header_contains: str | None = None,
    updated_after: str | None = None,
):
    """Return a page of datasets available to the authenticated profile."""
    try:
        return search_profile_datasets(
            request.auth,
            query=query,
            project_key=project_key,
            section_key=section_key,
            header_contains=header_contains,
            updated_after=updated_after,
            limit=limit,
            offset=offset,
        )
    except DatasetServiceError as exc:
        _raise_http_error(exc)


@api.get(
    "/datasets/archived",
    response=DatasetListOut,
    auth=[api_key_auth],
    tags=["datasets"],
)
def list_archived_datasets(
    request: HttpRequest,
    limit: int = AGENT_COLLECTION_DEFAULT_LIMIT,
    offset: int = 0,
):
    """Return a page of archived datasets owned by the authenticated profile."""
    try:
        return serialize_profile_archived_datasets(request.auth, limit=limit, offset=offset)
    except DatasetServiceError as exc:
        _raise_http_error(exc)


@api.post(
    "/datasets",
    response={201: DatasetCreateOut},
    auth=[api_key_write_auth],
    tags=["datasets"],
)
def create_dataset(request: HttpRequest, payload: DatasetCreateIn):
    """Create a ready API-backed dataset for the authenticated profile."""
    try:
        return Status(
            201,
            create_profile_dataset(
                request.auth,
                name=payload.name,
                description=payload.description,
                instructions=payload.instructions,
                metadata=payload.metadata,
                headers=payload.headers,
                rows=payload.rows,
                index_column=payload.index_column,
                column_types=payload.column_types,
                project_key=payload.project_key,
                section_key=payload.section_key,
                enqueue_background_work=not _is_post_deploy_smoke_request(request),
                **_agent_actor_kwargs(request),
            ),
        )
    except DatasetServiceError as exc:
        _raise_http_error(exc)


@api.get(
    "/public/datasets/{public_key}",
    response=PublicDatasetSummaryOut,
    auth=None,
    tags=["public datasets"],
)
def get_public_dataset_metadata(
    request: HttpRequest,
    public_key: str,
    password: str | None = Header(
        default=None,
        alias="X-Rowset-Public-Password",
    ),
):
    """Return safe metadata for an enabled public dataset."""
    try:
        dataset = get_public_dataset(public_key, password=password)
        response = serialize_public_dataset_summary(dataset)
    except DatasetServiceError as exc:
        if exc.public_access_state:
            set_public_dataset_request_context(
                request,
                access_state=exc.public_access_state,
            )
        _raise_http_error(exc)
    set_public_dataset_request_context(request, access_state="available", dataset=dataset)
    return response


@api.get(
    "/public/datasets/{public_key}/rows",
    response=PublicDatasetRowsOut,
    auth=None,
    tags=["public datasets"],
)
def list_public_rows(
    request: HttpRequest,
    public_key: str,
    limit: int = 100,
    offset: int = 0,
    query: str | None = None,
    filters: str | None = None,
    sort: str | None = None,
    direction: str | None = None,
    password: str | None = Header(
        default=None,
        alias="X-Rowset-Public-Password",
    ),
):
    """Return a bounded page of rows from an enabled public dataset."""
    try:
        response = list_public_dataset_rows(
            public_key,
            password=password,
            limit=limit,
            offset=offset,
            query=query,
            filters=_parse_row_filters(filters),
            sort=sort,
            direction=direction,
        )
    except DatasetServiceError as exc:
        if exc.public_access_state:
            set_public_dataset_request_context(
                request,
                access_state=exc.public_access_state,
            )
        _raise_http_error(exc)
    set_public_dataset_request_context(
        request,
        access_state="available",
        public_key=response["dataset"],
    )
    return response


@api.get(
    "/datasets/{dataset_key}",
    response=DatasetDetailOut,
    auth=[api_key_auth],
    tags=["datasets"],
)
def get_dataset(request: HttpRequest, dataset_key: str):
    """Return metadata, schema context, and relationship context for one dataset."""
    try:
        return serialize_dataset_detail(get_profile_dataset(request.auth, dataset_key))
    except DatasetServiceError as exc:
        _raise_http_error(exc)


@api.patch(
    "/datasets/{dataset_key}/metadata",
    response=DatasetMetadataOut,
    auth=[api_key_write_auth],
    tags=["datasets"],
)
def patch_dataset_metadata(
    request: HttpRequest,
    dataset_key: str,
    payload: DatasetMetadataPatchIn,
):
    """Update persistent dataset description, agent instructions, and JSON metadata."""
    updates = {
        key: value
        for key, value in payload.model_dump(exclude_unset=True).items()
        if value is not None
    }
    try:
        return update_profile_dataset_metadata(
            request.auth,
            dataset_key,
            **updates,
            **_agent_actor_kwargs(request),
        )
    except DatasetServiceError as exc:
        _raise_http_error(exc)


@api.delete(
    "/datasets/{dataset_key}",
    response=DatasetArchiveOut,
    auth=[api_key_write_auth],
    tags=["datasets"],
)
def archive_dataset(request: HttpRequest, dataset_key: str):
    """Archive a dataset without deleting its rows or schema metadata."""
    try:
        return archive_profile_dataset(
            request.auth,
            dataset_key,
            **_agent_actor_kwargs(request),
        )
    except DatasetServiceError as exc:
        _raise_http_error(exc)


@api.post(
    "/datasets/{dataset_key}/restore",
    response=DatasetArchiveOut,
    auth=[api_key_write_auth],
    tags=["datasets"],
)
def restore_dataset(request: HttpRequest, dataset_key: str):
    """Restore an archived dataset to normal dataset and project listings."""
    try:
        return restore_profile_dataset(
            request.auth,
            dataset_key,
            **_agent_actor_kwargs(request),
        )
    except DatasetServiceError as exc:
        _raise_http_error(exc)


@api.patch(
    "/datasets/{dataset_key}/column-types",
    response=DatasetColumnTypesOut,
    auth=[api_key_write_auth],
    tags=["datasets"],
)
def patch_dataset_column_types(
    request: HttpRequest,
    dataset_key: str,
    payload: DatasetColumnTypesPatchIn,
):
    """Update semantic column type metadata without changing row values."""
    try:
        return update_profile_dataset_column_types(
            request.auth,
            dataset_key,
            payload.column_types,
            **_agent_actor_kwargs(request),
        )
    except DatasetServiceError as exc:
        _raise_http_error(exc)


@api.post(
    "/datasets/{dataset_key}/columns",
    response=DatasetColumnMutationOut,
    auth=[api_key_write_auth],
    tags=["datasets"],
)
def add_dataset_column(
    request: HttpRequest,
    dataset_key: str,
    payload: DatasetColumnAddIn,
):
    """Add one column to a active dataset and backfill existing rows."""
    try:
        return add_profile_dataset_column(
            request.auth,
            dataset_key,
            name=payload.name,
            default_value=payload.default_value,
            column_type=payload.column_type,
            **_agent_actor_kwargs(request),
        )
    except DatasetServiceError as exc:
        _raise_http_error(exc)


@api.post(
    "/datasets/{dataset_key}/columns/rename",
    response=DatasetColumnMutationOut,
    auth=[api_key_write_auth],
    tags=["datasets"],
)
def rename_dataset_column(
    request: HttpRequest,
    dataset_key: str,
    payload: DatasetColumnRenameIn,
):
    """Rename one column on a active dataset while preserving row values."""
    try:
        return rename_profile_dataset_column(
            request.auth,
            dataset_key,
            old_name=payload.old_name,
            new_name=payload.new_name,
            **_agent_actor_kwargs(request),
        )
    except DatasetServiceError as exc:
        _raise_http_error(exc)


@api.post(
    "/datasets/{dataset_key}/columns/drop",
    response=DatasetColumnMutationOut,
    auth=[api_key_write_auth],
    tags=["datasets"],
)
def drop_dataset_column(
    request: HttpRequest,
    dataset_key: str,
    payload: DatasetColumnDropIn,
):
    """Drop one non-index column from a active dataset and stored rows."""
    try:
        return drop_profile_dataset_column(
            request.auth,
            dataset_key,
            name=payload.name,
            **_agent_actor_kwargs(request),
        )
    except DatasetServiceError as exc:
        _raise_http_error(exc)


@api.post(
    "/datasets/{dataset_key}/columns/reorder",
    response=DatasetColumnMutationOut,
    auth=[api_key_write_auth],
    tags=["datasets"],
)
def reorder_dataset_columns(
    request: HttpRequest,
    dataset_key: str,
    payload: DatasetColumnReorderIn,
):
    """Update the display and export order for active dataset columns."""
    try:
        return reorder_profile_dataset_columns(
            request.auth,
            dataset_key,
            headers=payload.headers,
            **_agent_actor_kwargs(request),
        )
    except DatasetServiceError as exc:
        _raise_http_error(exc)


@api.patch(
    "/datasets/{dataset_key}/project",
    response=DatasetProjectOut,
    auth=[api_key_write_auth],
    tags=["datasets"],
)
def patch_dataset_project(
    request: HttpRequest,
    dataset_key: str,
    payload: DatasetProjectPatchIn,
):
    """Attach an existing dataset to a project, or detach it when project_key is null."""
    try:
        return update_profile_dataset_project(
            request.auth,
            dataset_key,
            payload.project_key,
            section_key=payload.section_key,
            **_agent_actor_kwargs(request),
        )
    except DatasetServiceError as exc:
        _raise_http_error(exc)


@api.get(
    "/datasets/{dataset_key}/relationships",
    response=DatasetRelationshipListOut,
    auth=[api_key_auth],
    tags=["datasets"],
)
def list_dataset_relationships(request: HttpRequest, dataset_key: str):
    """Return relationship definitions where this dataset is the source."""
    try:
        return list_profile_dataset_relationships(request.auth, dataset_key)
    except DatasetServiceError as exc:
        _raise_http_error(exc)


@api.post(
    "/datasets/{dataset_key}/relationships",
    response={201: DatasetRelationshipCreateOut},
    auth=[api_key_write_auth],
    tags=["datasets"],
)
def create_dataset_relationship(
    request: HttpRequest,
    dataset_key: str,
    payload: DatasetRelationshipCreateIn,
):
    """Create one source-column to target-dataset-index relationship."""
    try:
        return Status(
            201,
            create_profile_dataset_relationship(
                request.auth,
                dataset_key,
                source_column=payload.source_column,
                target_dataset_key=payload.target_dataset_key,
                name=payload.name,
                enforce_integrity=payload.enforce_integrity,
                **_agent_actor_kwargs(request),
            ),
        )
    except DatasetServiceError as exc:
        _raise_http_error(exc)


@api.get(
    "/datasets/{dataset_key}/relationships/{relationship_key}/resolve",
    response=DatasetRelationshipResolveOut,
    auth=[api_key_auth],
    tags=["datasets"],
)
def resolve_dataset_relationship(
    request: HttpRequest,
    dataset_key: str,
    relationship_key: str,
    source_index_value: str,
):
    """Resolve one source row through a dataset relationship."""
    try:
        return resolve_profile_dataset_relationship(
            request.auth,
            dataset_key,
            relationship_key,
            source_index_value=source_index_value,
        )
    except DatasetServiceError as exc:
        _raise_http_error(exc)


@api.delete(
    "/datasets/{dataset_key}/relationships/{relationship_key}",
    response=DatasetRelationshipDeleteOut,
    auth=[api_key_write_auth],
    tags=["datasets"],
)
def delete_dataset_relationship(
    request: HttpRequest,
    dataset_key: str,
    relationship_key: str,
):
    """Delete one dataset relationship definition."""
    try:
        return delete_profile_dataset_relationship(
            request.auth,
            dataset_key,
            relationship_key,
            **_agent_actor_kwargs(request),
        )
    except DatasetServiceError as exc:
        _raise_http_error(exc)


@api.patch(
    "/datasets/{dataset_key}/public-preview",
    response=DatasetPublicPreviewOut,
    auth=[api_key_write_auth],
    tags=["datasets"],
)
def patch_dataset_public_preview(
    request: HttpRequest,
    dataset_key: str,
    payload: DatasetPublicPreviewPatchIn,
):
    """Update read-only public preview settings for a dataset."""
    try:
        return update_profile_dataset_public_preview(
            request.auth,
            dataset_key,
            public_enabled=payload.public_enabled,
            public_page_size=payload.public_page_size,
            public_password=payload.public_password,
            clear_public_password=payload.clear_public_password,
            **_agent_actor_kwargs(request),
        )
    except DatasetServiceError as exc:
        _raise_http_error(exc)


@api.get(
    "/datasets/{dataset_key}/rows",
    response=DatasetRowsOut,
    auth=[api_key_auth],
    tags=["datasets"],
)
def list_dataset_rows(
    request: HttpRequest,
    dataset_key: str,
    limit: int = AGENT_COLLECTION_DEFAULT_LIMIT,
    offset: int = 0,
    query: str | None = None,
    filters: str | None = None,
    sort: str | None = None,
    direction: str | None = None,
):
    """Return a bounded, optionally filtered and sorted page of rows for a dataset."""
    try:
        return list_profile_dataset_rows(
            request.auth,
            dataset_key,
            limit=limit,
            offset=offset,
            query=query,
            filters=_parse_row_filters(filters),
            sort=sort,
            direction=direction,
        )
    except DatasetServiceError as exc:
        _raise_http_error(exc)


@api.post(
    "/datasets/{dataset_key}/search",
    response=DatasetSearchOut,
    auth=[api_key_auth],
    tags=["datasets"],
)
def search_dataset_rows(
    request: HttpRequest,
    dataset_key: str,
    payload: DatasetSearchIn,
):
    """Return ranked hybrid vector and lexical search results for one dataset."""
    try:
        return search_profile_dataset_rows(
            request.auth,
            dataset_key,
            query=payload.query,
            filters=payload.filters,
            limit=payload.limit,
        )
    except DatasetServiceError as exc:
        _raise_http_error(exc)


@api.post(
    "/datasets/{dataset_key}/rows",
    response=DatasetApiOut,
    auth=[api_key_write_auth],
    tags=["datasets"],
)
def create_dataset_row(request: HttpRequest, dataset_key: str, payload: DatasetRowIn):
    try:
        return create_profile_dataset_row(
            request.auth,
            dataset_key,
            payload.data,
            **_agent_actor_kwargs(request),
        )
    except DatasetServiceError as exc:
        _raise_http_error(exc)


@api.post(
    "/datasets/{dataset_key}/rows/by-index/image",
    response=DatasetImageAttachOut,
    auth=[api_key_write_auth],
    tags=["datasets"],
)
def attach_dataset_row_image_by_index(
    request: HttpRequest,
    dataset_key: str,
    index_value: str,
    payload: DatasetImageAttachIn,
):
    """Attach or replace one image asset in an image column by row index value."""
    try:
        return attach_profile_dataset_image_asset(
            request.auth,
            dataset_key,
            index_value=index_value,
            column_name=payload.column_name,
            image_base64=payload.image_base64,
            filename=payload.filename,
            content_type=payload.content_type,
            **_agent_actor_kwargs(request),
        )
    except DatasetServiceError as exc:
        _raise_http_error(exc)


@api.post(
    "/datasets/{dataset_key}/rows/{row_id}/image",
    response=DatasetImageAttachOut,
    auth=[api_key_write_auth],
    tags=["datasets"],
)
def attach_dataset_row_image(
    request: HttpRequest,
    dataset_key: str,
    row_id: int,
    payload: DatasetImageAttachIn,
):
    """Attach or replace one image asset in an image column for a dataset row."""
    try:
        return attach_profile_dataset_image_asset(
            request.auth,
            dataset_key,
            row_id=row_id,
            column_name=payload.column_name,
            image_base64=payload.image_base64,
            filename=payload.filename,
            content_type=payload.content_type,
            **_agent_actor_kwargs(request),
        )
    except DatasetServiceError as exc:
        _raise_http_error(exc)


@api.post(
    "/datasets/{dataset_key}/rows/by-index/audio",
    response=DatasetAudioAttachOut,
    auth=[api_key_write_auth],
    tags=["datasets"],
)
def attach_dataset_row_audio_by_index(
    request: HttpRequest,
    dataset_key: str,
    index_value: str,
    payload: DatasetAudioAttachIn,
):
    """Attach or replace one audio asset in an audio column by row index value."""
    try:
        return attach_profile_dataset_audio_asset(
            request.auth,
            dataset_key,
            index_value=index_value,
            column_name=payload.column_name,
            audio_base64=payload.audio_base64,
            filename=payload.filename,
            content_type=payload.content_type,
            **_agent_actor_kwargs(request),
        )
    except DatasetServiceError as exc:
        _raise_http_error(exc)


@api.post(
    "/datasets/{dataset_key}/rows/{row_id}/audio",
    response=DatasetAudioAttachOut,
    auth=[api_key_write_auth],
    tags=["datasets"],
)
def attach_dataset_row_audio(
    request: HttpRequest,
    dataset_key: str,
    row_id: int,
    payload: DatasetAudioAttachIn,
):
    """Attach or replace one audio asset in an audio column for a dataset row."""
    try:
        return attach_profile_dataset_audio_asset(
            request.auth,
            dataset_key,
            row_id=row_id,
            column_name=payload.column_name,
            audio_base64=payload.audio_base64,
            filename=payload.filename,
            content_type=payload.content_type,
            **_agent_actor_kwargs(request),
        )
    except DatasetServiceError as exc:
        _raise_http_error(exc)


@api.get(
    "/datasets/{dataset_key}/assets/{asset_key}",
    response=DatasetAssetApiOut,
    auth=[api_key_auth],
    tags=["datasets"],
)
def get_dataset_asset_metadata(request: HttpRequest, dataset_key: str, asset_key: str):
    """Return metadata for one image asset owned by the authenticated profile."""
    try:
        return serialize_profile_dataset_asset(request.auth, dataset_key, asset_key)
    except DatasetServiceError as exc:
        _raise_http_error(exc)


@api.api_operation(
    ["GET", "HEAD"],
    "/datasets/{dataset_key}/assets/{asset_key}/content",
    auth=[api_key_auth],
    tags=["datasets"],
)
def get_dataset_asset_content(
    request: HttpRequest,
    dataset_key: str,
    asset_key: str,
    variant: str = "original",
):
    """Return original or thumbnail image bytes after Rowset API-key authorization."""
    try:
        asset = get_profile_dataset_asset(request.auth, dataset_key, asset_key)
        return _dataset_asset_file_response(
            asset,
            variant,
            include_body=request.method != "HEAD",
        )
    except DatasetServiceError as exc:
        _raise_http_error(exc)


@api.get(
    "/datasets/{dataset_key}/rows/by-index",
    response=DatasetApiOut,
    auth=[api_key_auth],
    tags=["datasets"],
)
def get_dataset_row_by_index(request: HttpRequest, dataset_key: str, index_value: str):
    try:
        return get_profile_dataset_row_by_index(request.auth, dataset_key, index_value)
    except DatasetServiceError as exc:
        _raise_http_error(exc)


@api.patch(
    "/datasets/{dataset_key}/rows/by-index",
    response=DatasetApiOut,
    auth=[api_key_write_auth],
    tags=["datasets"],
)
def patch_dataset_row_by_index(
    request: HttpRequest,
    dataset_key: str,
    index_value: str,
    payload: DatasetRowPatchIn,
):
    try:
        return patch_profile_dataset_row_by_index(
            request.auth,
            dataset_key,
            index_value,
            payload.data,
            **_agent_actor_kwargs(request),
        )
    except DatasetServiceError as exc:
        _raise_http_error(exc)


@api.get(
    "/datasets/{dataset_key}/rows/{row_id}",
    response=DatasetApiOut,
    auth=[api_key_auth],
    tags=["datasets"],
)
def get_dataset_row(request: HttpRequest, dataset_key: str, row_id: int):
    try:
        return get_profile_dataset_row(request.auth, dataset_key, row_id)
    except DatasetServiceError as exc:
        _raise_http_error(exc)


@api.patch(
    "/datasets/{dataset_key}/rows/{row_id}",
    response=DatasetApiOut,
    auth=[api_key_write_auth],
    tags=["datasets"],
)
def patch_dataset_row(
    request: HttpRequest,
    dataset_key: str,
    row_id: int,
    payload: DatasetRowPatchIn,
):
    try:
        return patch_profile_dataset_row(
            request.auth,
            dataset_key,
            row_id,
            payload.data,
            **_agent_actor_kwargs(request),
        )
    except DatasetServiceError as exc:
        _raise_http_error(exc)


@api.delete(
    "/datasets/{dataset_key}/rows/{row_id}",
    response=DatasetApiOut,
    auth=[api_key_write_auth],
    tags=["datasets"],
)
def delete_dataset_row(request: HttpRequest, dataset_key: str, row_id: int):
    try:
        return delete_profile_dataset_row(
            request.auth,
            dataset_key,
            row_id,
            **_agent_actor_kwargs(request),
        )
    except DatasetServiceError as exc:
        _raise_http_error(exc)


@api.get(
    "/datasets/{dataset_key}/export.csv",
    auth=[api_key_auth],
    tags=["datasets"],
)
def export_dataset_csv(request: HttpRequest, dataset_key: str):
    try:
        dataset = get_profile_dataset(request.auth, dataset_key)
    except DatasetServiceError as exc:
        _raise_http_error(exc)
    return _export_dataset_response(dataset, "csv")


@api.get(
    "/datasets/{dataset_key}/export.jsonl",
    auth=[api_key_auth],
    tags=["datasets"],
)
def export_dataset_jsonl(request: HttpRequest, dataset_key: str):
    try:
        dataset = get_profile_dataset(request.auth, dataset_key)
    except DatasetServiceError as exc:
        _raise_http_error(exc)
    return _export_dataset_response(dataset, "jsonl")


@api.get(
    "/datasets/{dataset_key}/export.xlsx",
    auth=[api_key_auth],
    tags=["datasets"],
)
def export_dataset_xlsx(request: HttpRequest, dataset_key: str):
    try:
        dataset = get_profile_dataset(request.auth, dataset_key)
    except DatasetServiceError as exc:
        _raise_http_error(exc)
    return _export_dataset_response(dataset, "xlsx")


@api.get(
    "/datasets/{dataset_key}/export.sqlite",
    auth=[api_key_auth],
    tags=["datasets"],
)
def export_dataset_sqlite(request: HttpRequest, dataset_key: str):
    try:
        dataset = get_profile_dataset(request.auth, dataset_key)
    except DatasetServiceError as exc:
        _raise_http_error(exc)
    return _export_dataset_response(dataset, "sqlite")
