import json
from typing import NoReturn

from django.core.cache import cache
from django.db import connection
from django.http import HttpRequest, HttpResponse
from django.utils.http import content_disposition_header
from ninja import NinjaAPI
from ninja.errors import HttpError
from ninja.responses import Status

from apps.api.auth import api_key_auth, session_auth, superuser_api_auth
from apps.api.schemas import (
    BlogPostDetailOut,
    BlogPostIn,
    BlogPostItemOut,
    BlogPostListOut,
    BlogPostOut,
    BlogPostUpdateIn,
    DatasetApiOut,
    DatasetArchiveOut,
    DatasetColumnAddIn,
    DatasetColumnDropIn,
    DatasetColumnMutationOut,
    DatasetColumnRenameIn,
    DatasetColumnReorderIn,
    DatasetColumnTypesOut,
    DatasetColumnTypesPatchIn,
    DatasetCreateIn,
    DatasetCreateOut,
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
    ProjectCreateIn,
    ProjectCreateOut,
    ProjectDetailOut,
    ProjectListOut,
    ProjectMetadataOut,
    ProjectMetadataPatchIn,
    ProjectUpdateIn,
    ProjectUpdateOut,
    SubmitFeedbackIn,
    SubmitFeedbackOut,
    UserInfoOut,
    UserSettingsOut,
)
from apps.api.services import (
    DatasetServiceError,
    add_profile_dataset_column,
    archive_profile_dataset,
    create_profile_dataset,
    create_profile_dataset_relationship,
    create_profile_dataset_row,
    create_profile_project,
    delete_profile_dataset_relationship,
    delete_profile_dataset_row,
    drop_profile_dataset_column,
    get_profile_dataset_row,
    get_profile_dataset_row_by_index,
    get_ready_profile_dataset,
    list_profile_dataset_relationships,
    list_profile_dataset_rows,
    patch_profile_dataset_row,
    patch_profile_dataset_row_by_index,
    rename_profile_dataset_column,
    reorder_profile_dataset_columns,
    resolve_profile_dataset_relationship,
    restore_profile_dataset,
    search_profile_datasets,
    search_profile_projects,
    serialize_profile_project_detail,
    serialize_user_info,
    update_profile_dataset_column_types,
    update_profile_dataset_metadata,
    update_profile_dataset_project,
    update_profile_dataset_public_preview,
    update_profile_project,
    update_profile_project_metadata,
)
from apps.blog.choices import BlogPostStatus
from apps.blog.models import BlogPost
from apps.core.models import Feedback
from apps.datasets.services import (
    iter_export_row_data,
    rows_to_csv_text,
    rows_to_jsonl_text,
    rows_to_sqlite_bytes,
    rows_to_xlsx_bytes,
)
from filebridge.utils import get_filebridge_logger

logger = get_filebridge_logger(__name__)

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


