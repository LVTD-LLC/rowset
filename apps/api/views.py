import csv

from django.core.cache import cache
from django.db import connection
from django.http import HttpRequest, HttpResponse
from ninja import NinjaAPI
from ninja.errors import HttpError

from apps.api.auth import api_key_auth, session_auth, superuser_api_auth
from apps.api.schemas import (
    BlogPostDetailOut,
    BlogPostIn,
    BlogPostItemOut,
    BlogPostListOut,
    BlogPostOut,
    BlogPostUpdateIn,
    DatasetApiOut,
    DatasetRowIn,
    DatasetRowOut,
    DatasetRowPatchIn,
    DatasetRowsOut,
    SubmitFeedbackIn,
    SubmitFeedbackOut,
    UserSettingsOut,
)
from apps.blog.choices import BlogPostStatus
from apps.blog.models import BlogPost
from apps.core.models import Feedback
from apps.datasets.choices import DatasetStatus
from apps.datasets.models import Dataset, DatasetRow
from filebridge.utils import get_filebridge_logger

logger = get_filebridge_logger(__name__)

api = NinjaAPI()


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
        return {"status": True, "message": "Feedback submitted successfully"}
    except Exception as e:
        logger.error("Failed to submit feedback", error=str(e), profile_id=profile.id)
        return {"status": False, "message": "Failed to submit feedback. Please try again."}


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


def _get_ready_dataset(profile, dataset_key: str) -> Dataset:
    try:
        dataset = Dataset.objects.get(key=dataset_key, profile=profile)
    except Dataset.DoesNotExist as exc:
        raise HttpError(404, "Dataset not found.") from exc

    if dataset.status != DatasetStatus.READY:
        raise HttpError(
            409,
            "Dataset is not ready yet. Confirm and wait for import first.",
        )

    return dataset


def _serialize_dataset_row(row: DatasetRow) -> DatasetRowOut:
    return {
        "id": row.id,
        "row_number": row.row_number,
        "index_value": row.index_value,
        "data": row.data,
    }


@api.get(
    "/datasets/{dataset_key}/rows",
    response=DatasetRowsOut,
    auth=[api_key_auth],
    tags=["datasets"],
)
def list_dataset_rows(request: HttpRequest, dataset_key: str, limit: int = 100, offset: int = 0):
    dataset = _get_ready_dataset(request.auth, dataset_key)
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    rows = dataset.rows.all()[offset : offset + limit]
    return {
        "dataset": str(dataset.key),
        "count": dataset.rows.count(),
        "rows": [_serialize_dataset_row(row) for row in rows],
    }


@api.post(
    "/datasets/{dataset_key}/rows",
    response=DatasetApiOut,
    auth=[api_key_auth],
    tags=["datasets"],
)
def create_dataset_row(request: HttpRequest, dataset_key: str, payload: DatasetRowIn):
    dataset = _get_ready_dataset(request.auth, dataset_key)
    last_row_number = (
        dataset.rows.order_by("-row_number").values_list("row_number", flat=True).first() or 0
    )
    row_number = last_row_number + 1
    if dataset.index_generated:
        index_value = str(row_number)
        data = {dataset.index_column: index_value, **payload.data}
    else:
        index_value = str(payload.data.get(dataset.index_column, "")).strip()
        if not index_value:
            raise HttpError(400, f"Index column '{dataset.index_column}' is required.")
        data = payload.data

    if dataset.rows.filter(index_value=index_value).exists():
        raise HttpError(409, f"Row with index '{index_value}' already exists.")

    row = DatasetRow.objects.create(
        dataset=dataset,
        row_number=row_number,
        index_value=index_value,
        data={header: str(data.get(header, "")) for header in dataset.headers},
    )
    dataset.row_count = dataset.rows.count()
    dataset.save(update_fields=["row_count", "updated_at"])
    return {"status": "success", "message": "Row created.", "row": _serialize_dataset_row(row)}


@api.get(
    "/datasets/{dataset_key}/rows/by-index",
    response=DatasetApiOut,
    auth=[api_key_auth],
    tags=["datasets"],
)
def get_dataset_row_by_index(request: HttpRequest, dataset_key: str, index_value: str):
    dataset = _get_ready_dataset(request.auth, dataset_key)
    try:
        row = dataset.rows.get(index_value=index_value)
    except DatasetRow.DoesNotExist as exc:
        raise HttpError(404, "Row not found.") from exc
    return {"status": "success", "message": "Row retrieved.", "row": _serialize_dataset_row(row)}


@api.get(
    "/datasets/{dataset_key}/rows/{row_id}",
    response=DatasetApiOut,
    auth=[api_key_auth],
    tags=["datasets"],
)
def get_dataset_row(request: HttpRequest, dataset_key: str, row_id: int):
    dataset = _get_ready_dataset(request.auth, dataset_key)
    try:
        row = dataset.rows.get(id=row_id)
    except DatasetRow.DoesNotExist as exc:
        raise HttpError(404, "Row not found.") from exc
    return {"status": "success", "message": "Row retrieved.", "row": _serialize_dataset_row(row)}


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
    dataset = _get_ready_dataset(request.auth, dataset_key)
    try:
        row = dataset.rows.get(id=row_id)
    except DatasetRow.DoesNotExist as exc:
        raise HttpError(404, "Row not found.") from exc

    row.data = {
        **row.data,
        **{key: str(value) for key, value in payload.data.items() if key in dataset.headers},
    }
    if dataset.index_column in payload.data:
        if dataset.index_generated:
            raise HttpError(
                400,
                f"Index column '{dataset.index_column}' is managed by FileBridge "
                "and cannot be updated.",
            )
        index_value = str(payload.data.get(dataset.index_column, "")).strip()
        if not index_value:
            raise HttpError(400, f"Index column '{dataset.index_column}' cannot be blank.")
        if dataset.rows.exclude(id=row.id).filter(index_value=index_value).exists():
            raise HttpError(409, f"Row with index '{index_value}' already exists.")
        row.index_value = index_value
    row.save(update_fields=["data", "index_value", "updated_at"])
    return {"status": "success", "message": "Row updated.", "row": _serialize_dataset_row(row)}


@api.delete(
    "/datasets/{dataset_key}/rows/{row_id}",
    response=DatasetApiOut,
    auth=[api_key_auth],
    tags=["datasets"],
)
def delete_dataset_row(request: HttpRequest, dataset_key: str, row_id: int):
    dataset = _get_ready_dataset(request.auth, dataset_key)
    deleted_count, _ = dataset.rows.filter(id=row_id).delete()
    if deleted_count == 0:
        raise HttpError(404, "Row not found.")
    dataset.row_count = dataset.rows.count()
    dataset.save(update_fields=["row_count", "updated_at"])
    return {"status": "success", "message": "Row deleted."}


@api.get(
    "/datasets/{dataset_key}/export.csv",
    auth=[api_key_auth],
    tags=["datasets"],
)
def export_dataset_csv(request: HttpRequest, dataset_key: str):
    dataset = _get_ready_dataset(request.auth, dataset_key)
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{dataset.name}.csv"'
    writer = csv.DictWriter(response, fieldnames=dataset.headers)
    writer.writeheader()
    for row in dataset.rows.all().iterator():
        writer.writerow({header: row.data.get(header, "") for header in dataset.headers})
    return response
