import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from time import perf_counter
from typing import Any
from urllib.parse import unquote, urlparse
from uuid import UUID, uuid4

from django.contrib.auth.hashers import make_password
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.files.base import ContentFile
from django.core.files.storage import storages
from django.db import IntegrityError, connection, transaction
from django.db.models import Count, Exists, OuterRef, Q, TextField
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Cast, Trim
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from apps.api.row_contracts import (
    RankedRowSearchCandidate,
    RowFilterOperators,
    RowFilters,
    RowSearchCandidate,
    RowWritePayload,
    normalize_row_data_for_headers,
    normalize_row_patch_for_headers,
    normalize_search_filter_operators,
    normalize_search_filters,
)
from apps.core.analytics import (
    ROWSET_DATASET_CREATED,
    ROWSET_DATASET_ROW_MUTATED,
    agent_api_key_tracking_properties,
    track_activation_event,
)
from apps.core.models import AgentApiKey, Profile
from apps.datasets.choices import DatasetColumnType, DatasetMutationType, DatasetStatus
from apps.datasets.constants import (
    MAX_DATASET_DESCRIPTION_LENGTH,
    MAX_DATASET_INSTRUCTIONS_LENGTH,
    MAX_DATASET_METADATA_BYTES,
    MAX_PROJECT_METADATA_BYTES,
)
from apps.datasets.embeddings import (
    EmbeddingProvider,
    EmbeddingProviderError,
    get_embedding_provider,
)
from apps.datasets.history import record_dataset_mutation
from apps.datasets.models import (
    DATASET_ASSET_STORAGE_ALIAS,
    Dataset,
    DatasetAsset,
    DatasetMutation,
    DatasetRelationship,
    DatasetRow,
    Project,
    ProjectSection,
    record_dataset_asset_file_deletion_failure,
)
from apps.datasets.services import (
    COLUMN_SCHEMA_REFERENCE_TARGET_KEY,
    COLUMN_SCHEMA_TYPE_KEY,
    DATASET_REFERENCE_TARGET,
    PROJECT_REFERENCE_TARGET,
    CSVParseError,
    DatasetImageError,
    DatasetRowQueryError,
    apply_dataset_row_query,
    apply_dataset_rows_query,
    choice_constraints_from_schema,
    dataset_asset_key_from_ref,
    dataset_asset_ref,
    decode_image_base64,
    generated_index_column_name,
    generated_index_column_schema,
    image_columns_from_schema,
    infer_column_schema,
    invalid_choice_values_by_column,
    normalize_column_schema,
    normalize_public_page_size,
    prepare_dataset_image,
    project_section_dataset_groups,
    validate_and_canonicalize_choice_row_values,
    validate_headers,
    validate_image_row_values,
)
from apps.datasets.vector_search import (
    QdrantVectorStore,
    VectorStoreError,
    build_dataset_row_search_document,
)
from apps.datasets.vector_tasks import enqueue_vector_task
from rowset.utils import build_absolute_public_url, get_rowset_logger

API_CREATED_FILE_TYPE = "api"
MAX_API_DATASET_CREATE_ROWS = 1000
DATASET_SEARCH_MAX_LIMIT = 50
DATASET_SEARCH_RRF_K = 60
DATASET_SEARCH_LIMIT_ERRORS = (TypeError, ValueError)
PROFILE_ROW_SEARCH_SORT_RANK = "rank"
PROFILE_ROW_SEARCH_SORT_DATASET = "dataset"
PROFILE_ROW_SEARCH_SORT_ROW_NUMBER = "row_number"
PROFILE_ROW_SEARCH_SORTS = {
    PROFILE_ROW_SEARCH_SORT_RANK,
    PROFILE_ROW_SEARCH_SORT_DATASET,
    PROFILE_ROW_SEARCH_SORT_ROW_NUMBER,
}
FREE_ACCOUNT_DATASET_LIMIT = 2
FREE_ACCOUNT_ROW_LIMIT = 50
ROW_MUTATION_TYPES = (
    DatasetMutationType.ROW_CREATED,
    DatasetMutationType.ROW_UPDATED,
    DatasetMutationType.ROW_DELETED,
)
logger = get_rowset_logger(__name__)


@dataclass(frozen=True)
class _DatasetVectorSearchResult:
    hits: list[Any]
    embedding_model: str
    embedding_dimensions: int
    embedding_latency_ms: float
    vector_latency_ms: float


ColumnTypeSpec = str | dict[str, Any]
DATASET_SUMMARY_ONLY_FIELDS = (
    "key",
    "name",
    "description",
    "instructions",
    "metadata",
    "original_filename",
    "file_type",
    "status",
    "headers",
    "column_schema",
    "index_column",
    "index_generated",
    "row_count",
    "public_enabled",
    "public_key",
    "public_page_size",
    "public_password_hash",
    "project",
    "project__key",
    "project__name",
    "project__description",
    "project__archived_at",
    "section",
    "section__key",
    "section__name",
    "section__description",
    "section__archived_at",
    "created_at",
    "updated_at",
    "confirmed_at",
    "processed_at",
    "archived_at",
)
UNSET = object()


def _visible_project_dataset_count():
    return Count(
        "datasets",
        filter=Q(datasets__archived_at__isnull=True) & ~Q(datasets__status=DatasetStatus.PREVIEWED),
    )


def _visible_project_section_dataset_count():
    return Count(
        "datasets",
        filter=Q(datasets__archived_at__isnull=True) & ~Q(datasets__status=DatasetStatus.PREVIEWED),
    )


def _active_dataset_queryset(queryset):
    return queryset.filter(archived_at__isnull=True)


def _archived_dataset_queryset(queryset):
    return queryset.filter(archived_at__isnull=False)


def _active_project_queryset(queryset):
    return queryset.filter(archived_at__isnull=True)


def _active_project_section_queryset(queryset):
    return queryset.filter(archived_at__isnull=True, project__archived_at__isnull=True)


class DatasetServiceError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(message)


def _visible_profile_dataset_queryset(profile: Profile):
    return profile.datasets.filter(archived_at__isnull=True).exclude(status=DatasetStatus.PREVIEWED)


def _lock_profile_for_quota(profile: Profile) -> Profile:
    return Profile.objects.select_for_update().select_related("user").get(pk=profile.pk)


def _enforce_dataset_create_quota(profile: Profile, initial_row_count: int) -> None:
    if profile.has_active_subscription:
        return

    active_dataset_count = _visible_profile_dataset_queryset(profile).count()
    if active_dataset_count >= FREE_ACCOUNT_DATASET_LIMIT:
        raise DatasetServiceError(
            403,
            (
                "Free accounts can have at most "
                f"{FREE_ACCOUNT_DATASET_LIMIT} active datasets. Upgrade for unlimited datasets."
            ),
        )

    if initial_row_count > FREE_ACCOUNT_ROW_LIMIT:
        raise DatasetServiceError(
            403,
            (
                "Free accounts can create datasets with at most "
                f"{FREE_ACCOUNT_ROW_LIMIT} rows. Upgrade for unlimited rows."
            ),
        )


def _enforce_dataset_row_create_quota(profile: Profile, dataset: Dataset) -> None:
    if profile.has_active_subscription:
        return

    if dataset.row_count >= FREE_ACCOUNT_ROW_LIMIT:
        raise DatasetServiceError(
            403,
            (
                "Free accounts can store at most "
                f"{FREE_ACCOUNT_ROW_LIMIT} rows per dataset. Upgrade for unlimited rows."
            ),
        )


def _enqueue_dataset_vector_backfill(dataset_id: int) -> None:
    enqueue_vector_task("apps.datasets.tasks.backfill_dataset_vectors_task", dataset_id)


def _enqueue_dataset_vector_reindex(dataset_id: int) -> None:
    enqueue_vector_task("apps.datasets.tasks.reindex_dataset_vectors_task", dataset_id)


def _enqueue_dataset_row_vector_index(row_id: int) -> None:
    enqueue_vector_task("apps.datasets.tasks.index_dataset_row_vector", row_id)


def _enqueue_dataset_row_vector_delete(dataset_id: int, row_ids: list[int]) -> None:
    enqueue_vector_task("apps.datasets.tasks.delete_dataset_row_vectors", dataset_id, row_ids)


def _enqueue_dataset_vector_delete(dataset_id: int) -> None:
    enqueue_vector_task("apps.datasets.tasks.delete_dataset_vectors", dataset_id)


def _normalize_search_query(query: str | None) -> str:
    return str(query or "").strip()


def _normalize_dataset_status(status: str | None) -> str:
    normalized_status = str(status or "").strip().lower()
    if normalized_status and normalized_status not in DatasetStatus.values:
        raise DatasetServiceError(400, f"Unsupported dataset status '{normalized_status}'.")
    return normalized_status


def _normalize_updated_after(updated_after: str | date | datetime | None) -> datetime | None:
    if updated_after in (None, ""):
        return None

    if isinstance(updated_after, datetime):
        parsed = updated_after
    elif isinstance(updated_after, date):
        parsed = datetime.combine(updated_after, time.min)
    else:
        value = str(updated_after).strip()
        if not value:
            return None
        parsed = parse_datetime(value)
        if parsed is None:
            parsed_date = parse_date(value)
            parsed = datetime.combine(parsed_date, time.min) if parsed_date else None
        if parsed is None:
            raise DatasetServiceError(400, "updated_after must be an ISO date or datetime.")

    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed, UTC)
    return parsed


def _raise_if_archived(dataset: Dataset) -> None:
    if dataset.archived_at is not None:
        raise DatasetServiceError(
            409,
            "Dataset is archived. Restore it before making changes.",
        )


def _profile_has_row_mutation(profile: Profile) -> bool:
    return DatasetMutation.objects.filter(
        profile=profile,
        mutation_type__in=ROW_MUTATION_TYPES,
    ).exists()


def _track_dataset_row_mutation(
    *,
    profile: Profile,
    dataset: Dataset,
    mutation_type: str,
    agent_api_key: AgentApiKey | None,
    is_first_row_mutation: bool,
    changed_field_count: int = 0,
    deleted_count: int = 0,
    index_changed: bool = False,
    image_asset_attached: bool = False,
) -> None:
    track_activation_event(
        profile,
        ROWSET_DATASET_ROW_MUTATED,
        {
            "mutation_type": mutation_type,
            "dataset_id": dataset.id,
            "row_count_after": dataset.row_count,
            "changed_field_count": changed_field_count,
            "deleted_count": deleted_count,
            "index_changed": index_changed,
            "image_asset_attached": image_asset_attached,
            "is_first_row_mutation": is_first_row_mutation,
            **agent_api_key_tracking_properties(agent_api_key),
        },
        source_function="apps.api.services.dataset_row_mutation",
    )


def serialize_user_info(profile: Profile) -> dict:
    """Return safe user/profile details for API and MCP consumers."""
    user = profile.user
    return {
        "id": user.id,
        "email": user.email,
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "full_name": user.get_full_name(),
        "date_joined": user.date_joined,
        "profile": {
            "id": profile.id,
            "state": profile.state,
            "has_active_subscription": profile.has_active_subscription,
        },
    }


def _normalize_project_name(name: str) -> str:
    normalized_name = (name or "").strip()
    if not normalized_name:
        raise DatasetServiceError(400, "Project name is required.")
    if len(normalized_name) > 255:
        raise DatasetServiceError(400, "Project name must be 255 characters or fewer.")
    return normalized_name


def _normalize_project_description(description: str | None) -> str:
    return (description or "").strip()


def _normalize_project_section_name(name: str) -> str:
    normalized_name = (name or "").strip()
    if not normalized_name:
        raise DatasetServiceError(400, "Project section name is required.")
    if len(normalized_name) > 255:
        raise DatasetServiceError(400, "Project section name must be 255 characters or fewer.")
    return normalized_name


def _normalize_project_section_description(description: str | None) -> str:
    return (description or "").strip()