def _agent_actor_kwargs(request: HttpRequest) -> dict:
    agent_api_key = getattr(request, "agent_api_key", None)
    if agent_api_key is None:
        return {}
    return {"agent_api_key": agent_api_key}


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
    except Exception as e:
        logger.error(
            "Healthcheck failed: Database connection error",
            error=str(e),
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
    except Exception as e:
        logger.error(
            "Healthcheck failed: Redis connection error",
            error=str(e),
            exc_info=True,
        )

    healthy = all(checks.values())
    payload = {
        "healthy": healthy,
        "checks": checks,
    }

    if healthy:
        logger.info("Healthcheck passed", **checks)
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
        Feedback.objects.create(profile=profile, feedback=data.feedback, page=data.page)
        return {"success": True, "message": "Feedback submitted successfully"}
    except Exception as e:
        logger.error("Failed to submit feedback", error=str(e), profile_id=profile.id)
        return {"success": False, "message": "Failed to submit feedback. Please try again."}


def _serialize_blog_post(blog_post: BlogPost) -> BlogPostItemOut:
    return {
        "id": blog_post.id,
        "title": blog_post.title,
        "description": blog_post.description,
        "slug": blog_post.slug,
        "tags": blog_post.tags,
        "content": blog_post.content,
        "status": blog_post.status,
    }


@api.post(
    "/blog-posts/submit",
    response={200: BlogPostOut, 403: BlogPostOut},
    auth=[superuser_api_auth],
    include_in_schema=False,
    tags=["admin"],
)
def submit_blog_post(request: HttpRequest, data: BlogPostIn):
    profile = request.auth

    if not profile or not getattr(profile.user, "is_superuser", False):
        return 403, {"status": "error", "message": "Forbidden: superuser access required."}

    try:
        BlogPost.objects.create(
            title=data.title,
            description=data.description,
            slug=data.slug,
            tags=data.tags,
            content=data.content,
            status=data.status,
            # icon and image are ignored for now (file upload not handled)
        )
        return BlogPostOut(status="success", message="Blog post submitted successfully.")
    except Exception as e:
        return BlogPostOut(status="failure", message=f"Failed to submit blog post: {str(e)}")


@api.get(
    "/internal/blog-posts",
    response=BlogPostListOut,
    auth=[superuser_api_auth],
    include_in_schema=False,
    tags=["admin"],
)
def list_internal_blog_posts(request: HttpRequest):
    blog_posts = BlogPost.objects.order_by("-created_at")
    return {"blog_posts": [_serialize_blog_post(blog_post) for blog_post in blog_posts]}


@api.get(
    "/internal/blog-posts/{blog_post_id}",
    response={200: BlogPostDetailOut, 404: BlogPostOut},
    auth=[superuser_api_auth],
    include_in_schema=False,
    tags=["admin"],
)
def get_internal_blog_post(request: HttpRequest, blog_post_id: int):
    try:
        blog_post = BlogPost.objects.get(id=blog_post_id)
    except BlogPost.DoesNotExist:
        return 404, {"status": "error", "message": "Blog post not found."}

    return {
        "status": "success",
        "message": "Blog post retrieved successfully.",
        "blog_post": _serialize_blog_post(blog_post),
    }


@api.put(
    "/internal/blog-posts/{blog_post_id}",
    response={200: BlogPostDetailOut, 404: BlogPostOut},
    auth=[superuser_api_auth],
    include_in_schema=False,
    tags=["admin"],
)
def update_internal_blog_post(request: HttpRequest, blog_post_id: int, data: BlogPostIn):
    try:
        blog_post = BlogPost.objects.get(id=blog_post_id)
    except BlogPost.DoesNotExist:
        return 404, {"status": "error", "message": "Blog post not found."}

    blog_post.title = data.title
    blog_post.description = data.description
    blog_post.slug = data.slug
    blog_post.tags = data.tags
    blog_post.content = data.content
    blog_post.status = data.status
    blog_post.save(
        update_fields=["title", "description", "slug", "tags", "content", "status", "updated_at"]
    )

    return {
        "status": "success",
        "message": "Blog post updated successfully.",
        "blog_post": _serialize_blog_post(blog_post),
    }


@api.patch(
    "/internal/blog-posts/{blog_post_id}",
    response={200: BlogPostDetailOut, 404: BlogPostOut},
    auth=[superuser_api_auth],
    include_in_schema=False,
    tags=["admin"],
)
def patch_internal_blog_post(request: HttpRequest, blog_post_id: int, data: BlogPostUpdateIn):
    try:
        blog_post = BlogPost.objects.get(id=blog_post_id)
    except BlogPost.DoesNotExist:
        return 404, {"status": "error", "message": "Blog post not found."}

    fields_to_update = []
    for field in ["title", "description", "slug", "tags", "content", "status"]:
        value = getattr(data, field)
        if value is not None:
            setattr(blog_post, field, value)
            fields_to_update.append(field)

    if fields_to_update:
        blog_post.save(update_fields=[*fields_to_update, "updated_at"])

    return {
        "status": "success",
        "message": "Blog post updated successfully.",
        "blog_post": _serialize_blog_post(blog_post),
    }


@api.delete(
    "/internal/blog-posts/{blog_post_id}",
    response={200: BlogPostOut, 404: BlogPostOut},
    auth=[superuser_api_auth],
    include_in_schema=False,
    tags=["admin"],
)
def delete_internal_blog_post(request: HttpRequest, blog_post_id: int):
    deleted_count, _ = BlogPost.objects.filter(id=blog_post_id).delete()
    if deleted_count == 0:
        return 404, {"status": "error", "message": "Blog post not found."}

    return {"status": "success", "message": "Blog post deleted successfully."}


@api.post(
    "/internal/blog-posts/{blog_post_id}/review",
    response={200: BlogPostDetailOut, 404: BlogPostOut},
    auth=[superuser_api_auth],
    include_in_schema=False,
    tags=["admin"],
)
def review_internal_blog_post(request: HttpRequest, blog_post_id: int):
    try:
        blog_post = BlogPost.objects.get(id=blog_post_id)
    except BlogPost.DoesNotExist:
        return 404, {"status": "error", "message": "Blog post not found."}

    blog_post.status = BlogPostStatus.DRAFT
    blog_post.save(update_fields=["status", "updated_at"])
    return {
        "status": "success",
        "message": "Blog post moved to draft for review.",
        "blog_post": _serialize_blog_post(blog_post),
    }


@api.post(
    "/internal/blog-posts/{blog_post_id}/publish",
    response={200: BlogPostDetailOut, 404: BlogPostOut},
    auth=[superuser_api_auth],
    include_in_schema=False,
    tags=["admin"],
)
def publish_internal_blog_post(request: HttpRequest, blog_post_id: int):
    try:
        blog_post = BlogPost.objects.get(id=blog_post_id)
    except BlogPost.DoesNotExist:
        return 404, {"status": "error", "message": "Blog post not found."}

    blog_post.status = BlogPostStatus.PUBLISHED
    blog_post.save(update_fields=["status", "updated_at"])
    return {
        "status": "success",
        "message": "Blog post published successfully.",
        "blog_post": _serialize_blog_post(blog_post),
    }


@api.get(
    "/user",
    response=UserInfoOut,
    auth=[api_key_auth],
    tags=["user"],
)
def get_user_info(request: HttpRequest):
    """Return safe profile and account details for the authenticated API key."""
    return serialize_user_info(request.auth)


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
    except Exception as e:
        logger.error(
            "Error fetching user settings",
            error=str(e),
            profile_id=profile.id,
            exc_info=True,
        )
        raise HttpError(500, "An unexpected error occurred.") from e


@api.get(
    "/projects",
    response=ProjectListOut,
    auth=[api_key_auth],
    tags=["projects"],
)
def list_projects(
    request: HttpRequest,
    limit: int = 100,
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
    auth=[api_key_auth],
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
def get_project(request: HttpRequest, project_key: str, limit: int = 100, offset: int = 0):
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
    auth=[api_key_auth],
    tags=["projects"],
)
def patch_project(request: HttpRequest, project_key: str, payload: ProjectUpdateIn):
    """Update semantic project metadata for the authenticated profile."""
    updates = payload.model_dump(exclude_unset=True)
    for key, value in updates.items():
        if value is None:
            raise HttpError(
                400,
                f"Project {key} cannot be null. "
                "Omit it to leave the current value unchanged.",
            )
    try:
        return update_profile_project(request.auth, project_key, **updates)
    except DatasetServiceError as exc:
        _raise_http_error(exc)


@api.patch(
    "/projects/{project_key}/metadata",
    response=ProjectMetadataOut,
    auth=[api_key_auth],
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
    "/datasets",
    response=DatasetListOut,
    auth=[api_key_auth],
    tags=["datasets"],
)
def list_datasets(
    request: HttpRequest,
    limit: int = 100,
    offset: int = 0,
    query: str | None = None,
    project_key: str | None = None,
    header_contains: str | None = None,
    status: str | None = None,
    updated_after: str | None = None,
):
    """Return a page of datasets available to the authenticated profile."""
    try:
        return search_profile_datasets(
            request.auth,
            query=query,
            project_key=project_key,
            header_contains=header_contains,
            status=status,
            updated_after=updated_after,
            limit=limit,
            offset=offset,
        )
    except DatasetServiceError as exc:
        _raise_http_error(exc)


@api.post(
    "/datasets",
    response={201: DatasetCreateOut},
    auth=[api_key_auth],
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
                **_agent_actor_kwargs(request),
            ),
        )
    except DatasetServiceError as exc:
        _raise_http_error(exc)


@api.patch(
    "/datasets/{dataset_key}/metadata",
    response=DatasetMetadataOut,
    auth=[api_key_auth],
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
    auth=[api_key_auth],
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
    auth=[api_key_auth],
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
    auth=[api_key_auth],
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
    auth=[api_key_auth],
    tags=["datasets"],
)
def add_dataset_column(
    request: HttpRequest,
    dataset_key: str,
    payload: DatasetColumnAddIn,
):
    """Add one column to a ready dataset and backfill existing rows."""
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
    auth=[api_key_auth],
    tags=["datasets"],
)
def rename_dataset_column(
    request: HttpRequest,
    dataset_key: str,
    payload: DatasetColumnRenameIn,
):
    """Rename one column on a ready dataset while preserving row values."""
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
    auth=[api_key_auth],
    tags=["datasets"],
)
def drop_dataset_column(
    request: HttpRequest,
    dataset_key: str,
    payload: DatasetColumnDropIn,
):
    """Drop one non-index column from a ready dataset and stored rows."""
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
    auth=[api_key_auth],
    tags=["datasets"],
)
def reorder_dataset_columns(
    request: HttpRequest,
    dataset_key: str,
    payload: DatasetColumnReorderIn,
):
    """Update the display and export order for ready dataset columns."""
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
    auth=[api_key_auth],
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
    auth=[api_key_auth],
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
    auth=[api_key_auth],
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
    auth=[api_key_auth],
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
    limit: int = 100,
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
    "/datasets/{dataset_key}/rows",
    response=DatasetApiOut,
    auth=[api_key_auth],
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
    auth=[api_key_auth],
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
    auth=[api_key_auth],
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
    auth=[api_key_auth],
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
        dataset = get_ready_profile_dataset(request.auth, dataset_key)
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
        dataset = get_ready_profile_dataset(request.auth, dataset_key)
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
        dataset = get_ready_profile_dataset(request.auth, dataset_key)
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
        dataset = get_ready_profile_dataset(request.auth, dataset_key)
    except DatasetServiceError as exc:
        _raise_http_error(exc)
    return _export_dataset_response(dataset, "sqlite")