def _normalize_metadata_object(
    metadata: dict[str, Any] | None,
    *,
    label: str,
    max_bytes: int,
) -> dict[str, Any]:
    if metadata is None:
        return {}
    if not isinstance(metadata, dict):
        raise DatasetServiceError(400, f"{label} metadata must be a JSON object.")

    for key in metadata:
        if not isinstance(key, str) or not key.strip():
            raise DatasetServiceError(
                400,
                f"{label} metadata keys must be non-empty strings.",
            )

    try:
        serialized_metadata = json.dumps(
            metadata,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise DatasetServiceError(400, f"{label} metadata must be JSON serializable.") from exc

    if len(serialized_metadata.encode("utf-8")) > max_bytes:
        raise DatasetServiceError(
            400,
            f"{label} metadata must be {max_bytes} bytes or fewer.",
        )

    return metadata


def _normalize_project_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    return _normalize_metadata_object(
        metadata,
        label="Project",
        max_bytes=MAX_PROJECT_METADATA_BYTES,
    )


def _normalize_project_section_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    return _normalize_metadata_object(
        metadata,
        label="Project section",
        max_bytes=MAX_PROJECT_METADATA_BYTES,
    )


def serialize_project_reference(project: Project | None) -> dict | None:
    """Return the project fields embedded in dataset metadata."""
    if project is None or getattr(project, "archived_at", None) is not None:
        return None
    return {
        "key": str(project.key),
        "name": project.name,
        "description": project.description,
    }


def serialize_project_section_reference(section: ProjectSection | None) -> dict | None:
    """Return the section fields embedded in dataset metadata."""
    if section is None or getattr(section, "archived_at", None) is not None:
        return None
    return {
        "key": str(section.key),
        "name": section.name,
        "description": section.description,
    }


def serialize_project_summary(project: Project) -> dict:
    """Return machine-friendly project metadata without row payloads."""
    dataset_count = getattr(project, "dataset_count", None)
    if dataset_count is None:
        dataset_count = (
            _active_dataset_queryset(project.datasets)
            .exclude(status=DatasetStatus.PREVIEWED)
            .count()
        )
    return {
        "key": str(project.key),
        "name": project.name,
        "description": project.description,
        "metadata": project.metadata or {},
        "dataset_count": dataset_count,
        "created_at": project.created_at,
        "updated_at": project.updated_at,
        "archived_at": getattr(project, "archived_at", None),
    }


def serialize_project_section_summary(section: ProjectSection) -> dict:
    """Return machine-friendly project section metadata without row payloads."""
    dataset_count = getattr(section, "dataset_count", None)
    if dataset_count is None:
        dataset_count = (
            _active_dataset_queryset(section.datasets)
            .exclude(status=DatasetStatus.PREVIEWED)
            .count()
        )
    return {
        "key": str(section.key),
        "project": serialize_project_reference(section.project),
        "name": section.name,
        "description": section.description,
        "metadata": section.metadata or {},
        "dataset_count": dataset_count,
        "created_at": section.created_at,
        "updated_at": section.updated_at,
        "archived_at": getattr(section, "archived_at", None),
    }


def search_profile_projects(
    profile: Profile,
    *,
    query: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    """Return a bounded, optionally filtered page of projects owned by the profile."""
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    normalized_query = _normalize_search_query(query)
    queryset = _active_project_queryset(
        profile.projects.annotate(dataset_count=_visible_project_dataset_count())
    ).only(
        "key",
        "name",
        "description",
        "metadata",
        "created_at",
        "updated_at",
        "archived_at",
    )
    if normalized_query:
        queryset = queryset.annotate(metadata_text=Cast("metadata", TextField())).filter(
            Q(name__icontains=normalized_query)
            | Q(description__icontains=normalized_query)
            | Q(metadata_text__icontains=normalized_query)
        )
    total_count = queryset.count()
    projects = list(queryset[offset : offset + limit])
    return {
        "count": len(projects),
        "total_count": total_count,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(projects) < total_count,
        "projects": [serialize_project_summary(project) for project in projects],
    }


def serialize_profile_projects(profile: Profile, limit: int = 100, offset: int = 0) -> dict:
    """Return a bounded page of projects owned by the authenticated profile."""
    return search_profile_projects(profile, limit=limit, offset=offset)


def create_profile_project(
    profile: Profile,
    *,
    name: str,
    description: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict:
    """Create a semantic dataset group for an authenticated profile."""
    normalized_name = _normalize_project_name(name)
    normalized_description = _normalize_project_description(description)
    normalized_metadata = _normalize_project_metadata(metadata)
    if _active_project_queryset(
        Project.objects.filter(profile=profile, name__iexact=normalized_name)
    ).exists():
        raise DatasetServiceError(409, "Project name already exists.")

    try:
        project = Project.objects.create(
            profile=profile,
            name=normalized_name,
            description=normalized_description,
            metadata=normalized_metadata,
        )
    except IntegrityError as exc:
        raise DatasetServiceError(409, "Project name already exists.") from exc

    project.dataset_count = 0
    return {
        "status": "success",
        "message": "Project created.",
        "project": serialize_project_summary(project),
    }


def update_profile_project(
    profile: Profile,
    project_key: str,
    *,
    name: Any = UNSET,
    description: Any = UNSET,
) -> dict:
    """Update project metadata for an authenticated profile."""
    if name is UNSET and description is UNSET:
        raise DatasetServiceError(400, "Provide name or description to update.")

    normalized_name = _normalize_project_name(name) if name is not UNSET else UNSET
    normalized_description = (
        _normalize_project_description(description) if description is not UNSET else UNSET
    )

    with transaction.atomic():
        try:
            project = _active_project_queryset(Project.objects.select_for_update()).get(
                key=project_key, profile=profile
            )
        except (Project.DoesNotExist, ValidationError, ValueError) as exc:
            raise DatasetServiceError(404, "Project not found.") from exc

        update_fields = []
        if normalized_name is not UNSET and project.name != normalized_name:
            if (
                _active_project_queryset(
                    Project.objects.filter(profile=profile, name__iexact=normalized_name)
                )
                .exclude(pk=project.pk)
                .exists()
            ):
                raise DatasetServiceError(409, "Project name already exists.")
            project.name = normalized_name
            update_fields.append("name")

        if normalized_description is not UNSET and project.description != normalized_description:
            project.description = normalized_description
            update_fields.append("description")

        if update_fields:
            try:
                project.save(update_fields=[*update_fields, "updated_at"])
            except IntegrityError as exc:
                raise DatasetServiceError(409, "Project name already exists.") from exc

    return {
        "status": "success",
        "message": "Project updated." if update_fields else "No project changes detected.",
        "project": serialize_project_summary(project),
    }


def get_profile_project(profile: Profile, project_key: str) -> Project:
    try:
        return (
            _active_project_queryset(
                Project.objects.annotate(dataset_count=_visible_project_dataset_count())
            )
            .only(
                "key",
                "name",
                "description",
                "metadata",
                "created_at",
                "updated_at",
                "archived_at",
            )
            .get(key=project_key, profile=profile)
        )
    except (Project.DoesNotExist, ValidationError, ValueError) as exc:
        raise DatasetServiceError(404, "Project not found.") from exc


def _extract_project_identifier(project_identifier: str) -> str:
    identifier = str(project_identifier or "").strip()
    if not identifier:
        return ""

    parsed = urlparse(identifier)
    segments = [unquote(segment) for segment in parsed.path.split("/") if segment]
    for index, segment in enumerate(segments[:-1]):
        if segment == "projects":
            return segments[index + 1]

    return unquote(identifier).strip("/")


def _project_identifier_uuid(project_identifier: str) -> UUID:
    try:
        return UUID(_extract_project_identifier(project_identifier))
    except (AttributeError, TypeError, ValueError) as exc:
        raise DatasetServiceError(404, "Project not found.") from exc


def get_profile_project_reference(profile: Profile, project_key: str) -> Project:
    """Resolve a project reference cell, including archived projects."""
    try:
        return (
            Project.objects.annotate(dataset_count=_visible_project_dataset_count())
            .only(
                "key",
                "name",
                "description",
                "metadata",
                "created_at",
                "updated_at",
                "archived_at",
            )
            .get(key=_project_identifier_uuid(project_key), profile=profile)
        )
    except (Project.DoesNotExist, ValidationError, ValueError) as exc:
        raise DatasetServiceError(404, "Project not found.") from exc


def _project_section_identifier_uuid(section_identifier: str) -> UUID:
    try:
        return UUID(str(section_identifier or "").strip())
    except (AttributeError, TypeError, ValueError) as exc:
        raise DatasetServiceError(404, "Project section not found.") from exc


def get_profile_project_section(
    profile: Profile,
    project_key: str,
    section_key: str,
) -> ProjectSection:
    project = get_profile_project(profile, project_key)
    return get_profile_project_section_for_project(profile, project, section_key)


def get_profile_project_section_for_project(
    profile: Profile,
    project: Project,
    section_key: str,
) -> ProjectSection:
    try:
        return (
            _active_project_section_queryset(
                ProjectSection.objects.select_related("project").annotate(
                    dataset_count=_visible_project_section_dataset_count()
                )
            )
            .only(
                "key",
                "project",
                "project__key",
                "project__name",
                "project__description",
                "project__archived_at",
                "name",
                "description",
                "metadata",
                "created_at",
                "updated_at",
                "archived_at",
            )
            .get(
                key=_project_section_identifier_uuid(section_key),
                profile=profile,
                project=project,
            )
        )
    except (ProjectSection.DoesNotExist, ValidationError, ValueError) as exc:
        raise DatasetServiceError(404, "Project section not found.") from exc


def serialize_profile_project_sections(
    profile: Profile,
    project_key: str,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    """Return a bounded page of active sections inside one owned project."""
    project = get_profile_project(profile, project_key)
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    queryset = (
        _active_project_section_queryset(
            project.sections.select_related("project").annotate(
                dataset_count=_visible_project_section_dataset_count()
            )
        )
        .only(
            "key",
            "project",
            "project__key",
            "project__name",
            "project__description",
            "project__archived_at",
            "name",
            "description",
            "metadata",
            "created_at",
            "updated_at",
            "archived_at",
        )
        .order_by("name", "id")
    )
    total_count = queryset.count()
    sections = list(queryset[offset : offset + limit])
    return {
        "count": len(sections),
        "total_count": total_count,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(sections) < total_count,
        "sections": [serialize_project_section_summary(section) for section in sections],
    }


def create_profile_project_section(
    profile: Profile,
    project_key: str,
    *,
    name: str,
    description: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict:
    """Create a section for grouping datasets inside one authenticated project."""
    project = get_profile_project(profile, project_key)
    normalized_name = _normalize_project_section_name(name)
    normalized_description = _normalize_project_section_description(description)
    normalized_metadata = _normalize_project_section_metadata(metadata)
    if _active_project_section_queryset(
        ProjectSection.objects.filter(project=project, name__iexact=normalized_name)
    ).exists():
        raise DatasetServiceError(409, "Project section name already exists.")

    try:
        section = ProjectSection.objects.create(
            profile=profile,
            project=project,
            name=normalized_name,
            description=normalized_description,
            metadata=normalized_metadata,
        )
    except IntegrityError as exc:
        raise DatasetServiceError(409, "Project section name already exists.") from exc

    section.dataset_count = 0
    return {
        "status": "success",
        "message": "Project section created.",
        "section": serialize_project_section_summary(section),
    }


def update_profile_project_section(
    profile: Profile,
    project_key: str,
    section_key: str,
    *,
    name: Any = UNSET,
    description: Any = UNSET,
) -> dict:
    """Update an active section inside one authenticated project."""
    if name is UNSET and description is UNSET:
        raise DatasetServiceError(400, "Provide name or description to update.")

    normalized_name = _normalize_project_section_name(name) if name is not UNSET else UNSET
    normalized_description = (
        _normalize_project_section_description(description) if description is not UNSET else UNSET
    )

    with transaction.atomic():
        project = get_profile_project(profile, project_key)
        section = get_profile_project_section_for_project(profile, project, section_key)

        update_fields = []
        if normalized_name is not UNSET and section.name != normalized_name:
            if (
                _active_project_section_queryset(
                    ProjectSection.objects.filter(
                        project=project,
                        name__iexact=normalized_name,
                    )
                )
                .exclude(pk=section.pk)
                .exists()
            ):
                raise DatasetServiceError(409, "Project section name already exists.")
            section.name = normalized_name
            update_fields.append("name")

        if normalized_description is not UNSET and section.description != normalized_description:
            section.description = normalized_description
            update_fields.append("description")

        if update_fields:
            try:
                section.save(update_fields=[*update_fields, "updated_at"])
            except IntegrityError as exc:
                raise DatasetServiceError(409, "Project section name already exists.") from exc

    return {
        "status": "success",
        "message": "Project section updated."
        if update_fields
        else "No project section changes detected.",
        "section": serialize_project_section_summary(section),
    }


def archive_profile_project_section(
    profile: Profile,
    project_key: str,
    section_key: str,
) -> dict:
    """Archive a project section and leave its datasets in the parent project."""
    with transaction.atomic():
        project = get_profile_project(profile, project_key)
        section = get_profile_project_section_for_project(profile, project, section_key)

        message = "Project section was already archived."
        if section.archived_at is None:
            archived_at = timezone.now()
            section.archived_at = archived_at
            section.save(update_fields=["archived_at", "updated_at"])
            Dataset.objects.filter(profile=profile, project=project, section=section).update(
                section=None,
                updated_at=archived_at,
            )
            section.dataset_count = 0
            message = "Project section archived."

    return {
        "status": "success",
        "message": message,
        "section": serialize_project_section_summary(section),
    }


def _resolve_project_section_assignment(
    profile: Profile,
    project: Project | None,
    section_key: str | None,
) -> ProjectSection | None:
    normalized_section_key = str(section_key or "").strip()
    if not normalized_section_key:
        return None
    if project is None:
        raise DatasetServiceError(404, "Project section not found.")
    return get_profile_project_section_for_project(profile, project, normalized_section_key)


def update_profile_project_metadata(
    profile: Profile,
    project_key: str,
    *,
    metadata=UNSET,
) -> dict:
    """Replace arbitrary JSON metadata on a project owned by the authenticated profile."""
    with transaction.atomic():
        try:
            project = _active_project_queryset(Project.objects.select_for_update()).get(
                key=project_key,
                profile=profile,
            )
        except (Project.DoesNotExist, ValidationError, ValueError) as exc:
            raise DatasetServiceError(404, "Project not found.") from exc

        changed = False
        if metadata is not UNSET:
            next_metadata = _normalize_project_metadata(metadata)
            if project.metadata != next_metadata:
                project.metadata = next_metadata
                changed = True

        message = "No project metadata changes detected."
        if changed:
            project.save(update_fields=["metadata", "updated_at"])
            message = "Project metadata updated."

    return {
        "status": "success",
        "message": message,
        "project": serialize_project_summary(project),
    }


def archive_profile_project(profile: Profile, project_key: str) -> dict:
    """Archive an owned project without deleting or archiving its datasets."""
    with transaction.atomic():
        try:
            project = Project.objects.select_for_update().get(key=project_key, profile=profile)
        except (Project.DoesNotExist, ValidationError, ValueError) as exc:
            raise DatasetServiceError(404, "Project not found.") from exc

        message = "Project was already archived."
        if project.archived_at is None:
            project.archived_at = timezone.now()
            project.save(update_fields=["archived_at", "updated_at"])
            message = "Project archived."

    return {
        "status": "success",
        "message": message,
        "project": serialize_project_summary(project),
    }


def serialize_profile_project_detail(
    profile: Profile,
    project_key: str,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    """Return one project plus a bounded page of datasets assigned to it."""
    project = get_profile_project(profile, project_key)
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    queryset = _dataset_summary_queryset(
        _active_dataset_queryset(project.datasets).exclude(status=DatasetStatus.PREVIEWED)
    )
    sections = list(
        _active_project_section_queryset(
            project.sections.select_related("project").annotate(
                dataset_count=_visible_project_section_dataset_count()
            )
        )
        .only(
            "key",
            "project",
            "project__key",
            "project__name",
            "project__description",
            "project__archived_at",
            "name",
            "description",
            "metadata",
            "created_at",
            "updated_at",
            "archived_at",
        )
        .order_by("name", "id")
    )
    total_count = project.dataset_count
    datasets = list(queryset[offset : offset + limit])
    active_section_ids = [section.id for section in sections]
    unsectioned_dataset_count = queryset.exclude(section_id__in=active_section_ids).count()
    dataset_groups = _project_dataset_groups(
        sections,
        datasets,
        unsectioned_dataset_count=unsectioned_dataset_count,
    )
    return {
        "status": "success",
        "message": "Project retrieved.",
        "project": serialize_project_summary(project),
        "sections": [serialize_project_section_summary(section) for section in sections],
        "dataset_groups": dataset_groups,
        "datasets": {
            "count": len(datasets),
            "total_count": total_count,
            "limit": limit,
            "offset": offset,
            "has_more": offset + len(datasets) < total_count,
            "datasets": [serialize_dataset_summary(dataset) for dataset in datasets],
        },
    }


def _dataset_group_items_payload(datasets: list[Dataset], total_count: int) -> dict:
    return {
        "count": len(datasets),
        "total_count": total_count,
        "datasets": [serialize_dataset_summary(dataset) for dataset in datasets],
    }


def _project_dataset_groups(
    sections: list[ProjectSection],
    datasets: list[Dataset],
    *,
    unsectioned_dataset_count: int | None = None,
) -> list[dict]:
    groups = project_section_dataset_groups(
        sections,
        datasets,
        unsectioned_dataset_count=unsectioned_dataset_count,
    )
    return [
        {
            "label": group["label"],
            "section": serialize_project_section_reference(group["section"]),
            "dataset_count": group["dataset_count"],
            "datasets": _dataset_group_items_payload(group["datasets"], group["dataset_count"]),
        }
        for group in groups
    ]


def serialize_dataset_summary(dataset: Dataset) -> dict:
    """Return machine-friendly dataset metadata without row payloads."""
    public_url = (
        build_absolute_public_url(dataset.get_public_url()) if dataset.public_enabled else None
    )
    return {
        "key": str(dataset.key),
        "name": dataset.name,
        "description": dataset.description,
        "instructions": dataset.instructions,
        "metadata": dataset.metadata or {},
        "project": serialize_project_reference(getattr(dataset, "project", None)),
        "section": serialize_project_section_reference(getattr(dataset, "section", None)),
        "original_filename": dataset.original_filename,
        "file_type": dataset.file_type,
        "status": dataset.status,
        "headers": dataset.headers,
        "column_schema": normalize_column_schema(
            dataset.headers,
            dataset.column_schema or {},
        ),
        "index_column": dataset.index_column,
        "index_generated": dataset.index_generated,
        "row_count": dataset.row_count,
        "public_enabled": dataset.public_enabled,
        "public_key": str(dataset.public_key),
        "public_url": public_url,
        "public_page_size": dataset.public_page_size,
        "public_password_protected": dataset.is_public_password_protected,
        "created_at": dataset.created_at,
        "updated_at": dataset.updated_at,
        "confirmed_at": dataset.confirmed_at,
        "processed_at": dataset.processed_at,
        "archived_at": dataset.archived_at,
    }


def _serialize_relationships_from_manager(manager) -> list[dict]:
    if manager is None:
        return []
    try:
        relationships = manager.select_related("source_dataset", "target_dataset").order_by(
            "name",
            "id",
        )
    except AttributeError:
        return []
    return [serialize_dataset_relationship(relationship) for relationship in relationships]


def serialize_dataset_relationship_context(dataset: Dataset) -> dict:
    """Return outgoing and incoming relationship metadata for one dataset."""
    return {
        "outgoing": _serialize_relationships_from_manager(
            getattr(dataset, "outgoing_relationships", None)
        ),
        "incoming": _serialize_relationships_from_manager(
            getattr(dataset, "incoming_relationships", None)
        ),
    }


def serialize_dataset_reference(dataset: Dataset) -> dict:
    """Return compact metadata for a dataset referenced by a cell value."""
    return {
        "key": str(dataset.key),
        "name": dataset.name,
        "project": serialize_project_reference(getattr(dataset, "project", None)),
        "section": serialize_project_section_reference(getattr(dataset, "section", None)),
        "status": dataset.status,
        "headers": dataset.headers,
        "index_column": dataset.index_column,
        "row_count": dataset.row_count,
        "public_enabled": dataset.public_enabled,
        "created_at": dataset.created_at,
        "updated_at": dataset.updated_at,
        "archived_at": dataset.archived_at,
    }


def _reference_columns(
    headers: list[str],
    column_schema: dict | None,
    target: str,
) -> list[str]:
    normalized_schema = normalize_column_schema(headers, column_schema)
    return [
        header
        for header in headers
        if normalized_schema[header].get(COLUMN_SCHEMA_TYPE_KEY) == DatasetColumnType.REFERENCE
        and normalized_schema[header].get(COLUMN_SCHEMA_REFERENCE_TARGET_KEY) == target
    ]


def _dataset_reference_columns(headers: list[str], column_schema: dict | None) -> list[str]:
    return _reference_columns(headers, column_schema, DATASET_REFERENCE_TARGET)


def _project_reference_columns(headers: list[str], column_schema: dict | None) -> list[str]:
    return _reference_columns(headers, column_schema, PROJECT_REFERENCE_TARGET)


def _reference_values_by_column(
    dataset: Dataset,
    reference_columns: list[str],
) -> dict[str, set[str]]:
    values_by_column: dict[str, set[str]] = {column: set() for column in reference_columns}
    row_data_queryset = dataset.rows.order_by("row_number", "id").values_list("data", flat=True)
    row_data_items = row_data_queryset if dataset.row_count else dataset.preview_rows
    for row_data in row_data_items:
        if not isinstance(row_data, dict):
            continue
        for column in reference_columns:
            raw_value = str(row_data.get(column, "") or "").strip()
            if raw_value:
                values_by_column[column].add(raw_value)
    return values_by_column


def serialize_dataset_reference_context(dataset: Dataset) -> dict[str, dict[str, dict]]:
    """Return referenced dataset metadata grouped by source column and target key."""
    reference_columns = _dataset_reference_columns(dataset.headers, dataset.column_schema)
    if not reference_columns:
        return {}

    values_by_column = _reference_values_by_column(dataset, reference_columns)
    identifiers_by_value: dict[str, UUID] = {}
    for raw_value in {value for values in values_by_column.values() for value in values}:
        try:
            identifiers_by_value[raw_value] = _dataset_identifier_uuid(raw_value)
        except DatasetServiceError:
            continue

    if not identifiers_by_value:
        return {}

    identifiers = set(identifiers_by_value.values())
    target_datasets = _dataset_summary_queryset(
        Dataset.objects.filter(profile=dataset.profile)
    ).filter(
        Q(key__in=identifiers) | Q(public_key__in=identifiers),
    )
    datasets_by_key = {target_dataset.key: target_dataset for target_dataset in target_datasets}
    datasets_by_public_key = {
        target_dataset.public_key: target_dataset
        for target_dataset in target_datasets
        if target_dataset.public_key
    }

    referenced: dict[str, dict[str, dict]] = {}
    for column, raw_values in values_by_column.items():
        targets: dict[str, dict] = {}
        for raw_value in raw_values:
            identifier = identifiers_by_value.get(raw_value)
            if identifier is None:
                continue
            target_dataset = datasets_by_key.get(identifier) or datasets_by_public_key.get(
                identifier
            )
            if target_dataset is None:
                continue
            targets[str(target_dataset.key)] = serialize_dataset_reference(target_dataset)
        if targets:
            referenced[column] = targets

    return referenced


def serialize_project_reference_context(dataset: Dataset) -> dict[str, dict[str, dict]]:
    """Return referenced project metadata grouped by source column and target key."""
    reference_columns = _project_reference_columns(dataset.headers, dataset.column_schema)
    if not reference_columns:
        return {}

    values_by_column = _reference_values_by_column(dataset, reference_columns)
    project_keys_by_value: dict[str, UUID] = {}
    for raw_value in {value for values in values_by_column.values() for value in values}:
        try:
            project_keys_by_value[raw_value] = _project_identifier_uuid(raw_value)
        except DatasetServiceError:
            continue

    if not project_keys_by_value:
        return {}

    target_projects = (
        Project.objects.annotate(dataset_count=_visible_project_dataset_count())
        .only(
            "key",
            "name",
            "description",
            "metadata",
            "created_at",
            "updated_at",
            "archived_at",
        )
        .filter(profile=dataset.profile, key__in=set(project_keys_by_value.values()))
    )
    projects_by_key = {target_project.key: target_project for target_project in target_projects}

    referenced: dict[str, dict[str, dict]] = {}
    for column, raw_values in values_by_column.items():
        targets: dict[str, dict] = {}
        for raw_value in raw_values:
            project_key = project_keys_by_value.get(raw_value)
            if project_key is None:
                continue
            target_project = projects_by_key.get(project_key)
            if target_project is None:
                continue
            targets[str(target_project.key)] = serialize_project_summary(target_project)
        if targets:
            referenced[column] = targets

    return referenced


def serialize_dataset_detail(dataset: Dataset) -> dict:
    """Return one dataset with relationship context, without row payloads."""
    payload = serialize_dataset_summary(dataset)
    payload["relationships"] = serialize_dataset_relationship_context(dataset)
    payload["dataset_references"] = serialize_dataset_reference_context(dataset)
    payload["project_references"] = serialize_project_reference_context(dataset)
    return payload


def _dataset_summary_queryset(queryset):
    return queryset.select_related("project", "section").only(*DATASET_SUMMARY_ONLY_FIELDS)


def search_profile_datasets(  # noqa: C901
    profile: Profile,
    *,
    query: str | None = None,
    project_key: str | None = None,
    section_key: str | None = None,
    header_contains: str | None = None,
    status: str | None = None,
    updated_after: str | date | datetime | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    """
    Return a bounded, optionally filtered page of datasets owned by the profile.

    Query text matches dataset name, original filename, and assigned project/section metadata.
    Ungrouped datasets match only on dataset fields because they have no grouping metadata.
    """
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    normalized_query = _normalize_search_query(query)
    normalized_project_key = str(project_key or "").strip()
    normalized_section_key = str(section_key or "").strip()
    normalized_header = str(header_contains or "").strip()
    normalized_status = _normalize_dataset_status(status)
    normalized_updated_after = _normalize_updated_after(updated_after)

    queryset = _dataset_summary_queryset(_active_dataset_queryset(profile.datasets))
    if normalized_query:
        queryset = queryset.filter(
            Q(name__icontains=normalized_query)
            | Q(description__icontains=normalized_query)
            | Q(instructions__icontains=normalized_query)
            | Q(original_filename__icontains=normalized_query)
            | Q(
                project__archived_at__isnull=True,
                project__name__icontains=normalized_query,
            )
            | Q(
                project__archived_at__isnull=True,
                project__description__icontains=normalized_query,
            )
            | Q(
                section__archived_at__isnull=True,
                section__name__icontains=normalized_query,
            )
            | Q(
                section__archived_at__isnull=True,
                section__description__icontains=normalized_query,
            )
        )
    if normalized_project_key:
        try:
            project_key_uuid = UUID(normalized_project_key)
        except ValueError as exc:
            raise DatasetServiceError(400, "project_key must be a valid UUID.") from exc
        else:
            queryset = queryset.filter(
                project__key=project_key_uuid,
                project__archived_at__isnull=True,
            )
    if normalized_section_key:
        try:
            section_key_uuid = UUID(normalized_section_key)
        except ValueError as exc:
            raise DatasetServiceError(400, "section_key must be a valid UUID.") from exc
        else:
            queryset = queryset.filter(
                section__key=section_key_uuid,
                section__archived_at__isnull=True,
                section__project__archived_at__isnull=True,
            )
    if normalized_status:
        queryset = queryset.filter(status=normalized_status)
    if normalized_updated_after is not None:
        queryset = queryset.filter(updated_at__gte=normalized_updated_after)
    if normalized_header:
        queryset = queryset.filter(headers__contains=[normalized_header])

    total_count = queryset.count()
    page = list(queryset[offset : offset + limit])

    return {
        "count": len(page),
        "total_count": total_count,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(page) < total_count,
        "datasets": [serialize_dataset_summary(dataset) for dataset in page],
    }


def serialize_profile_datasets(profile: Profile, limit: int = 100, offset: int = 0) -> dict:
    """Return a bounded page of datasets owned by the authenticated profile."""
    return search_profile_datasets(profile, limit=limit, offset=offset)


def serialize_profile_archived_datasets(
    profile: Profile,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    """Return a bounded page of archived datasets owned by the authenticated profile."""
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    queryset = _dataset_summary_queryset(
        _archived_dataset_queryset(profile.datasets).exclude(status=DatasetStatus.PREVIEWED)
    )
    total_count = queryset.count()
    page = list(queryset[offset : offset + limit])

    return {
        "count": len(page),
        "total_count": total_count,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(page) < total_count,
        "datasets": [serialize_dataset_summary(dataset) for dataset in page],
    }


def _extract_dataset_identifier(dataset_identifier: str) -> str:
    identifier = str(dataset_identifier or "").strip()
    if not identifier:
        return ""

    parsed = urlparse(identifier)
    segments = [unquote(segment) for segment in parsed.path.split("/") if segment]
    for index, segment in enumerate(segments[:-1]):
        if segment == "datasets":
            return segments[index + 1]

    return unquote(identifier).strip("/")


def _dataset_identifier_uuid(dataset_identifier: str) -> UUID:
    try:
        return UUID(_extract_dataset_identifier(dataset_identifier))
    except (AttributeError, TypeError, ValueError) as exc:
        raise DatasetServiceError(404, "Dataset not found.") from exc


def _get_profile_dataset_from_queryset(
    queryset,
    profile: Profile,
    dataset_identifier: str,
) -> Dataset:
    identifier = _dataset_identifier_uuid(dataset_identifier)
    # Keep the canonical private key path first for existing clients; public keys and
    # pasted Rowset URLs intentionally resolve through a scoped fallback.
    lookup_errors = (Dataset.DoesNotExist, ValidationError, ValueError)
    try:
        return queryset.get(key=identifier, profile=profile)
    except lookup_errors:
        pass

    try:
        return queryset.get(public_key=identifier, profile=profile)
    except lookup_errors as exc:
        raise DatasetServiceError(404, "Dataset not found.") from exc


def get_profile_dataset(profile: Profile, dataset_key: str) -> Dataset:
    return _get_profile_dataset_from_queryset(
        Dataset.objects.select_related("project", "section"),
        profile,
        dataset_key,
    )


def get_ready_profile_dataset(profile: Profile, dataset_key: str) -> Dataset:
    dataset = get_profile_dataset(profile, dataset_key)
    _raise_if_archived(dataset)
    if dataset.status != DatasetStatus.READY:
        raise DatasetServiceError(
            409,
            "Dataset is not ready yet. Confirm and wait for import first.",
        )
    return dataset


def get_ready_profile_dataset_for_update(profile: Profile, dataset_key: str) -> Dataset:
    dataset = _get_profile_dataset_from_queryset(
        Dataset.objects.select_for_update(),
        profile,
        dataset_key,
    )
    _raise_if_archived(dataset)
    if dataset.status != DatasetStatus.READY:
        raise DatasetServiceError(
            409,
            "Dataset is not ready yet. Confirm and wait for import first.",
        )
    return dataset


def serialize_dataset_relationship(relationship: DatasetRelationship) -> dict:
    source_dataset = relationship.source_dataset
    target_dataset = relationship.target_dataset
    return {
        "key": str(relationship.key),
        "name": relationship.name,
        "source_dataset": {
            "key": str(source_dataset.key),
            "name": source_dataset.name,
            "index_column": source_dataset.index_column,
        },
        "source_column": relationship.source_column,
        "target_dataset": {
            "key": str(target_dataset.key),
            "name": target_dataset.name,
            "index_column": target_dataset.index_column,
        },
        "target_index_column": relationship.target_index_column,
        "enforce_integrity": relationship.enforce_integrity,
        "created_at": relationship.created_at,
        "updated_at": relationship.updated_at,
    }


def _relationship_identifier_uuid(relationship_key: str) -> UUID:
    try:
        return UUID(str(relationship_key or "").strip())
    except (AttributeError, TypeError, ValueError) as exc:
        raise DatasetServiceError(400, "Invalid relationship key.") from exc


def _normalize_relationship_name(
    name: str | None,
    *,
    source_column: str,
    target_dataset: Dataset,
) -> str:
    normalized_name = str(name or "").strip()
    if not normalized_name:
        normalized_name = f"{source_column} to {target_dataset.name}"
    if len(normalized_name) > 120:
        raise DatasetServiceError(400, "Relationship name must be 120 characters or fewer.")
    return normalized_name


def _normalize_relationship_source_column(dataset: Dataset, source_column: str) -> str:
    normalized_column = str(source_column or "").strip()
    if not normalized_column:
        raise DatasetServiceError(400, "Relationship source_column is required.")
    if normalized_column not in dataset.headers:
        raise DatasetServiceError(
            400,
            f"Relationship source_column '{normalized_column}' must match a dataset header.",
        )
    return normalized_column


def _relationship_cell_value(row_data: dict, column: str) -> str:
    return str(row_data.get(column, "") or "").strip()


def _relationship_source_rows_with_values(relationship: DatasetRelationship):
    return (
        relationship.source_dataset.rows.annotate(
            rowset_relationship_value=Trim(KeyTextTransform(relationship.source_column, "data"))
        )
        .filter(rowset_relationship_value__isnull=False)
        .exclude(rowset_relationship_value="")
    )


def _validate_existing_relationship_values(relationship: DatasetRelationship) -> None:
    matching_target_rows = relationship.target_dataset.rows.filter(
        index_value=OuterRef("rowset_relationship_value")
    )
    missing_count = (
        _relationship_source_rows_with_values(relationship)
        .annotate(rowset_target_exists=Exists(matching_target_rows))
        .filter(rowset_target_exists=False)
        .count()
    )

    if missing_count:
        plural = "values" if missing_count != 1 else "value"
        raise DatasetServiceError(
            400,
            f"Column '{relationship.source_column}' contains {missing_count} {plural} "
            f"without a matching row in target dataset '{relationship.target_dataset.name}'.",
        )


def _enforced_outgoing_relationships(dataset: Dataset):
    return dataset.outgoing_relationships.filter(enforce_integrity=True).select_related(
        "target_dataset"
    )


def _validate_relationship_row_data(
    dataset: Dataset,
    row_data: dict,
    *,
    columns: list[str] | set[str] | None = None,
) -> None:
    selected_columns = set(columns) if columns is not None else None
    for relationship in _enforced_outgoing_relationships(dataset):
        if selected_columns is not None and relationship.source_column not in selected_columns:
            continue
        value = _relationship_cell_value(row_data, relationship.source_column)
        if not value:
            continue
        if relationship.target_dataset.archived_at is not None:
            raise DatasetServiceError(
                409,
                f"Relationship '{relationship.name}' targets an archived dataset.",
            )
        if not relationship.target_dataset.rows.filter(index_value=value).exists():
            raise DatasetServiceError(
                400,
                f"Column '{relationship.source_column}' references a missing row in "
                f"target dataset '{relationship.target_dataset.name}'.",
            )


def _raise_if_target_row_is_referenced(dataset: Dataset, index_value: str) -> None:
    normalized_index_value = str(index_value or "").strip()
    if not normalized_index_value:
        return

    incoming_relationships = dataset.incoming_relationships.filter(
        enforce_integrity=True
    ).select_related("source_dataset")
    for relationship in incoming_relationships:
        if (
            _relationship_source_rows_with_values(relationship)
            .filter(rowset_relationship_value=normalized_index_value)
            .exists()
        ):
            raise DatasetServiceError(
                409,
                f"Row is referenced by relationship '{relationship.name}' from "
                f"dataset '{relationship.source_dataset.name}'.",
            )


def create_profile_dataset_relationship(
    profile: Profile,
    dataset_key: str,
    *,
    source_column: str,
    target_dataset_key: str,
    name: str | None = None,
    enforce_integrity: bool = True,
    agent_api_key: AgentApiKey | None = None,
) -> dict:
    """Create one lightweight foreign-key-style relationship for a source dataset."""
    with transaction.atomic():
        source_dataset = get_ready_profile_dataset_for_update(profile, dataset_key)
        target_dataset = get_ready_profile_dataset(profile, target_dataset_key)
        if source_dataset.pk == target_dataset.pk:
            raise DatasetServiceError(
                400,
                "Relationship target dataset must be different from the source dataset.",
            )

        normalized_source_column = _normalize_relationship_source_column(
            source_dataset,
            source_column,
        )
        normalized_name = _normalize_relationship_name(
            name,
            source_column=normalized_source_column,
            target_dataset=target_dataset,
        )
        relationship = DatasetRelationship(
            profile=profile,
            source_dataset=source_dataset,
            target_dataset=target_dataset,
            name=normalized_name,
            source_column=normalized_source_column,
            target_index_column=target_dataset.index_column,
            enforce_integrity=bool(enforce_integrity),
        )
        if relationship.enforce_integrity:
            _validate_existing_relationship_values(relationship)

        try:
            relationship.save()
        except IntegrityError as exc:
            raise DatasetServiceError(
                409,
                "Relationship already exists for this dataset.",
            ) from exc

        source_dataset.updated_by_agent_api_key = agent_api_key
        source_dataset.save(update_fields=["updated_by_agent_api_key", "updated_at"])
        record_dataset_mutation(
            source_dataset,
            DatasetMutationType.RELATIONSHIP_CREATED,
            "Dataset relationship created.",
            agent_api_key=agent_api_key,
            target_type="relationship",
            target_identifier=str(relationship.key),
            metadata={
                "relationship_key": str(relationship.key),
                "relationship_name": relationship.name,
                "source_column": relationship.source_column,
                "target_dataset_key": str(target_dataset.key),
                "target_index_column": relationship.target_index_column,
                "enforce_integrity": relationship.enforce_integrity,
            },
        )

    return {
        "status": "success",
        "message": "Relationship created.",
        "relationship": serialize_dataset_relationship(relationship),
    }


def list_profile_dataset_relationships(profile: Profile, dataset_key: str) -> dict:
    source_dataset = get_ready_profile_dataset(profile, dataset_key)
    relationships = source_dataset.outgoing_relationships.select_related(
        "source_dataset", "target_dataset"
    ).order_by("name", "id")
    return {
        "dataset": str(source_dataset.key),
        "relationships": [
            serialize_dataset_relationship(relationship) for relationship in relationships
        ],
    }


def _get_profile_dataset_relationship(
    profile: Profile,
    dataset: Dataset,
    relationship_key: str,
):
    relationship_uuid = _relationship_identifier_uuid(relationship_key)
    try:
        return (
            dataset.outgoing_relationships.select_related("source_dataset", "target_dataset")
            .filter(profile=profile)
            .get(key=relationship_uuid)
        )
    except DatasetRelationship.DoesNotExist as exc:
        raise DatasetServiceError(404, "Relationship not found.") from exc


def delete_profile_dataset_relationship(
    profile: Profile,
    dataset_key: str,
    relationship_key: str,
    agent_api_key: AgentApiKey | None = None,
) -> dict:
    with transaction.atomic():
        source_dataset = get_ready_profile_dataset_for_update(profile, dataset_key)
        relationship = _get_profile_dataset_relationship(
            profile,
            source_dataset,
            relationship_key,
        )
        relationship_payload = serialize_dataset_relationship(relationship)
        relationship.delete()
        source_dataset.updated_by_agent_api_key = agent_api_key
        source_dataset.save(update_fields=["updated_by_agent_api_key", "updated_at"])
        record_dataset_mutation(
            source_dataset,
            DatasetMutationType.RELATIONSHIP_DELETED,
            "Dataset relationship deleted.",
            agent_api_key=agent_api_key,
            target_type="relationship",
            target_identifier=relationship_payload["key"],
            metadata={
                "relationship_key": relationship_payload["key"],
                "relationship_name": relationship_payload["name"],
                "source_column": relationship_payload["source_column"],
                "target_dataset_key": relationship_payload["target_dataset"]["key"],
                "target_index_column": relationship_payload["target_index_column"],
                "enforce_integrity": relationship_payload["enforce_integrity"],
            },
        )
    return {
        "status": "success",
        "message": "Relationship deleted.",
        "relationship": relationship_payload,
    }


def resolve_profile_dataset_relationship(
    profile: Profile,
    dataset_key: str,
    relationship_key: str,
    *,
    source_index_value: str,
) -> dict:
    source_dataset = get_ready_profile_dataset(profile, dataset_key)
    relationship = _get_profile_dataset_relationship(profile, source_dataset, relationship_key)
    if relationship.target_dataset.archived_at is not None:
        raise DatasetServiceError(409, "Relationship target dataset is archived.")
    if relationship.target_dataset.status != DatasetStatus.READY:
        raise DatasetServiceError(409, "Relationship target dataset is not ready.")

    normalized_source_index = str(source_index_value or "").strip()
    if not normalized_source_index:
        raise DatasetServiceError(400, "source_index_value is required.")
    try:
        source_row = source_dataset.rows.prefetch_related("assets").get(
            index_value=normalized_source_index
        )
    except DatasetRow.DoesNotExist as exc:
        raise DatasetServiceError(404, "Source row not found.") from exc

    target_index_value = _relationship_cell_value(source_row.data or {}, relationship.source_column)
    if not target_index_value:
        return {
            "status": "success",
            "message": "Relationship value is blank.",
            "relationship": serialize_dataset_relationship(relationship),
            "source_row": serialize_dataset_row(source_row, dataset=source_dataset),
            "target_index_value": "",
            "target_row": None,
        }
    try:
        target_row = relationship.target_dataset.rows.prefetch_related("assets").get(
            index_value=target_index_value
        )
    except DatasetRow.DoesNotExist as exc:
        if not relationship.enforce_integrity:
            return {
                "status": "success",
                "message": "Related row not found.",
                "relationship": serialize_dataset_relationship(relationship),
                "source_row": serialize_dataset_row(source_row, dataset=source_dataset),
                "target_index_value": target_index_value,
                "target_row": None,
            }
        raise DatasetServiceError(404, "Related row not found.") from exc
    return {
        "status": "success",
        "message": "Related row resolved.",
        "relationship": serialize_dataset_relationship(relationship),
        "source_row": serialize_dataset_row(source_row, dataset=source_dataset),
        "target_index_value": target_index_value,
        "target_row": serialize_dataset_row(target_row, dataset=relationship.target_dataset),
    }


def _stringify_cell(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _row_field_changes(
    current_data: dict,
    patch_data: dict,
    candidate_fields: list[str],
) -> list[dict[str, str]]:
    field_changes = []
    for field in candidate_fields:
        before_value = _stringify_cell(current_data.get(field, ""))
        after_value = _stringify_cell(patch_data.get(field, ""))
        if before_value == after_value:
            continue

        field_changes.append(
            {
                "field": field,
                "before": before_value,
                "after": after_value,
            }
        )
    return field_changes


def _normalize_dataset_name(name: str) -> str:
    normalized_name = (name or "").strip()
    if not normalized_name:
        raise DatasetServiceError(400, "Dataset name is required.")
    if len(normalized_name) > 255:
        raise DatasetServiceError(400, "Dataset name must be 255 characters or fewer.")
    return normalized_name


def _normalize_dataset_description(description: str | None) -> str:
    normalized_description = (description or "").strip()
    if len(normalized_description) > MAX_DATASET_DESCRIPTION_LENGTH:
        raise DatasetServiceError(
            400,
            f"Dataset description must be {MAX_DATASET_DESCRIPTION_LENGTH} characters or fewer.",
        )
    return normalized_description


def _normalize_dataset_instructions(instructions: str | None) -> str:
    normalized_instructions = (instructions or "").strip()
    if len(normalized_instructions) > MAX_DATASET_INSTRUCTIONS_LENGTH:
        raise DatasetServiceError(
            400,
            f"Dataset instructions must be {MAX_DATASET_INSTRUCTIONS_LENGTH} characters or fewer.",
        )
    return normalized_instructions


def _normalize_dataset_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    return _normalize_metadata_object(
        metadata,
        label="Dataset",
        max_bytes=MAX_DATASET_METADATA_BYTES,
    )


def _normalize_create_rows(rows: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    if rows and len(rows) > MAX_API_DATASET_CREATE_ROWS:
        raise DatasetServiceError(
            400,
            f"Datasets can be created with at most {MAX_API_DATASET_CREATE_ROWS} initial rows.",
        )

    normalized_rows = []
    for row in rows or []:
        normalized_row = {}
        for key, value in row.items():
            header = str(key or "").strip()
            if not header:
                raise DatasetServiceError(400, "Dataset row keys must be non-empty strings.")
            if header in normalized_row:
                raise DatasetServiceError(
                    400,
                    f"Dataset row contains duplicate normalized header '{header}'.",
                )
            normalized_row[header] = _stringify_cell(value)
        normalized_rows.append(normalized_row)
    return normalized_rows


def _headers_from_rows(rows: list[dict[str, str]]) -> list[str]:
    headers = []
    seen: set[str] = set()
    for row in rows:
        for header in row:
            if header not in seen:
                headers.append(header)
                seen.add(header)
    return headers


def _normalize_create_headers(
    headers: list[str] | None,
    rows: list[dict[str, str]],
) -> list[str]:
    if headers is None:
        headers = _headers_from_rows(rows)

    if not headers:
        raise DatasetServiceError(400, "Provide at least one dataset header or row.")

    try:
        return validate_headers([str(header or "").strip() for header in headers], "Dataset")
    except CSVParseError as exc:
        raise DatasetServiceError(400, str(exc)) from exc


def _validate_rows_match_headers(rows: list[dict[str, str]], headers: list[str]) -> None:
    header_set = set(headers)
    extra_headers = sorted({header for row in rows for header in row if header not in header_set})
    if extra_headers:
        joined = ", ".join(extra_headers)
        raise DatasetServiceError(400, f"Rows contain fields not listed in headers: {joined}.")


def _validate_choice_row_data(
    headers: list[str],
    column_schema: dict,
    row_data: dict,
    *,
    columns: list[str] | set[str] | None = None,
    choice_constraints: dict[str, list[str]] | None = None,
) -> None:
    constraints = choice_constraints
    if constraints is None:
        constraints = choice_constraints_from_schema(
            headers,
            column_schema,
            normalized=True,
        )
    try:
        validate_and_canonicalize_choice_row_values(
            headers,
            column_schema,
            row_data,
            columns=columns,
            choice_constraints=constraints,
        )
    except CSVParseError as exc:
        raise DatasetServiceError(400, str(exc)) from exc


def _validate_image_row_data(
    headers: list[str],
    column_schema: dict,
    row_data: dict,
    *,
    columns: list[str] | set[str] | None = None,
    allow_asset_refs: bool = False,
) -> None:
    try:
        validate_image_row_values(
            headers,
            column_schema,
            row_data,
            columns=columns,
            allow_asset_refs=allow_asset_refs,
        )
    except CSVParseError as exc:
        raise DatasetServiceError(400, str(exc)) from exc


def _validate_choice_rows(
    headers: list[str],
    column_schema: dict,
    rows: list[dict[str, str]],
) -> None:
    choice_constraints = choice_constraints_from_schema(
        headers,
        column_schema,
        normalized=True,
    )
    for row_data in rows:
        _validate_choice_row_data(
            headers,
            column_schema,
            row_data,
            choice_constraints=choice_constraints,
        )


def _validate_image_rows(
    headers: list[str],
    column_schema: dict,
    rows: list[dict[str, str]],
) -> None:
    for row_data in rows:
        _validate_image_row_data(headers, column_schema, row_data)


def _iter_dataset_row_data(dataset: Dataset):
    yield from (
        dataset.rows.order_by("row_number", "id")
        .values_list("data", flat=True)
        .iterator(chunk_size=1000)
    )


def _validate_existing_choice_values(dataset: Dataset, column_schema: dict) -> None:
    invalid_values = invalid_choice_values_by_column(
        dataset.headers,
        column_schema,
        _iter_dataset_row_data(dataset),
    )
    if not invalid_values:
        return

    column = sorted(invalid_values)[0]
    values = ", ".join(sorted(invalid_values[column])[:5])
    raise DatasetServiceError(
        400,
        f"Column '{column}' has existing values outside the allowed choices: {values}.",
    )


def _dataset_reference_validation_error(column: str) -> DatasetServiceError:
    return DatasetServiceError(
        400,
        f"Column '{column}' references a dataset that does not exist or is not owned "
        "by this profile.",
    )


def _project_reference_validation_error(column: str) -> DatasetServiceError:
    return DatasetServiceError(
        400,
        f"Column '{column}' references a project that does not exist or is not owned "
        "by this profile.",
    )


def _canonical_dataset_reference_value(profile: Profile, column: str, raw_value) -> str:
    normalized_value = str(raw_value or "").strip()
    if not normalized_value:
        return ""
    try:
        return str(get_profile_dataset(profile, normalized_value).key)
    except DatasetServiceError as exc:
        if exc.status_code == 404:
            raise _dataset_reference_validation_error(column) from exc
        raise


def _canonical_project_reference_value(profile: Profile, column: str, raw_value) -> str:
    normalized_value = str(raw_value or "").strip()
    if not normalized_value:
        return ""
    try:
        return str(get_profile_project_reference(profile, normalized_value).key)
    except DatasetServiceError as exc:
        if exc.status_code == 404:
            raise _project_reference_validation_error(column) from exc
        raise


def _normalize_reference_row_data(
    profile: Profile,
    headers: list[str],
    column_schema: dict | None,
    row_data: dict,
    *,
    columns: list[str] | set[str] | None = None,
) -> dict[str, str]:
    selected_columns = set(columns) if columns is not None else None
    dataset_reference_columns = _dataset_reference_columns(headers, column_schema)
    project_reference_columns = _project_reference_columns(headers, column_schema)
    if selected_columns is not None:
        dataset_reference_columns = [
            column for column in dataset_reference_columns if column in selected_columns
        ]
        project_reference_columns = [
            column for column in project_reference_columns if column in selected_columns
        ]
    if not dataset_reference_columns and not project_reference_columns:
        return row_data

    normalized_data = dict(row_data)
    for column in dataset_reference_columns:
        normalized_data[column] = _canonical_dataset_reference_value(
            profile,
            column,
            normalized_data.get(column, ""),
        )
    for column in project_reference_columns:
        normalized_data[column] = _canonical_project_reference_value(
            profile,
            column,
            normalized_data.get(column, ""),
        )
    return normalized_data


def _normalize_reference_rows(
    profile: Profile,
    headers: list[str],
    column_schema: dict | None,
    rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    return [
        _normalize_reference_row_data(profile, headers, column_schema, row_data)
        for row_data in rows
    ]


def _validate_existing_reference_values(
    profile: Profile,
    dataset: Dataset,
    column_schema: dict,
) -> None:
    reference_columns = [
        *_dataset_reference_columns(dataset.headers, column_schema),
        *_project_reference_columns(dataset.headers, column_schema),
    ]
    if not reference_columns:
        return
    for row_data in _iter_dataset_row_data(dataset):
        _normalize_reference_row_data(
            profile,
            dataset.headers,
            column_schema,
            row_data,
            columns=reference_columns,
        )


def _validate_existing_image_values(dataset: Dataset, column_schema: dict) -> None:
    image_columns = image_columns_from_schema(dataset.headers, column_schema)
    if not image_columns:
        return
    for row in (
        dataset.rows.order_by("row_number", "id").only("id", "data").iterator(chunk_size=1000)
    ):
        row_data = row.data or {}
        _validate_image_row_data(
            dataset.headers,
            column_schema,
            row_data,
            columns=image_columns,
            allow_asset_refs=True,
        )
        for column in image_columns:
            asset_key = dataset_asset_key_from_ref(row_data.get(column, ""))
            if (
                asset_key
                and not DatasetAsset.objects.filter(
                    dataset=dataset,
                    row=row,
                    column_name=column,
                    key=asset_key,
                ).exists()
            ):
                raise DatasetServiceError(
                    400,
                    f"Column '{column}' references an image asset that does not exist.",
                )


def _create_dataset_index_config(
    headers: list[str],
    index_column: str | None,
) -> tuple[str, bool, list[str]]:
    normalized_index = (index_column or "").strip()
    if not normalized_index:
        generated_index = generated_index_column_name(headers)
        return generated_index, True, [generated_index, *headers]

    if normalized_index not in headers:
        raise DatasetServiceError(400, "Index column must match one of the dataset headers.")

    return normalized_index, False, headers


def _normalize_dataset_column_schema(
    *,
    base_headers: list[str],
    index_column: str,
    index_generated: bool,
    rows: list[dict[str, str]],
    column_types: dict[str, ColumnTypeSpec] | None,
) -> dict[str, dict[str, Any]]:
    inferred_schema = infer_column_schema(base_headers, rows)
    try:
        base_schema = normalize_column_schema(
            base_headers,
            column_types,
            fallback_schema=inferred_schema,
            reject_unknown=True,
        )
    except CSVParseError as exc:
        raise DatasetServiceError(400, str(exc)) from exc

    if (
        not index_generated
        and base_schema[index_column][COLUMN_SCHEMA_TYPE_KEY] == DatasetColumnType.IMAGE
    ):
        raise DatasetServiceError(400, "Image columns cannot be used as the dataset index.")

    if index_generated:
        return {
            index_column: generated_index_column_schema(),
            **base_schema,
        }
    return base_schema


def create_profile_dataset(
    profile: Profile,
    *,
    name: str,
    description: str | None = None,
    instructions: str | None = None,
    metadata: dict[str, Any] | None = None,
    headers: list[str] | None = None,
    rows: list[dict[str, Any]] | None = None,
    index_column: str | None = None,
    column_types: dict[str, ColumnTypeSpec] | None = None,
    project_key: str | None = None,
    section_key: str | None = None,
    agent_api_key: AgentApiKey | None = None,
) -> dict:
    """Create a ready API-backed dataset for an authenticated profile."""
    normalized_name = _normalize_dataset_name(name)
    normalized_description = _normalize_dataset_description(description)
    normalized_instructions = _normalize_dataset_instructions(instructions)
    normalized_metadata = _normalize_dataset_metadata(metadata)
    normalized_project_key = str(project_key or "").strip()
    project = (
        get_profile_project(profile, normalized_project_key) if normalized_project_key else None
    )
    section = _resolve_project_section_assignment(profile, project, section_key)
    normalized_rows = _normalize_create_rows(rows)
    base_headers = _normalize_create_headers(headers, normalized_rows)
    _validate_rows_match_headers(normalized_rows, base_headers)
    index_column, index_generated, dataset_headers = _create_dataset_index_config(
        base_headers,
        index_column,
    )
    column_schema = _normalize_dataset_column_schema(
        base_headers=base_headers,
        index_column=index_column,
        index_generated=index_generated,
        rows=normalized_rows,
        column_types=column_types,
    )
    _validate_choice_rows(base_headers, column_schema, normalized_rows)
    _validate_image_rows(base_headers, column_schema, normalized_rows)
    normalized_rows = _normalize_reference_rows(
        profile,
        base_headers,
        column_schema,
        normalized_rows,
    )
    api_dataset_count_before = Dataset.objects.filter(
        profile=profile,
        file_type=API_CREATED_FILE_TYPE,
        status=DatasetStatus.READY,
    ).count()

    seen_index_values = set()
    row_payloads = []
    for row_number, row_data in enumerate(normalized_rows, start=1):
        if index_generated:
            index_value = str(row_number)
            serialized_data = {
                index_column: index_value,
                **{header: row_data.get(header, "") for header in base_headers},
            }
        else:
            index_value = row_data.get(index_column, "").strip()
            if not index_value:
                raise DatasetServiceError(400, f"Index column '{index_column}' is required.")
            serialized_data = {header: row_data.get(header, "") for header in dataset_headers}

        if index_value in seen_index_values:
            raise DatasetServiceError(
                409,
                f"Index column '{index_column}' must be unique. Duplicate value: {index_value}.",
            )
        seen_index_values.add(index_value)
        row_payloads.append((row_number, index_value, serialized_data))

    with transaction.atomic():
        quota_profile = _lock_profile_for_quota(profile)
        _enforce_dataset_create_quota(quota_profile, len(row_payloads))
        now = timezone.now()
        dataset = Dataset.objects.create(
            profile=profile,
            project=project,
            section=section,
            created_by_agent_api_key=agent_api_key,
            updated_by_agent_api_key=agent_api_key,
            name=normalized_name,
            description=normalized_description,
            instructions=normalized_instructions,
            metadata=normalized_metadata,
            original_filename="Created via API",
            file_type=API_CREATED_FILE_TYPE,
            status=DatasetStatus.READY,
            headers=dataset_headers,
            column_schema=column_schema,
            preview_rows=[payload[2] for payload in row_payloads[:5]],
            index_column=index_column,
            index_generated=index_generated,
            row_count=len(row_payloads),
            confirmed_at=now,
            processed_at=now,
        )
        DatasetRow.objects.bulk_create(
            [
                DatasetRow(
                    dataset=dataset,
                    created_by_agent_api_key=agent_api_key,
                    updated_by_agent_api_key=agent_api_key,
                    row_number=row_number,
                    index_value=index_value,
                    data=data,
                )
                for row_number, index_value, data in row_payloads
            ],
            batch_size=1000,
        )
        record_dataset_mutation(
            dataset,
            DatasetMutationType.DATASET_CREATED,
            f"Dataset created with {len(row_payloads)} rows and {len(dataset_headers)} columns.",
            agent_api_key=agent_api_key,
            metadata={
                "headers": dataset_headers,
                "row_count": len(row_payloads),
                "index_column": index_column,
                "index_generated": index_generated,
                "description": normalized_description,
                "instructions": normalized_instructions,
                "metadata": normalized_metadata,
                "project_key": str(project.key) if project else "",
                "section_key": str(section.key) if section else "",
            },
        )
        if row_payloads:
            _enqueue_dataset_vector_backfill(dataset.id)

    track_activation_event(
        profile,
        ROWSET_DATASET_CREATED,
        {
            "dataset_id": dataset.id,
            "is_first_dataset": api_dataset_count_before == 0,
            "initial_row_count": len(row_payloads),
            "column_count": len(dataset_headers),
            "index_generated": index_generated,
            "has_project": project is not None,
            "has_section": section is not None,
            **agent_api_key_tracking_properties(agent_api_key),
        },
        source_function="apps.api.services.create_profile_dataset",
    )

    return {
        "status": "success",
        "message": "Dataset created.",
        "dataset": serialize_dataset_summary(dataset),
    }


def update_profile_dataset_column_types(
    profile: Profile,
    dataset_key: str,
    column_types: dict[str, ColumnTypeSpec],
    agent_api_key: AgentApiKey | None = None,
) -> dict:
    with transaction.atomic():
        dataset = _get_profile_dataset_from_queryset(
            Dataset.objects.select_for_update(),
            profile,
            dataset_key,
        )

        _raise_if_archived(dataset)

        if dataset.status == DatasetStatus.PROCESSING:
            raise DatasetServiceError(
                409,
                "Column types cannot be updated while the dataset is processing.",
            )

        previous_schema = normalize_column_schema(dataset.headers, dataset.column_schema)
        try:
            next_schema = normalize_column_schema(
                dataset.headers,
                column_types,
                fallback_schema=dataset.column_schema,
                reject_unknown=True,
            )
        except CSVParseError as exc:
            raise DatasetServiceError(400, str(exc)) from exc
        if next_schema[dataset.index_column][COLUMN_SCHEMA_TYPE_KEY] == DatasetColumnType.IMAGE:
            raise DatasetServiceError(400, "Image columns cannot be used as the dataset index.")
        _validate_existing_choice_values(dataset, next_schema)
        _validate_existing_reference_values(profile, dataset, next_schema)
        _validate_existing_image_values(dataset, next_schema)
        dataset.column_schema = next_schema
        dataset.updated_by_agent_api_key = agent_api_key
        dataset.save(
            update_fields=[
                "column_schema",
                "updated_by_agent_api_key",
                "updated_at",
            ]
        )
        record_dataset_mutation(
            dataset,
            DatasetMutationType.COLUMN_TYPES_UPDATED,
            "Column types updated.",
            agent_api_key=agent_api_key,
            target_type="schema",
            metadata={
                "previous_column_schema": previous_schema,
                "column_schema": next_schema,
                "updated_columns": sorted(column_types),
            },
        )
        if dataset.status == DatasetStatus.READY:
            _enqueue_dataset_vector_reindex(dataset.id)

    return {
        "status": "success",
        "message": "Column types updated.",
        "dataset": serialize_dataset_summary(dataset),
    }


def _dataset_metadata_state(dataset: Dataset) -> dict[str, Any]:
    return {
        "description": dataset.description,
        "instructions": dataset.instructions,
        "metadata": dataset.metadata or {},
    }


def update_profile_dataset_metadata(
    profile: Profile,
    dataset_key: str,
    *,
    description: Any = UNSET,
    instructions: Any = UNSET,
    metadata: Any = UNSET,
    agent_api_key: AgentApiKey | None = None,
) -> dict:
    """Update persistent dataset context for agents and authenticated users."""
    if description is UNSET and instructions is UNSET and metadata is UNSET:
        raise DatasetServiceError(
            400,
            "Provide description, instructions, or metadata to update.",
        )

    with transaction.atomic():
        dataset = _get_profile_dataset_from_queryset(
            Dataset.objects.select_for_update(),
            profile,
            dataset_key,
        )
        _raise_if_archived(dataset)

        previous_state = _dataset_metadata_state(dataset)
        changed_fields = []
        update_fields = []

        if description is not UNSET:
            next_description = _normalize_dataset_description(description)
            if dataset.description != next_description:
                dataset.description = next_description
                changed_fields.append("description")
                update_fields.append("description")

        if instructions is not UNSET:
            next_instructions = _normalize_dataset_instructions(instructions)
            if dataset.instructions != next_instructions:
                dataset.instructions = next_instructions
                changed_fields.append("instructions")
                update_fields.append("instructions")

        if metadata is not UNSET:
            next_metadata = _normalize_dataset_metadata(metadata)
            if (dataset.metadata or {}) != next_metadata:
                dataset.metadata = next_metadata
                changed_fields.append("metadata")
                update_fields.append("metadata")

        if changed_fields:
            dataset.updated_by_agent_api_key = agent_api_key
            update_fields.extend(["updated_by_agent_api_key", "updated_at"])
            dataset.save(update_fields=update_fields)
            record_dataset_mutation(
                dataset,
                DatasetMutationType.DATASET_METADATA_UPDATED,
                "Dataset metadata updated.",
                agent_api_key=agent_api_key,
                target_type="dataset",
                target_identifier=str(dataset.key),
                metadata={
                    "previous": previous_state,
                    "current": _dataset_metadata_state(dataset),
                    "changed_fields": changed_fields,
                },
            )

    return {
        "status": "success",
        "message": (
            "Dataset metadata updated."
            if changed_fields
            else "No dataset metadata changes detected."
        ),
        "dataset": serialize_dataset_summary(dataset),
    }


def _normalize_existing_column_name(dataset: Dataset, name: str) -> str:
    normalized_name = str(name or "").strip()
    if normalized_name not in dataset.headers:
        raise DatasetServiceError(404, "Column not found.")
    return normalized_name


def _normalize_new_column_name(dataset: Dataset, name: str, *, replacing: str | None = None) -> str:
    normalized_name = str(name or "").strip()
    if replacing is None:
        next_headers = [*dataset.headers, normalized_name]
    else:
        next_headers = [
            normalized_name if header == replacing else header for header in dataset.headers
        ]

    try:
        validate_headers(next_headers, "Dataset")
    except CSVParseError as exc:
        raise DatasetServiceError(400, str(exc)) from exc
    return normalized_name


def _raise_if_column_participates_in_relationship(dataset: Dataset, column_name: str) -> None:
    outgoing = dataset.outgoing_relationships.filter(source_column=column_name).first()
    if outgoing is not None:
        raise DatasetServiceError(
            409,
            f"Column '{column_name}' is used by relationship '{outgoing.name}'. "
            "Delete the relationship before changing this column.",
        )
    if column_name == dataset.index_column:
        incoming = dataset.incoming_relationships.first()
        if incoming is not None:
            raise DatasetServiceError(
                409,
                f"Index column '{column_name}' is targeted by relationship '{incoming.name}'. "
                "Delete the relationship before changing this column.",
            )


def _normalized_column_schema_for_headers(
    headers: list[str],
    column_schema: dict,
) -> dict[str, dict[str, Any]]:
    try:
        return normalize_column_schema(headers, column_schema)
    except CSVParseError as exc:
        raise DatasetServiceError(400, str(exc)) from exc


def _transform_dataset_rows(
    dataset: Dataset,
    transform,
    *,
    agent_api_key: AgentApiKey | None,
) -> list[dict[str, str]]:
    batch_size = 1000
    batch = []
    preview_rows = []
    now = timezone.now()
    for row in dataset.rows.order_by("row_number", "id").iterator(chunk_size=batch_size):
        row.data = transform(row.data or {})
        row.updated_by_agent_api_key = agent_api_key
        row.updated_at = now
        batch.append(row)
        if len(preview_rows) < 5:
            preview_rows.append(row.data)

        if len(batch) >= batch_size:
            DatasetRow.objects.bulk_update(
                batch,
                ["data", "updated_by_agent_api_key", "updated_at"],
                batch_size=batch_size,
            )
            batch = []

    if batch:
        DatasetRow.objects.bulk_update(
            batch,
            ["data", "updated_by_agent_api_key", "updated_at"],
            batch_size=batch_size,
        )

    if preview_rows:
        return preview_rows

    return [transform(preview_row or {}) for preview_row in dataset.preview_rows[:5]]


def add_profile_dataset_column(
    profile: Profile,
    dataset_key: str,
    *,
    name: str,
    default_value: Any = "",
    column_type: ColumnTypeSpec | None = None,
    agent_api_key: AgentApiKey | None = None,
) -> dict:
    """Add one column to a ready dataset and backfill existing rows."""
    with transaction.atomic():
        dataset = get_ready_profile_dataset_for_update(profile, dataset_key)
        column_name = _normalize_new_column_name(dataset, name)
        default_cell = _stringify_cell(default_value)
        next_headers = [*dataset.headers, column_name]
        try:
            dataset.column_schema = normalize_column_schema(
                next_headers,
                {column_name: column_type} if column_type is not None else {},
                fallback_schema=dataset.column_schema,
                reject_unknown=True,
            )
        except CSVParseError as exc:
            raise DatasetServiceError(400, str(exc)) from exc
        default_row = {column_name: default_cell}
        _validate_choice_row_data(
            next_headers,
            dataset.column_schema,
            default_row,
            columns={column_name},
        )
        default_cell = default_row[column_name]
        _validate_image_row_data(
            next_headers,
            dataset.column_schema,
            default_row,
            columns={column_name},
        )
        default_cell = _normalize_reference_row_data(
            profile,
            next_headers,
            dataset.column_schema,
            default_row,
            columns={column_name},
        )[column_name]

        def add_column(data: dict) -> dict[str, str]:
            next_data = dict(data)
            next_data[column_name] = _stringify_cell(next_data.get(column_name, default_cell))
            return next_data

        dataset.headers = next_headers
        dataset.preview_rows = _transform_dataset_rows(
            dataset,
            add_column,
            agent_api_key=agent_api_key,
        )
        dataset.updated_by_agent_api_key = agent_api_key
        dataset.save(
            update_fields=[
                "headers",
                "column_schema",
                "preview_rows",
                "updated_by_agent_api_key",
                "updated_at",
            ]
        )
        record_dataset_mutation(
            dataset,
            DatasetMutationType.COLUMN_ADDED,
            f"Column '{column_name}' added.",
            agent_api_key=agent_api_key,
            target_type="column",
            target_identifier=column_name,
            metadata={
                "column": column_name,
                "column_type": dataset.column_schema[column_name]["type"],
                "default_value_provided": default_value not in ("", None),
            },
        )
        _enqueue_dataset_vector_reindex(dataset.id)

    return {
        "status": "success",
        "message": "Column added.",
        "dataset": serialize_dataset_summary(dataset),
    }


def rename_profile_dataset_column(
    profile: Profile,
    dataset_key: str,
    *,
    old_name: str,
    new_name: str,
    agent_api_key: AgentApiKey | None = None,
) -> dict:
    """Rename one column on a ready dataset while preserving row values."""
    with transaction.atomic():
        dataset = get_ready_profile_dataset_for_update(profile, dataset_key)
        old_column_name = _normalize_existing_column_name(dataset, old_name)
        _raise_if_column_participates_in_relationship(dataset, old_column_name)
        if dataset.index_generated and old_column_name == dataset.index_column:
            raise DatasetServiceError(
                400,
                f"Generated index column '{dataset.index_column}' cannot be renamed.",
            )

        new_column_name = _normalize_new_column_name(
            dataset,
            new_name,
            replacing=old_column_name,
        )
        current_schema = _normalized_column_schema_for_headers(
            dataset.headers,
            dataset.column_schema,
        )
        next_headers = [
            new_column_name if header == old_column_name else header for header in dataset.headers
        ]
        dataset.column_schema = {
            new_column_name if header == old_column_name else header: current_schema[header]
            for header in dataset.headers
        }

        def rename_column(data: dict) -> dict[str, str]:
            next_data = dict(data)
            next_data[new_column_name] = _stringify_cell(next_data.pop(old_column_name, ""))
            return next_data

        dataset.headers = next_headers
        if dataset.index_column == old_column_name:
            dataset.index_column = new_column_name
        dataset.preview_rows = _transform_dataset_rows(
            dataset,
            rename_column,
            agent_api_key=agent_api_key,
        )
        DatasetAsset.objects.filter(dataset=dataset, column_name=old_column_name).update(
            column_name=new_column_name
        )
        dataset.updated_by_agent_api_key = agent_api_key
        dataset.save(
            update_fields=[
                "headers",
                "column_schema",
                "index_column",
                "preview_rows",
                "updated_by_agent_api_key",
                "updated_at",
            ]
        )
        record_dataset_mutation(
            dataset,
            DatasetMutationType.COLUMN_RENAMED,
            f"Column '{old_column_name}' renamed to '{new_column_name}'.",
            agent_api_key=agent_api_key,
            target_type="column",
            target_identifier=new_column_name,
            metadata={
                "old_name": old_column_name,
                "new_name": new_column_name,
                "index_column_renamed": dataset.index_column == new_column_name,
            },
        )
        _enqueue_dataset_vector_reindex(dataset.id)

    return {
        "status": "success",
        "message": "Column renamed.",
        "dataset": serialize_dataset_summary(dataset),
    }


def drop_profile_dataset_column(
    profile: Profile,
    dataset_key: str,
    *,
    name: str,
    agent_api_key: AgentApiKey | None = None,
) -> dict:
    """Drop one non-index column from a ready dataset and stored rows."""
    with transaction.atomic():
        dataset = get_ready_profile_dataset_for_update(profile, dataset_key)
        column_name = _normalize_existing_column_name(dataset, name)
        _raise_if_column_participates_in_relationship(dataset, column_name)
        if column_name == dataset.index_column:
            raise DatasetServiceError(
                400,
                f"Index column '{dataset.index_column}' cannot be dropped.",
            )

        current_schema = _normalized_column_schema_for_headers(
            dataset.headers,
            dataset.column_schema,
        )
        next_headers = [header for header in dataset.headers if header != column_name]
        dataset.column_schema = {header: current_schema[header] for header in next_headers}

        def drop_column(data: dict) -> dict[str, str]:
            next_data = dict(data)
            next_data.pop(column_name, None)
            return next_data

        dataset.headers = next_headers
        dataset.preview_rows = _transform_dataset_rows(
            dataset,
            drop_column,
            agent_api_key=agent_api_key,
        )
        DatasetAsset.objects.filter(dataset=dataset, column_name=column_name).delete()
        dataset.updated_by_agent_api_key = agent_api_key
        dataset.save(
            update_fields=[
                "headers",
                "column_schema",
                "preview_rows",
                "updated_by_agent_api_key",
                "updated_at",
            ]
        )
        record_dataset_mutation(
            dataset,
            DatasetMutationType.COLUMN_DROPPED,
            f"Column '{column_name}' dropped.",
            agent_api_key=agent_api_key,
            target_type="column",
            target_identifier=column_name,
            metadata={
                "column": column_name,
                "column_schema": current_schema.get(column_name, {}),
            },
        )
        _enqueue_dataset_vector_reindex(dataset.id)

    return {
        "status": "success",
        "message": "Column dropped.",
        "dataset": serialize_dataset_summary(dataset),
    }


def _normalize_reordered_headers(dataset: Dataset, headers: list[str]) -> list[str]:
    try:
        normalized_headers = validate_headers(
            [str(header or "").strip() for header in headers],
            "Dataset",
        )
    except CSVParseError as exc:
        raise DatasetServiceError(400, str(exc)) from exc

    missing_headers = [header for header in dataset.headers if header not in normalized_headers]
    unknown_headers = [header for header in normalized_headers if header not in dataset.headers]
    if missing_headers or unknown_headers:
        details = []
        if missing_headers:
            details.append(f"missing headers: {', '.join(missing_headers)}")
        if unknown_headers:
            details.append(f"unknown headers: {', '.join(unknown_headers)}")
        joined = "; ".join(details)
        raise DatasetServiceError(
            400,
            f"Reordered headers must include each existing header exactly once ({joined}).",
        )

    return normalized_headers


def reorder_profile_dataset_columns(
    profile: Profile,
    dataset_key: str,
    *,
    headers: list[str],
    agent_api_key: AgentApiKey | None = None,
) -> dict:
    """Update the display/export order for ready dataset columns."""
    with transaction.atomic():
        dataset = get_ready_profile_dataset_for_update(profile, dataset_key)
        previous_headers = list(dataset.headers)
        next_headers = _normalize_reordered_headers(dataset, headers)
        current_schema = _normalized_column_schema_for_headers(
            dataset.headers,
            dataset.column_schema,
        )
        dataset.headers = next_headers
        dataset.column_schema = {header: current_schema[header] for header in next_headers}
        dataset.updated_by_agent_api_key = agent_api_key
        dataset.save(
            update_fields=[
                "headers",
                "column_schema",
                "updated_by_agent_api_key",
                "updated_at",
            ]
        )
        record_dataset_mutation(
            dataset,
            DatasetMutationType.COLUMNS_REORDERED,
            "Columns reordered.",
            agent_api_key=agent_api_key,
            target_type="schema",
            metadata={
                "previous_headers": previous_headers,
                "headers": next_headers,
            },
        )

    return {
        "status": "success",
        "message": "Columns reordered.",
        "dataset": serialize_dataset_summary(dataset),
    }


def update_profile_dataset_public_preview(
    profile: Profile,
    dataset_key: str,
    *,
    public_enabled: bool | None = None,
    public_page_size: int | None = None,
    public_password: str | None = None,
    clear_public_password: bool = False,
    agent_api_key: AgentApiKey | None = None,
) -> dict:
    if clear_public_password and public_password is not None:
        raise DatasetServiceError(
            400,
            "Use either public_password or clear_public_password, not both.",
        )

    with transaction.atomic():
        dataset = _get_profile_dataset_from_queryset(
            Dataset.objects.select_for_update(),
            profile,
            dataset_key,
        )

        _raise_if_archived(dataset)

        previous_public_enabled = dataset.public_enabled
        previous_public_page_size = dataset.public_page_size
        previous_password_protected = dataset.is_public_password_protected
        next_public_enabled = dataset.public_enabled if public_enabled is None else public_enabled

        if next_public_enabled and dataset.status != DatasetStatus.READY:
            raise DatasetServiceError(
                409,
                "Public previews can only be enabled for ready datasets.",
            )

        dataset.public_enabled = next_public_enabled
        if public_page_size is not None:
            dataset.public_page_size = normalize_public_page_size(public_page_size)

        password_changed = False
        if clear_public_password:
            password_changed = bool(dataset.public_password_hash)
            if password_changed:
                dataset.public_password_hash = ""
        elif public_password is not None:
            normalized_password = public_password.strip()
            if not normalized_password:
                raise DatasetServiceError(400, "Public preview password cannot be blank.")
            dataset.public_password_hash = make_password(normalized_password)
            password_changed = True

        settings_changed = (
            dataset.public_enabled != previous_public_enabled
            or dataset.public_page_size != previous_public_page_size
            or password_changed
        )

        if settings_changed:
            dataset.updated_by_agent_api_key = agent_api_key
            dataset.save(
                update_fields=[
                    "public_enabled",
                    "public_page_size",
                    "public_password_hash",
                    "updated_by_agent_api_key",
                    "updated_at",
                ]
            )
            record_dataset_mutation(
                dataset,
                DatasetMutationType.PUBLIC_PREVIEW_UPDATED,
                "Public preview settings updated.",
                agent_api_key=agent_api_key,
                target_type="public_preview",
                metadata={
                    "previous_public_enabled": previous_public_enabled,
                    "public_enabled": dataset.public_enabled,
                    "previous_public_page_size": previous_public_page_size,
                    "public_page_size": dataset.public_page_size,
                    "previous_password_protected": previous_password_protected,
                    "password_protected": dataset.is_public_password_protected,
                    "password_changed": password_changed,
                },
            )

    return {
        "status": "success",
        "message": "Public preview settings updated.",
        "dataset": serialize_dataset_summary(dataset),
    }


def update_profile_dataset_project(
    profile: Profile,
    dataset_key: str,
    project_key: str | None,
    section_key: str | None = None,
    agent_api_key: AgentApiKey | None = None,
) -> dict:
    """Attach an existing dataset to a project owned by the profile, or detach it."""
    normalized_project_key = str(project_key or "").strip()
    project = (
        get_profile_project(profile, normalized_project_key) if normalized_project_key else None
    )
    section = _resolve_project_section_assignment(profile, project, section_key)

    with transaction.atomic():
        dataset = _get_profile_dataset_from_queryset(
            Dataset.objects.select_for_update(),
            profile,
            dataset_key,
        )

        _raise_if_archived(dataset)

        previous_project_key = str(dataset.project.key) if dataset.project else ""
        previous_project_name = dataset.project.name if dataset.project else ""
        previous_section_key = str(dataset.section.key) if dataset.section else ""
        previous_section_name = dataset.section.name if dataset.section else ""
        dataset.project = project
        dataset.section = section
        dataset.updated_by_agent_api_key = agent_api_key
        dataset.save(update_fields=["project", "section", "updated_by_agent_api_key", "updated_at"])
        record_dataset_mutation(
            dataset,
            DatasetMutationType.DATASET_PROJECT_UPDATED,
            "Project assignment updated.",
            agent_api_key=agent_api_key,
            target_type="project",
            target_identifier=str(project.key) if project else "",
            metadata={
                "previous_project_key": previous_project_key,
                "previous_project_name": previous_project_name,
                "previous_section_key": previous_section_key,
                "previous_section_name": previous_section_name,
                "project_key": str(project.key) if project else "",
                "project_name": project.name if project else "",
                "section_key": str(section.key) if section else "",
                "section_name": section.name if section else "",
            },
        )

    return {
        "status": "success",
        "message": "Dataset project updated.",
        "dataset": serialize_dataset_summary(dataset),
    }


def archive_profile_dataset(
    profile: Profile,
    dataset_key: str,
    agent_api_key: AgentApiKey | None = None,
) -> dict:
    """Archive an owned dataset without deleting rows or schema metadata."""
    with transaction.atomic():
        dataset = _get_profile_dataset_from_queryset(
            Dataset.objects.select_for_update(),
            profile,
            dataset_key,
        )

        was_archived = dataset.archived_at is not None
        was_public_enabled = dataset.public_enabled
        message = "Dataset was already archived."
        update_fields = []
        if dataset.archived_at is None or dataset.public_enabled:
            message = "Dataset archived."
            update_fields = ["public_enabled", "updated_at"]
            dataset.public_enabled = False

        if dataset.archived_at is None:
            dataset.archived_at = timezone.now()
            dataset.archived_by_agent_api_key = agent_api_key
            dataset.updated_by_agent_api_key = agent_api_key
            update_fields.extend(
                [
                    "archived_at",
                    "archived_by_agent_api_key",
                    "updated_by_agent_api_key",
                ]
            )

        if update_fields:
            dataset.save(update_fields=update_fields)
            if was_archived:
                record_dataset_mutation(
                    dataset,
                    DatasetMutationType.PUBLIC_PREVIEW_UPDATED,
                    "Public preview disabled.",
                    agent_api_key=agent_api_key,
                    target_type="public_preview",
                    metadata={
                        "previous_public_enabled": was_public_enabled,
                        "public_enabled": dataset.public_enabled,
                    },
                )
            else:
                record_dataset_mutation(
                    dataset,
                    DatasetMutationType.DATASET_ARCHIVED,
                    "Dataset archived.",
                    agent_api_key=agent_api_key,
                    metadata={"public_preview_disabled": was_public_enabled},
                )
                _enqueue_dataset_vector_delete(dataset.id)

    return {
        "status": "success",
        "message": message,
        "dataset": serialize_dataset_summary(dataset),
    }


def restore_profile_dataset(
    profile: Profile,
    dataset_key: str,
    agent_api_key: AgentApiKey | None = None,
) -> dict:
    """Restore an archived dataset to normal dataset and project listings."""
    with transaction.atomic():
        dataset = _get_profile_dataset_from_queryset(
            Dataset.objects.select_for_update(),
            profile,
            dataset_key,
        )

        message = "Dataset was not archived."
        if dataset.archived_at is not None:
            message = "Dataset restored."
            dataset.archived_at = None
            dataset.archived_by_agent_api_key = None
            dataset.updated_by_agent_api_key = agent_api_key
            dataset.save(
                update_fields=[
                    "archived_at",
                    "archived_by_agent_api_key",
                    "updated_by_agent_api_key",
                    "updated_at",
                ]
            )
            record_dataset_mutation(
                dataset,
                DatasetMutationType.DATASET_RESTORED,
                "Dataset restored.",
                agent_api_key=agent_api_key,
            )
            _enqueue_dataset_vector_backfill(dataset.id)

    return {
        "status": "success",
        "message": message,
        "dataset": serialize_dataset_summary(dataset),
    }


def _serialized_row_assets(row: DatasetRow, dataset: Dataset | None = None) -> list[dict]:
    row_data = row.data or {}
    return [
        serialize_dataset_asset(asset, dataset=dataset, row=row)
        for asset in row.assets.all()
        if str(row_data.get(asset.column_name, "") or "") == asset.asset_ref
    ]


def serialize_dataset_row(row: DatasetRow, *, dataset: Dataset | None = None) -> dict:
    return {
        "id": row.id,
        "row_number": row.row_number,
        "index_value": row.index_value,
        "data": row.data,
        "assets": _serialized_row_assets(row, dataset),
    }


def dataset_asset_content_field(asset: DatasetAsset, variant: str = "original"):
    normalized_variant = str(variant or "original").strip().lower()
    if normalized_variant == "thumbnail":
        return asset.thumbnail or asset.file
    if normalized_variant in {"", "original"}:
        return asset.file
    raise DatasetServiceError(400, "Asset variant must be 'original' or 'thumbnail'.")


def _dataset_asset_content_url(
    asset: DatasetAsset,
    variant: str,
    *,
    dataset: Dataset | None = None,
) -> str:
    dataset = dataset or asset.dataset
    return build_absolute_public_url(
        f"/api/datasets/{dataset.key}/assets/{asset.key}/content?variant={variant}"
    )


def _dataset_asset_public_content_url(
    asset: DatasetAsset,
    variant: str,
    *,
    dataset: Dataset | None = None,
) -> str | None:
    dataset = dataset or asset.dataset
    if not dataset.public_enabled or dataset.is_public_password_protected:
        return None
    path = reverse(
        "public_dataset_asset_content",
        kwargs={"public_key": dataset.public_key, "asset_key": asset.key},
    )
    return build_absolute_public_url(f"{path}?variant={variant}")


def serialize_dataset_asset(
    asset: DatasetAsset,
    *,
    dataset: Dataset | None = None,
    row: DatasetRow | None = None,
) -> dict:
    dataset = dataset or asset.dataset
    row = row or asset.row
    has_thumbnail = bool(asset.thumbnail and asset.thumbnail.name)
    return {
        "key": str(asset.key),
        "ref": dataset_asset_ref(asset.key),
        "dataset": str(dataset.key),
        "row_id": row.id,
        "row_number": row.row_number,
        "index_value": row.index_value,
        "column": asset.column_name,
        "original_filename": asset.original_filename,
        "content_type": asset.content_type,
        "byte_size": asset.byte_size,
        "width": asset.width,
        "height": asset.height,
        "checksum": asset.checksum,
        "status": asset.status,
        "has_thumbnail": has_thumbnail,
        "content_url": _dataset_asset_content_url(asset, "original", dataset=dataset),
        "thumbnail_url": _dataset_asset_content_url(asset, "thumbnail", dataset=dataset),
        "content_url_auth_required": True,
        "public_enabled": dataset.public_enabled,
        "public_password_protected": dataset.is_public_password_protected,
        "public_content_url": _dataset_asset_public_content_url(
            asset,
            "original",
            dataset=dataset,
        ),
        "public_thumbnail_url": _dataset_asset_public_content_url(
            asset,
            "thumbnail",
            dataset=dataset,
        ),
        "created_at": asset.created_at,
        "updated_at": asset.updated_at,
    }


def _get_dataset_asset_by_key(dataset: Dataset, profile: Profile, asset_key: str) -> DatasetAsset:
    try:
        asset_uuid = UUID(str(asset_key or "").strip())
    except (AttributeError, TypeError, ValueError) as exc:
        raise DatasetServiceError(404, "Dataset asset not found.") from exc
    try:
        return dataset.assets.select_related("row").get(key=asset_uuid, profile=profile)
    except DatasetAsset.DoesNotExist as exc:
        raise DatasetServiceError(404, "Dataset asset not found.") from exc


def get_profile_dataset_asset(profile: Profile, dataset_key: str, asset_key: str) -> DatasetAsset:
    dataset = get_ready_profile_dataset(profile, dataset_key)
    return _get_dataset_asset_by_key(dataset, profile, asset_key)


def serialize_profile_dataset_asset(profile: Profile, dataset_key: str, asset_key: str) -> dict:
    asset = get_profile_dataset_asset(profile, dataset_key, asset_key)
    return {
        "status": "success",
        "message": "Dataset asset retrieved.",
        "asset": serialize_dataset_asset(asset),
    }


def _row_for_image_attachment(
    dataset: Dataset,
    *,
    row_id: int | None = None,
    index_value: str | None = None,
) -> DatasetRow:
    has_row_id = row_id is not None
    normalized_index_value = str(index_value or "").strip()
    has_index_value = bool(normalized_index_value)
    if has_row_id == has_index_value:
        raise DatasetServiceError(400, "Provide exactly one of row_id or index_value.")
    try:
        if has_row_id:
            return dataset.rows.select_for_update().get(id=row_id)
        return dataset.rows.select_for_update().get(index_value=normalized_index_value)
    except DatasetRow.DoesNotExist as exc:
        raise DatasetServiceError(404, "Row not found.") from exc


def _normalize_image_asset_column(dataset: Dataset, column_name: str) -> str:
    column = _normalize_existing_column_name(dataset, column_name)
    normalized_schema = normalize_column_schema(dataset.headers, dataset.column_schema)
    if normalized_schema[column][COLUMN_SCHEMA_TYPE_KEY] != DatasetColumnType.IMAGE:
        raise DatasetServiceError(400, f"Column '{column}' is not an image column.")
    if column == dataset.index_column:
        raise DatasetServiceError(400, "Image columns cannot be used as the dataset index.")
    return column


def attach_profile_dataset_image_asset(
    profile: Profile,
    dataset_key: str,
    *,
    column_name: str,
    image_base64: str,
    filename: str | None = None,
    content_type: str | None = None,
    row_id: int | None = None,
    index_value: str | None = None,
    agent_api_key: AgentApiKey | None = None,
) -> dict:
    dataset = get_ready_profile_dataset(profile, dataset_key)
    _normalize_image_asset_column(dataset, column_name)
    try:
        prepared_image = prepare_dataset_image(
            image_bytes=decode_image_base64(image_base64),
            filename=filename,
            content_type=content_type,
        )
    except DatasetImageError as exc:
        raise DatasetServiceError(400, str(exc)) from exc

    saved_files = []
    try:
        with transaction.atomic():
            dataset = get_ready_profile_dataset_for_update(profile, dataset_key)
            column = _normalize_image_asset_column(dataset, column_name)
            row = _row_for_image_attachment(dataset, row_id=row_id, index_value=index_value)

            previous_value = str((row.data or {}).get(column, "") or "")
            DatasetAsset.objects.filter(dataset=dataset, row=row, column_name=column).delete()
            asset = DatasetAsset(
                profile=profile,
                dataset=dataset,
                row=row,
                created_by_agent_api_key=agent_api_key,
                column_name=column,
                original_filename=prepared_image.filename,
                content_type=prepared_image.content_type,
                byte_size=prepared_image.byte_size,
                width=prepared_image.width,
                height=prepared_image.height,
                checksum=prepared_image.checksum,
            )
            asset.file.name = asset.file.field.generate_filename(asset, prepared_image.filename)
            if prepared_image.thumbnail_bytes is not None:
                asset.thumbnail.name = asset.thumbnail.field.generate_filename(
                    asset,
                    "thumbnail.jpg",
                )
            asset.save()

            next_value = asset.asset_ref
            row.data = {**(row.data or {}), column: next_value}
            row.updated_by_agent_api_key = agent_api_key
            row.save(update_fields=["data", "updated_by_agent_api_key", "updated_at"])
            dataset.updated_by_agent_api_key = agent_api_key
            dataset.save(update_fields=["updated_by_agent_api_key", "updated_at"])
            is_first_row_mutation = not _profile_has_row_mutation(profile)
            record_dataset_mutation(
                dataset,
                DatasetMutationType.ROW_UPDATED,
                f"Image attached to row {row.row_number}.",
                agent_api_key=agent_api_key,
                target_type="row",
                target_identifier=row.id,
                metadata={
                    "row_id": row.id,
                    "row_number": row.row_number,
                    "changed_fields": [column],
                    "field_changes": [
                        {
                            "field": column,
                            "before": previous_value,
                            "after": next_value,
                        }
                    ],
                    "value_changes_recorded": True,
                    "asset_key": str(asset.key),
                    "asset_ref_recorded": True,
                    "filename": prepared_image.filename,
                    "content_type": prepared_image.content_type,
                    "byte_size": prepared_image.byte_size,
                    "width": prepared_image.width,
                    "height": prepared_image.height,
                },
            )
            _track_dataset_row_mutation(
                profile=profile,
                dataset=dataset,
                mutation_type=DatasetMutationType.ROW_UPDATED,
                agent_api_key=agent_api_key,
                is_first_row_mutation=is_first_row_mutation,
                changed_field_count=1,
                image_asset_attached=True,
            )
            saved_file_name = asset.file.storage.save(
                asset.file.name,
                ContentFile(prepared_image.image_bytes),
            )
            saved_files.append((DATASET_ASSET_STORAGE_ALIAS, saved_file_name))
            if saved_file_name != asset.file.name:
                raise DatasetServiceError(500, "Image upload path could not be reserved.")
            if prepared_image.thumbnail_bytes is not None:
                saved_thumbnail_name = asset.thumbnail.storage.save(
                    asset.thumbnail.name,
                    ContentFile(prepared_image.thumbnail_bytes),
                )
                saved_files.append((DATASET_ASSET_STORAGE_ALIAS, saved_thumbnail_name))
                if saved_thumbnail_name != asset.thumbnail.name:
                    raise DatasetServiceError(500, "Image thumbnail path could not be reserved.")
    except Exception:
        cleanup_error = None
        for storage_alias, name in saved_files:
            try:
                storages[storage_alias].delete(name)
            except Exception as exc:
                cleanup_error = cleanup_error or exc
                record_dataset_asset_file_deletion_failure(storage_alias, name, exc)
        if cleanup_error is not None:
            raise DatasetServiceError(
                500,
                "Image upload failed and saved files were queued for cleanup.",
            ) from cleanup_error
        raise

    return {
        "status": "success",
        "message": "Image attached.",
        "dataset": str(dataset.key),
        "row": serialize_dataset_row(row, dataset=dataset),
        "asset": serialize_dataset_asset(asset, dataset=dataset, row=row),
    }


def _normalize_dataset_search_limit(limit: int) -> int:
    try:
        normalized_limit = int(limit)
    except DATASET_SEARCH_LIMIT_ERRORS:
        normalized_limit = 10
    return max(1, min(normalized_limit, DATASET_SEARCH_MAX_LIMIT))


def _reciprocal_rank_score(rank: int | None) -> float:
    if rank is None:
        return 0.0
    return 1 / (DATASET_SEARCH_RRF_K + rank)


def _safe_vector_row_id(payload: dict[str, Any]) -> int | None:
    try:
        return int(payload.get("row_id"))
    except DATASET_SEARCH_LIMIT_ERRORS:
        return None


def _search_result_snippet(dataset: Dataset, row: DatasetRow) -> str:
    document = build_dataset_row_search_document(dataset, row)
    compact = " ".join(document.text.split())
    if len(compact) <= 300:
        return compact
    return f"{compact[:297].rstrip()}..."


def _dataset_search_querysets(
    dataset: Dataset,
    *,
    query: str,
    filters: dict[str, Any] | None,
):
    try:
        filtered_queryset, row_query = apply_dataset_row_query(
            dataset.rows.all(),
            dataset,
            filters=filters,
            strict=True,
        )
        lexical_queryset, _lexical_query = apply_dataset_row_query(
            dataset.rows.all(),
            dataset,
            query=query,
            filters=filters,
            strict=True,
        )
    except DatasetRowQueryError as exc:
        raise DatasetServiceError(400, str(exc)) from exc
    return filtered_queryset, row_query, lexical_queryset


def _dataset_vector_search_hits(
    dataset: Dataset,
    *,
    query: str,
    limit: int,
    embedding_provider: EmbeddingProvider | None,
    vector_store: QdrantVectorStore | None,
):
    try:
        provider = embedding_provider or get_embedding_provider()
        store = vector_store or QdrantVectorStore(
            embedding_model=provider.model,
            embedding_dimensions=provider.dimensions,
        )
        embedding_started_at = perf_counter()
        query_embedding = provider.embed_text(query)
        embedding_latency_ms = (perf_counter() - embedding_started_at) * 1000
        vector_started_at = perf_counter()
        hits = store.search_dataset_rows(dataset, query_embedding.vector, limit=limit * 3)
        vector_latency_ms = (perf_counter() - vector_started_at) * 1000
        return _DatasetVectorSearchResult(
            hits=hits,
            embedding_model=query_embedding.model,
            embedding_dimensions=query_embedding.dimensions,
            embedding_latency_ms=embedding_latency_ms,
            vector_latency_ms=vector_latency_ms,
        )
    except (EmbeddingProviderError, ImproperlyConfigured, VectorStoreError, ValueError) as exc:
        raise DatasetServiceError(503, f"Dataset vector search failed: {exc}") from exc


def _dataset_search_candidates(
    *,
    vector_hits,
    lexical_rows: list[DatasetRow],
    allowed_row_ids: set[int] | None,
) -> dict[int, RowSearchCandidate]:
    candidates: dict[int, RowSearchCandidate] = {}
    for vector_rank, hit in enumerate(vector_hits, start=1):
        row_id = _safe_vector_row_id(hit.payload)
        if row_id is None or (allowed_row_ids is not None and row_id not in allowed_row_ids):
            continue
        candidate = candidates.setdefault(row_id, {"row_id": row_id})
        candidate.setdefault("vector_rank", vector_rank)
        candidate.setdefault("vector_score", hit.score)
        candidate.setdefault("point_id", hit.point_id)
        candidate.setdefault("chunk_index", hit.payload.get("chunk_index"))
        candidate.setdefault("content_hash", hit.payload.get("content_hash"))

    for lexical_rank, row in enumerate(lexical_rows, start=1):
        candidate = candidates.setdefault(row.id, {"row_id": row.id})
        candidate.setdefault("lexical_rank", lexical_rank)
    return candidates


def _rank_dataset_search_candidates(
    candidates: dict[int, RowSearchCandidate],
    *,
    limit: int,
) -> list[RankedRowSearchCandidate]:
    for candidate in candidates.values():
        vector_rank = candidate.get("vector_rank")
        lexical_rank = candidate.get("lexical_rank")
        candidate["score"] = _reciprocal_rank_score(vector_rank) + _reciprocal_rank_score(
            lexical_rank
        )
        if vector_rank is not None and lexical_rank is not None:
            candidate["source"] = "hybrid"
        elif vector_rank is not None:
            candidate["source"] = "vector"
        else:
            candidate["source"] = "lexical"

    return sorted(
        candidates.values(),
        key=lambda candidate: (
            -candidate["score"],
            candidate.get("vector_rank") or 10_000,
            candidate.get("lexical_rank") or 10_000,
            candidate["row_id"],
        ),
    )[:limit]


def _serialize_dataset_search_results(
    dataset: Dataset,
    ranked_candidates: list[RankedRowSearchCandidate],
) -> list[dict[str, Any]]:
    rows_by_id = {
        row.id: row
        for row in dataset.rows.prefetch_related("assets").filter(
            id__in=[candidate["row_id"] for candidate in ranked_candidates]
        )
    }
    results = []
    for rank, candidate in enumerate(ranked_candidates, start=1):
        row = rows_by_id.get(candidate["row_id"])
        if row is None:
            continue
        results.append(
            {
                "rank": rank,
                "score": candidate["score"],
                "row": serialize_dataset_row(row, dataset=dataset),
                "match": {
                    "source": candidate["source"],
                    "vector_score": candidate.get("vector_score"),
                    "vector_rank": candidate.get("vector_rank"),
                    "lexical_rank": candidate.get("lexical_rank"),
                    "point_id": candidate.get("point_id"),
                    "chunk_index": candidate.get("chunk_index"),
                    "content_hash": candidate.get("content_hash"),
                    "snippet": _search_result_snippet(dataset, row),
                },
            }
        )
    return results


def _normalize_profile_row_search_limit(limit: int) -> int:
    return max(1, min(int(limit or 10), DATASET_SEARCH_MAX_LIMIT))


def _normalize_profile_row_search_sort(sort: str | None) -> str:
    normalized_sort = str(sort or PROFILE_ROW_SEARCH_SORT_RANK).strip().lower()
    if not normalized_sort:
        return PROFILE_ROW_SEARCH_SORT_RANK
    if normalized_sort not in PROFILE_ROW_SEARCH_SORTS:
        allowed = ", ".join(sorted(PROFILE_ROW_SEARCH_SORTS))
        raise DatasetServiceError(400, f"Search sort must be one of: {allowed}.")
    return normalized_sort


def _normalize_profile_row_search_direction(direction: str | None, sort: str) -> str:
    default_direction = "desc" if sort == PROFILE_ROW_SEARCH_SORT_RANK else "asc"
    normalized_direction = str(direction or default_direction).strip().lower()
    if normalized_direction in {"", "asc"}:
        return "asc"
    if normalized_direction == "desc":
        return "desc"
    raise DatasetServiceError(400, "Search direction must be 'asc' or 'desc'.")


def _normalize_profile_row_filters(filters: dict[str, Any] | None) -> RowFilters:
    if filters is None:
        return {}
    if not isinstance(filters, dict):
        raise DatasetServiceError(400, "Search filters must be a JSON object.")

    try:
        return normalize_search_filters(filters)
    except ValueError as exc:
        raise DatasetServiceError(400, str(exc)) from exc


def _normalize_profile_row_filter_operators(
    filter_operators: dict[str, Any] | None,
    filters: RowFilters,
) -> RowFilterOperators:
    if filter_operators is None:
        return {}
    if not isinstance(filter_operators, dict):
        raise DatasetServiceError(400, "Search filter_operators must be a JSON object.")

    try:
        return normalize_search_filter_operators(filter_operators, filters)
    except ValueError as exc:
        raise DatasetServiceError(400, str(exc)) from exc


def _profile_row_search_dataset_queryset(
    profile: Profile,
    *,
    dataset_key: str | None,
    project_key: str | None,
    section_key: str | None,
    status: str | None,
    archived: bool | None,
    filters: dict[str, str],
):
    normalized_dataset_key = str(dataset_key or "").strip()
    normalized_project_key = str(project_key or "").strip()
    normalized_section_key = str(section_key or "").strip()
    normalized_status = _normalize_dataset_status(status or DatasetStatus.READY)

    queryset = _dataset_summary_queryset(profile.datasets)
    if normalized_dataset_key:
        identifier = _dataset_identifier_uuid(normalized_dataset_key)
        queryset = queryset.filter(Q(key=identifier) | Q(public_key=identifier))
    if normalized_project_key:
        try:
            project_key_uuid = UUID(normalized_project_key)
        except ValueError as exc:
            raise DatasetServiceError(400, "project_key must be a valid UUID.") from exc
        queryset = queryset.filter(project__key=project_key_uuid, project__archived_at__isnull=True)
    if normalized_section_key:
        try:
            section_key_uuid = UUID(normalized_section_key)
        except ValueError as exc:
            raise DatasetServiceError(400, "section_key must be a valid UUID.") from exc
        queryset = queryset.filter(
            section__key=section_key_uuid,
            section__archived_at__isnull=True,
            section__project__archived_at__isnull=True,
        )
    if normalized_status:
        queryset = queryset.filter(status=normalized_status)
    if archived is not None:
        queryset = queryset.filter(archived_at__isnull=not archived)
    if filters:
        queryset = queryset.filter(headers__contains=list(filters))
    return queryset.order_by("id"), {
        "dataset_key": normalized_dataset_key,
        "project_key": normalized_project_key,
        "section_key": normalized_section_key,
        "status": normalized_status,
        "archived": archived,
    }


def _profile_vector_search_hits(
    profile: Profile,
    *,
    query: str,
    dataset_ids: list[int],
    dataset_status: str | None,
    dataset_archived: bool | None,
    limit: int,
    embedding_provider: EmbeddingProvider | None,
    vector_store: QdrantVectorStore | None,
):
    try:
        provider = embedding_provider or get_embedding_provider()
        store = vector_store or QdrantVectorStore(
            embedding_model=provider.model,
            embedding_dimensions=provider.dimensions,
        )
        embedding_started_at = perf_counter()
        query_embedding = provider.embed_text(query)
        embedding_latency_ms = (perf_counter() - embedding_started_at) * 1000
        vector_started_at = perf_counter()
        hits = store.search_profile_dataset_rows(
            profile,
            query_embedding.vector,
            dataset_ids=dataset_ids,
            dataset_status=dataset_status,
            dataset_archived=dataset_archived,
            limit=limit * 3,
        )
        vector_latency_ms = (perf_counter() - vector_started_at) * 1000
        return _DatasetVectorSearchResult(
            hits=hits,
            embedding_model=query_embedding.model,
            embedding_dimensions=query_embedding.dimensions,
            embedding_latency_ms=embedding_latency_ms,
            vector_latency_ms=vector_latency_ms,
        )
    except (EmbeddingProviderError, ImproperlyConfigured, VectorStoreError, ValueError) as exc:
        raise DatasetServiceError(503, f"Profile row vector search failed: {exc}") from exc


def _profile_lexical_rows(
    datasets: list[Dataset],
    *,
    query: str,
    filters: dict[str, str],
    filter_operators: dict[str, str],
    limit: int,
) -> list[DatasetRow]:
    try:
        queryset = apply_dataset_rows_query(
            DatasetRow.objects.all(),
            datasets,
            query=query,
            filters=filters,
            filter_operators=filter_operators,
            strict=True,
            skip_invalid_filter_operators=True,
        )
    except DatasetRowQueryError as exc:
        raise DatasetServiceError(400, str(exc)) from exc
    return list(queryset.only("id", "dataset_id")[: limit * 3])


def _profile_allowed_vector_row_ids(
    datasets: list[Dataset],
    vector_hits,
    *,
    filters: dict[str, str],
    filter_operators: dict[str, str],
) -> set[int]:
    vector_row_ids = [
        row_id
        for row_id in (_safe_vector_row_id(hit.payload) for hit in vector_hits)
        if row_id is not None
    ]
    if not vector_row_ids:
        return set()

    dataset_ids = [dataset.id for dataset in datasets]
    if not filters:
        return set(
            DatasetRow.objects.filter(dataset_id__in=dataset_ids, id__in=vector_row_ids)
            .order_by()
            .values_list("id", flat=True)
        )

    try:
        queryset = apply_dataset_rows_query(
            DatasetRow.objects.filter(id__in=vector_row_ids),
            datasets,
            filters=filters,
            filter_operators=filter_operators,
            strict=True,
            skip_invalid_filter_operators=True,
        )
    except DatasetRowQueryError as exc:
        raise DatasetServiceError(400, str(exc)) from exc
    return set(queryset.order_by().values_list("id", flat=True))


def _serialize_profile_row_search_results(
    ranked_candidates: list[RankedRowSearchCandidate],
) -> list[dict[str, Any]]:
    rows_by_id = {
        row.id: row
        for row in DatasetRow.objects.select_related(
            "dataset",
            "dataset__project",
            "dataset__section",
        )
        .prefetch_related("assets")
        .filter(id__in=[candidate["row_id"] for candidate in ranked_candidates])
    }
    results = []
    for rank, candidate in enumerate(ranked_candidates, start=1):
        row = rows_by_id.get(candidate["row_id"])
        if row is None:
            continue
        dataset = row.dataset
        results.append(
            {
                "rank": rank,
                "score": candidate["score"],
                "dataset": serialize_dataset_reference(dataset),
                "row": serialize_dataset_row(row, dataset=dataset),
                "match": {
                    "source": candidate["source"],
                    "vector_score": candidate.get("vector_score"),
                    "vector_rank": candidate.get("vector_rank"),
                    "lexical_rank": candidate.get("lexical_rank"),
                    "point_id": candidate.get("point_id"),
                    "chunk_index": candidate.get("chunk_index"),
                    "content_hash": candidate.get("content_hash"),
                    "snippet": _search_result_snippet(dataset, row),
                },
            }
        )
    return results


def _sort_profile_row_search_results(
    results: list[dict[str, Any]],
    *,
    sort: str,
    direction: str,
) -> list[dict[str, Any]]:
    if sort == PROFILE_ROW_SEARCH_SORT_RANK:
        ordered = list(reversed(results)) if direction == "asc" else results
    elif sort == PROFILE_ROW_SEARCH_SORT_DATASET:
        ordered = sorted(
            results,
            key=lambda result: (
                str(result["dataset"]["name"]).lower(),
                int(result["row"]["row_number"]),
                int(result["row"]["id"]),
            ),
            reverse=direction == "desc",
        )
    else:
        ordered = sorted(
            results,
            key=lambda result: (
                int(result["row"]["row_number"]),
                str(result["dataset"]["name"]).lower(),
                int(result["row"]["id"]),
            ),
            reverse=direction == "desc",
        )

    for rank, result in enumerate(ordered, start=1):
        result["rank"] = rank
    return ordered


def search_profile_rows(
    profile: Profile,
    *,
    query: str,
    filters: dict[str, Any] | None = None,
    filter_operators: dict[str, Any] | None = None,
    dataset_key: str | None = None,
    project_key: str | None = None,
    section_key: str | None = None,
    status: str | None = None,
    archived: bool | None = False,
    sort: str | None = None,
    direction: str | None = None,
    limit: int = 10,
    embedding_provider: EmbeddingProvider | None = None,
    vector_store: QdrantVectorStore | None = None,
) -> dict:
    query_id = uuid4().hex
    search_started_at = perf_counter()
    normalized_query = _normalize_search_query(query)
    if not normalized_query:
        raise DatasetServiceError(400, "Search query is required.")
    normalized_limit = _normalize_profile_row_search_limit(limit)
    normalized_sort = _normalize_profile_row_search_sort(sort)
    normalized_direction = _normalize_profile_row_search_direction(direction, normalized_sort)
    normalized_filters = _normalize_profile_row_filters(filters)
    normalized_filter_operators = _normalize_profile_row_filter_operators(
        filter_operators,
        normalized_filters,
    )
    dataset_queryset, dataset_filters = _profile_row_search_dataset_queryset(
        profile,
        dataset_key=dataset_key,
        project_key=project_key,
        section_key=section_key,
        status=status,
        archived=archived,
        filters=normalized_filters,
    )
    datasets = list(dataset_queryset)
    if not datasets:
        logger.info(
            "Profile row hybrid search complete",
            query_id=query_id,
            profile_id=profile.id,
            dataset_filters=dataset_filters,
            dataset_filter_count=len(dataset_filters),
            eligible_dataset_count=0,
            filters_count=len(normalized_filters),
            limit=normalized_limit,
            sort=normalized_sort,
            direction=normalized_direction,
            vector_hit_count=0,
            lexical_candidate_count=0,
            fused_candidate_count=0,
            result_count=0,
            hydration_misses=0,
            top_source="",
            top_score=None,
            top_vector_score=None,
            embedding_model="",
            embedding_dimensions=None,
            embedding_latency_ms=0,
            vector_latency_ms=0,
            search_latency_ms=round((perf_counter() - search_started_at) * 1000, 2),
        )
        return {
            "query": normalized_query,
            "filters": normalized_filters,
            "filter_operators": normalized_filter_operators,
            "dataset_filters": dataset_filters,
            "sort": normalized_sort,
            "direction": normalized_direction,
            "limit": normalized_limit,
            "count": 0,
            "results": [],
        }

    dataset_ids = [dataset.id for dataset in datasets]
    vector_search = _profile_vector_search_hits(
        profile,
        query=normalized_query,
        dataset_ids=dataset_ids,
        dataset_status=dataset_filters["status"],
        dataset_archived=dataset_filters["archived"],
        limit=normalized_limit,
        embedding_provider=embedding_provider,
        vector_store=vector_store,
    )
    vector_hits = vector_search.hits
    allowed_row_ids = _profile_allowed_vector_row_ids(
        datasets,
        vector_hits,
        filters=normalized_filters,
        filter_operators=normalized_filter_operators,
    )
    lexical_rows = _profile_lexical_rows(
        datasets,
        query=normalized_query,
        filters=normalized_filters,
        filter_operators=normalized_filter_operators,
        limit=normalized_limit,
    )
    candidates = _dataset_search_candidates(
        vector_hits=vector_hits,
        lexical_rows=lexical_rows,
        allowed_row_ids=allowed_row_ids,
    )
    ranked_candidates = _rank_dataset_search_candidates(candidates, limit=normalized_limit)
    results = _serialize_profile_row_search_results(ranked_candidates)
    results = _sort_profile_row_search_results(
        results,
        sort=normalized_sort,
        direction=normalized_direction,
    )
    hydration_misses = len(ranked_candidates) - len(results)
    top_result = results[0] if results else None
    logger.info(
        "Profile row hybrid search complete",
        query_id=query_id,
        profile_id=profile.id,
        dataset_filters=dataset_filters,
        dataset_filter_count=len(dataset_filters),
        eligible_dataset_count=len(datasets),
        filters_count=len(normalized_filters),
        limit=normalized_limit,
        sort=normalized_sort,
        direction=normalized_direction,
        vector_hit_count=len(vector_hits),
        lexical_candidate_count=len(lexical_rows),
        fused_candidate_count=len(ranked_candidates),
        result_count=len(results),
        hydration_misses=hydration_misses,
        top_source=top_result["match"]["source"] if top_result else "",
        top_score=round(top_result["score"], 6) if top_result else None,
        top_vector_score=(
            round(top_result["match"]["vector_score"], 6)
            if top_result and top_result["match"]["vector_score"] is not None
            else None
        ),
        embedding_model=vector_search.embedding_model,
        embedding_dimensions=vector_search.embedding_dimensions,
        embedding_latency_ms=round(vector_search.embedding_latency_ms, 2),
        vector_latency_ms=round(vector_search.vector_latency_ms, 2),
        search_latency_ms=round((perf_counter() - search_started_at) * 1000, 2),
    )

    return {
        "query": normalized_query,
        "filters": normalized_filters,
        "filter_operators": normalized_filter_operators,
        "dataset_filters": dataset_filters,
        "sort": normalized_sort,
        "direction": normalized_direction,
        "limit": normalized_limit,
        "count": len(results),
        "results": results,
    }


def search_profile_dataset_rows(
    profile: Profile,
    dataset_key: str,
    *,
    query: str,
    filters: dict[str, Any] | None = None,
    limit: int = 10,
    embedding_provider: EmbeddingProvider | None = None,
    vector_store: QdrantVectorStore | None = None,
) -> dict:
    query_id = uuid4().hex
    search_started_at = perf_counter()
    dataset = get_ready_profile_dataset(profile, dataset_key)
    normalized_query = _normalize_search_query(query)
    if not normalized_query:
        raise DatasetServiceError(400, "Search query is required.")
    normalized_limit = _normalize_dataset_search_limit(limit)
    filtered_queryset, row_query, lexical_queryset = _dataset_search_querysets(
        dataset,
        query=normalized_query,
        filters=filters,
    )
    vector_search = _dataset_vector_search_hits(
        dataset,
        query=normalized_query,
        limit=normalized_limit,
        embedding_provider=embedding_provider,
        vector_store=vector_store,
    )
    vector_hits = vector_search.hits

    allowed_row_ids: set[int] | None = None
    if row_query["filters"]:
        vector_row_ids = [
            row_id
            for row_id in (_safe_vector_row_id(hit.payload) for hit in vector_hits)
            if row_id is not None
        ]
        allowed_row_ids = (
            set(filtered_queryset.filter(id__in=vector_row_ids).values_list("id", flat=True))
            if vector_row_ids
            else set()
        )

    lexical_rows = list(lexical_queryset.only("id")[: normalized_limit * 3])
    candidates = _dataset_search_candidates(
        vector_hits=vector_hits,
        lexical_rows=lexical_rows,
        allowed_row_ids=allowed_row_ids,
    )
    ranked_candidates = _rank_dataset_search_candidates(candidates, limit=normalized_limit)
    results = _serialize_dataset_search_results(dataset, ranked_candidates)
    hydration_misses = len(ranked_candidates) - len(results)
    top_result = results[0] if results else None
    logger.info(
        "Dataset hybrid search complete",
        query_id=query_id,
        profile_id=profile.id,
        dataset_id=dataset.id,
        dataset_key=str(dataset.key),
        filters_count=len(row_query["filters"]),
        limit=normalized_limit,
        vector_hit_count=len(vector_hits),
        lexical_candidate_count=len(lexical_rows),
        fused_candidate_count=len(ranked_candidates),
        result_count=len(results),
        hydration_misses=hydration_misses,
        top_source=top_result["match"]["source"] if top_result else "",
        top_score=round(top_result["score"], 6) if top_result else None,
        top_vector_score=(
            round(top_result["match"]["vector_score"], 6)
            if top_result and top_result["match"]["vector_score"] is not None
            else None
        ),
        embedding_model=vector_search.embedding_model,
        embedding_dimensions=vector_search.embedding_dimensions,
        embedding_latency_ms=round(vector_search.embedding_latency_ms, 2),
        vector_latency_ms=round(vector_search.vector_latency_ms, 2),
        search_latency_ms=round((perf_counter() - search_started_at) * 1000, 2),
    )

    return {
        "dataset": str(dataset.key),
        "query": normalized_query,
        "filters": row_query["filters"],
        "limit": normalized_limit,
        "count": len(results),
        "results": results,
    }


def list_profile_dataset_rows(
    profile: Profile,
    dataset_key: str,
    limit: int = 100,
    offset: int = 0,
    query: str | None = None,
    filters: dict[str, Any] | None = None,
    sort: str | None = None,
    direction: str | None = None,
) -> dict:
    dataset = get_ready_profile_dataset(profile, dataset_key)
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    total_count = dataset.rows.count()
    try:
        row_queryset, row_query = apply_dataset_row_query(
            dataset.rows.all(),
            dataset,
            query=query,
            filters=filters,
            sort=sort,
            direction=direction,
            strict=True,
        )
    except DatasetRowQueryError as exc:
        raise DatasetServiceError(400, str(exc)) from exc

    has_restrictive_query = bool(row_query["query"] or row_query["filters"])
    filtered_count = row_queryset.count() if has_restrictive_query else total_count
    rows = list(row_queryset.prefetch_related("assets")[offset : offset + limit])
    return {
        "dataset": str(dataset.key),
        "count": filtered_count,
        "total_count": total_count,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(rows) < filtered_count,
        "query": row_query["query"],
        "filters": row_query["filters"],
        "sort": row_query["sort"],
        "direction": row_query["direction"],
        "rows": [serialize_dataset_row(row, dataset=dataset) for row in rows],
    }


def create_profile_dataset_row(
    profile: Profile,
    dataset_key: str,
    data: RowWritePayload,
    agent_api_key: AgentApiKey | None = None,
) -> dict:
    with transaction.atomic():
        quota_profile = _lock_profile_for_quota(profile)
        dataset = get_ready_profile_dataset_for_update(profile, dataset_key)
        _enforce_dataset_row_create_quota(quota_profile, dataset)

        last_row_number = (
            dataset.rows.order_by("-row_number").values_list("row_number", flat=True).first() or 0
        )
        row_number = last_row_number + 1
        if dataset.index_generated:
            row_data = {**data, dataset.index_column: str(row_number)}
        else:
            row_data = data

        serialized_data = normalize_row_data_for_headers(row_data, dataset.headers)
        _validate_choice_row_data(dataset.headers, dataset.column_schema, serialized_data)
        _validate_image_row_data(dataset.headers, dataset.column_schema, serialized_data)
        serialized_data = _normalize_reference_row_data(
            profile,
            dataset.headers,
            dataset.column_schema,
            serialized_data,
        )
        index_value = str(serialized_data.get(dataset.index_column, "")).strip()
        if not index_value:
            raise DatasetServiceError(
                400,
                f"Index column '{dataset.index_column}' is required.",
            )
        if dataset.rows.filter(index_value=index_value).exists():
            raise DatasetServiceError(409, f"Row with index '{index_value}' already exists.")
        _validate_relationship_row_data(dataset, serialized_data)

        row = DatasetRow.objects.create(
            dataset=dataset,
            created_by_agent_api_key=agent_api_key,
            updated_by_agent_api_key=agent_api_key,
            row_number=row_number,
            index_value=index_value,
            data=serialized_data,
        )
        dataset.row_count = dataset.rows.count()
        dataset.updated_by_agent_api_key = agent_api_key
        dataset.save(update_fields=["row_count", "updated_by_agent_api_key", "updated_at"])
        is_first_row_mutation = not _profile_has_row_mutation(profile)
        record_dataset_mutation(
            dataset,
            DatasetMutationType.ROW_CREATED,
            f"Row {row.row_number} added.",
            agent_api_key=agent_api_key,
            target_type="row",
            target_identifier=row.id,
            metadata={
                "row_id": row.id,
                "row_number": row.row_number,
                "changed_fields": sorted(row.data),
            },
        )
        _track_dataset_row_mutation(
            profile=profile,
            dataset=dataset,
            mutation_type=DatasetMutationType.ROW_CREATED,
            agent_api_key=agent_api_key,
            is_first_row_mutation=is_first_row_mutation,
            changed_field_count=len(row.data),
        )
        _enqueue_dataset_row_vector_index(row.id)
        row = dataset.rows.prefetch_related("assets").get(id=row.id)
    return {
        "status": "success",
        "message": "Row created.",
        "dataset": str(dataset.key),
        "row": serialize_dataset_row(row, dataset=dataset),
    }


def get_profile_dataset_row(profile: Profile, dataset_key: str, row_id: int) -> dict:
    dataset = get_ready_profile_dataset(profile, dataset_key)
    try:
        row = dataset.rows.prefetch_related("assets").get(id=row_id)
    except DatasetRow.DoesNotExist as exc:
        raise DatasetServiceError(404, "Row not found.") from exc
    return {
        "status": "success",
        "message": "Row retrieved.",
        "dataset": str(dataset.key),
        "row": serialize_dataset_row(row, dataset=dataset),
    }


def get_profile_dataset_row_by_index(profile: Profile, dataset_key: str, index_value: str) -> dict:
    dataset = get_ready_profile_dataset(profile, dataset_key)
    try:
        row = dataset.rows.prefetch_related("assets").get(index_value=index_value)
    except DatasetRow.DoesNotExist as exc:
        raise DatasetServiceError(404, "Row not found.") from exc
    return {
        "status": "success",
        "message": "Row retrieved.",
        "dataset": str(dataset.key),
        "row": serialize_dataset_row(row, dataset=dataset),
    }


def patch_profile_dataset_row(
    profile: Profile,
    dataset_key: str,
    row_id: int,
    data: RowWritePayload,
    agent_api_key: AgentApiKey | None = None,
) -> dict:
    with transaction.atomic():
        dataset = get_ready_profile_dataset_for_update(profile, dataset_key)
        try:
            row = dataset.rows.get(id=row_id)
        except DatasetRow.DoesNotExist as exc:
            raise DatasetServiceError(404, "Row not found.") from exc
        return _patch_dataset_row(
            profile,
            dataset,
            row,
            data,
            agent_api_key=agent_api_key,
        )


def patch_profile_dataset_row_by_index(
    profile: Profile,
    dataset_key: str,
    index_value: str,
    data: RowWritePayload,
    agent_api_key: AgentApiKey | None = None,
) -> dict:
    with transaction.atomic():
        dataset = get_ready_profile_dataset_for_update(profile, dataset_key)
        try:
            row = dataset.rows.get(index_value=index_value)
        except DatasetRow.DoesNotExist as exc:
            raise DatasetServiceError(404, "Row not found.") from exc
        return _patch_dataset_row(
            profile,
            dataset,
            row,
            data,
            agent_api_key=agent_api_key,
        )


def _patch_dataset_row(
    profile: Profile,
    dataset: Dataset,
    row: DatasetRow,
    data: RowWritePayload,
    agent_api_key: AgentApiKey | None = None,
) -> dict:
    if not connection.in_atomic_block:
        raise AssertionError("_patch_dataset_row must be called inside transaction.atomic().")

    row_patch = normalize_row_patch_for_headers(data, dataset.headers)
    patched_fields = sorted(row_patch)
    image_columns = set(image_columns_from_schema(dataset.headers, dataset.column_schema))
    changed_image_columns = [
        field
        for field in patched_fields
        if field in image_columns
        and row_patch.get(field, "") != str((row.data or {}).get(field, "") or "")
    ]
    invalid_image_asset_ref_columns = [
        field
        for field in changed_image_columns
        if dataset_asset_key_from_ref(row_patch.get(field, ""))
    ]
    if invalid_image_asset_ref_columns:
        column = invalid_image_asset_ref_columns[0]
        raise DatasetServiceError(
            400,
            f"Column '{column}' is an image column. Attach a new image asset instead.",
        )
    _validate_image_row_data(
        dataset.headers,
        dataset.column_schema,
        row_patch,
        columns=changed_image_columns,
    )
    cleared_image_columns = [
        field
        for field in changed_image_columns
        if field in image_columns and row_patch.get(field, "") == ""
    ]
    row_patch = _normalize_reference_row_data(
        profile,
        dataset.headers,
        dataset.column_schema,
        row_patch,
        columns=patched_fields,
    )
    _validate_choice_row_data(
        dataset.headers,
        dataset.column_schema,
        row_patch,
        columns=patched_fields,
    )
    field_changes = _row_field_changes(row.data or {}, row_patch, patched_fields)
    changed_fields = [str(change["field"]) for change in field_changes]
    row.data = {**row.data, **row_patch}
    index_changed = False
    if dataset.index_column in data:
        index_value = str(row_patch.get(dataset.index_column, "")).strip()
        if dataset.index_generated:
            if index_value != row.index_value:
                raise DatasetServiceError(
                    400,
                    f"Index column '{dataset.index_column}' is managed by Rowset "
                    "and cannot be updated.",
                )
        if not index_value:
            raise DatasetServiceError(
                400,
                f"Index column '{dataset.index_column}' cannot be blank.",
            )
        if dataset.rows.exclude(id=row.id).filter(index_value=index_value).exists():
            raise DatasetServiceError(409, f"Row with index '{index_value}' already exists.")
        index_changed = row.index_value != index_value
        if index_changed:
            _raise_if_target_row_is_referenced(dataset, row.index_value)
        row.index_value = index_value
    _validate_relationship_row_data(dataset, row.data, columns=patched_fields)
    if cleared_image_columns:
        DatasetAsset.objects.filter(
            dataset=dataset,
            row=row,
            column_name__in=cleared_image_columns,
        ).delete()
    row.updated_by_agent_api_key = agent_api_key
    row.save(update_fields=["data", "index_value", "updated_by_agent_api_key", "updated_at"])
    dataset.updated_by_agent_api_key = agent_api_key
    dataset.save(update_fields=["updated_by_agent_api_key", "updated_at"])
    is_first_row_mutation = not _profile_has_row_mutation(profile)
    record_dataset_mutation(
        dataset,
        DatasetMutationType.ROW_UPDATED,
        f"Row {row.row_number} updated.",
        agent_api_key=agent_api_key,
        target_type="row",
        target_identifier=row.id,
        metadata={
            "row_id": row.id,
            "row_number": row.row_number,
            "changed_fields": changed_fields,
            # Authenticated change history intentionally retains row diff values.
            # Any future erasure flow must account for this audit metadata too.
            "field_changes": field_changes,
            "value_changes_recorded": True,
            "index_changed": index_changed,
        },
    )
    _track_dataset_row_mutation(
        profile=profile,
        dataset=dataset,
        mutation_type=DatasetMutationType.ROW_UPDATED,
        agent_api_key=agent_api_key,
        is_first_row_mutation=is_first_row_mutation,
        changed_field_count=len(changed_fields),
        index_changed=index_changed,
    )
    _enqueue_dataset_row_vector_index(row.id)
    row = dataset.rows.prefetch_related("assets").get(id=row.id)
    return {
        "status": "success",
        "message": "Row updated.",
        "dataset": str(dataset.key),
        "row": serialize_dataset_row(row, dataset=dataset),
    }


def delete_profile_dataset_row(
    profile: Profile,
    dataset_key: str,
    row_id: int,
    agent_api_key: AgentApiKey | None = None,
) -> dict:
    with transaction.atomic():
        dataset = get_ready_profile_dataset_for_update(profile, dataset_key)
        try:
            row = dataset.rows.get(id=row_id)
        except DatasetRow.DoesNotExist as exc:
            raise DatasetServiceError(404, "Row not found.") from exc
        row_number = row.row_number
        _raise_if_target_row_is_referenced(dataset, row.index_value)
        row.delete()
        dataset.row_count = dataset.rows.count()
        dataset.updated_by_agent_api_key = agent_api_key
        dataset.save(update_fields=["row_count", "updated_by_agent_api_key", "updated_at"])
        is_first_row_mutation = not _profile_has_row_mutation(profile)
        record_dataset_mutation(
            dataset,
            DatasetMutationType.ROW_DELETED,
            f"Row {row_number} deleted.",
            agent_api_key=agent_api_key,
            target_type="row",
            target_identifier=row_id,
            metadata={
                "row_id": row_id,
                "row_number": row_number,
            },
        )
        _track_dataset_row_mutation(
            profile=profile,
            dataset=dataset,
            mutation_type=DatasetMutationType.ROW_DELETED,
            agent_api_key=agent_api_key,
            is_first_row_mutation=is_first_row_mutation,
            deleted_count=1,
        )
        _enqueue_dataset_row_vector_delete(dataset.id, [row_id])
    return {"status": "success", "message": "Row deleted.", "dataset": str(dataset.key)}


def delete_profile_dataset_rows(
    profile: Profile,
    dataset_key: str,
    row_ids: Iterable[int | str],
    agent_api_key: AgentApiKey | None = None,
) -> dict:
    ordered_row_ids: list[int] = []
    seen_row_ids: set[int] = set()
    for row_id in row_ids:
        try:
            normalized_row_id = int(row_id)
        except (TypeError, ValueError) as exc:
            raise DatasetServiceError(400, "Row IDs must be integers.") from exc
        if normalized_row_id in seen_row_ids:
            continue
        seen_row_ids.add(normalized_row_id)
        ordered_row_ids.append(normalized_row_id)

    if not ordered_row_ids:
        raise DatasetServiceError(400, "Select at least one row.")

    with transaction.atomic():
        dataset = get_ready_profile_dataset_for_update(profile, dataset_key)
        rows_by_id = {row.id: row for row in dataset.rows.filter(id__in=ordered_row_ids)}
        ordered_rows = []
        for row_id in ordered_row_ids:
            row = rows_by_id.get(row_id)
            if row is None:
                raise DatasetServiceError(404, "Row not found.")
            ordered_rows.append(row)

        for row in ordered_rows:
            _raise_if_target_row_is_referenced(dataset, row.index_value)

        deleted_rows = [(row.id, row.row_number) for row in ordered_rows]
        dataset.rows.filter(id__in=ordered_row_ids).delete()
        dataset.row_count = dataset.rows.count()
        dataset.updated_by_agent_api_key = agent_api_key
        dataset.save(update_fields=["row_count", "updated_by_agent_api_key", "updated_at"])
        is_first_row_mutation = not _profile_has_row_mutation(profile)
        for row_id, row_number in deleted_rows:
            record_dataset_mutation(
                dataset,
                DatasetMutationType.ROW_DELETED,
                f"Row {row_number} deleted.",
                agent_api_key=agent_api_key,
                target_type="row",
                target_identifier=row_id,
                metadata={
                    "row_id": row_id,
                    "row_number": row_number,
                },
            )
        _track_dataset_row_mutation(
            profile=profile,
            dataset=dataset,
            mutation_type=DatasetMutationType.ROW_DELETED,
            agent_api_key=agent_api_key,
            is_first_row_mutation=is_first_row_mutation,
            deleted_count=len(deleted_rows),
        )
        _enqueue_dataset_row_vector_delete(dataset.id, [row_id for row_id, _ in deleted_rows])

    row_label = "row" if len(deleted_rows) == 1 else "rows"
    return {
        "status": "success",
        "message": f"Deleted {len(deleted_rows)} {row_label}.",
        "dataset": str(dataset.key),
        "deleted_count": len(deleted_rows),
    }
