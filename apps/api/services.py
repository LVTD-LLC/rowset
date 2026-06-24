import json
from datetime import UTC, date, datetime, time
from typing import Any
from urllib.parse import unquote, urlparse
from uuid import UUID

from django.contrib.auth.hashers import make_password
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.models import Count, Q
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from apps.core.models import AgentApiKey, Profile
from apps.datasets.choices import DatasetMutationType, DatasetStatus
from apps.datasets.constants import (
    MAX_DATASET_DESCRIPTION_LENGTH,
    MAX_DATASET_INSTRUCTIONS_LENGTH,
    MAX_DATASET_METADATA_BYTES,
)
from apps.datasets.history import record_dataset_mutation
from apps.datasets.models import Dataset, DatasetRow, Project
from apps.datasets.services import (
    CSVParseError,
    DatasetRowQueryError,
    apply_dataset_row_query,
    choice_constraints_from_schema,
    generated_index_column_name,
    generated_index_column_schema,
    infer_column_schema,
    invalid_choice_values_by_column,
    normalize_column_schema,
    normalize_public_page_size,
    validate_choice_row_values,
    validate_headers,
)
from filebridge.utils import build_absolute_public_url

API_CREATED_FILE_TYPE = "api"
MAX_API_DATASET_CREATE_ROWS = 1000
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


def _active_dataset_queryset(queryset):
    return queryset.filter(archived_at__isnull=True)


class DatasetServiceError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(message)


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


def serialize_project_reference(project: Project | None) -> dict | None:
    """Return the project fields embedded in dataset metadata."""
    if project is None:
        return None
    return {
        "key": str(project.key),
        "name": project.name,
        "description": project.description,
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
        "dataset_count": dataset_count,
        "created_at": project.created_at,
        "updated_at": project.updated_at,
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
    queryset = profile.projects.annotate(dataset_count=_visible_project_dataset_count()).only(
        "key",
        "name",
        "description",
        "created_at",
        "updated_at",
    )
    if normalized_query:
        queryset = queryset.filter(
            Q(name__icontains=normalized_query) | Q(description__icontains=normalized_query)
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


def create_profile_project(profile: Profile, *, name: str, description: str | None = None) -> dict:
    """Create a semantic dataset group for an authenticated profile."""
    normalized_name = _normalize_project_name(name)
    normalized_description = _normalize_project_description(description)
    if Project.objects.filter(profile=profile, name__iexact=normalized_name).exists():
        raise DatasetServiceError(409, "Project name already exists.")

    try:
        project = Project.objects.create(
            profile=profile,
            name=normalized_name,
            description=normalized_description,
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
            project = (
                Project.objects.select_for_update()
                .get(key=project_key, profile=profile)
            )
        except (Project.DoesNotExist, ValidationError, ValueError) as exc:
            raise DatasetServiceError(404, "Project not found.") from exc

        update_fields = []
        if normalized_name is not UNSET and project.name != normalized_name:
            if (
                Project.objects.filter(profile=profile, name__iexact=normalized_name)
                .exclude(pk=project.pk)
                .exists()
            ):
                raise DatasetServiceError(409, "Project name already exists.")
            project.name = normalized_name
            update_fields.append("name")

        if (
            normalized_description is not UNSET
            and project.description != normalized_description
        ):
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
            Project.objects.annotate(dataset_count=_visible_project_dataset_count())
            .only("key", "name", "description", "created_at", "updated_at")
            .get(key=project_key, profile=profile)
        )
    except (Project.DoesNotExist, ValidationError, ValueError) as exc:
        raise DatasetServiceError(404, "Project not found.") from exc


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
    total_count = project.dataset_count
    datasets = list(queryset[offset : offset + limit])
    return {
        "status": "success",
        "message": "Project retrieved.",
        "project": serialize_project_summary(project),
        "datasets": {
            "count": len(datasets),
            "total_count": total_count,
            "limit": limit,
            "offset": offset,
            "has_more": offset + len(datasets) < total_count,
            "datasets": [serialize_dataset_summary(dataset) for dataset in datasets],
        },
    }


def serialize_dataset_summary(dataset: Dataset) -> dict:
    """Return machine-friendly dataset metadata without row payloads."""
    return {
        "key": str(dataset.key),
        "name": dataset.name,
        "description": dataset.description,
        "instructions": dataset.instructions,
        "metadata": dataset.metadata or {},
        "project": serialize_project_reference(getattr(dataset, "project", None)),
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
        "public_url": build_absolute_public_url(dataset.get_public_url()),
        "public_page_size": dataset.public_page_size,
        "public_password_protected": dataset.is_public_password_protected,
        "created_at": dataset.created_at,
        "updated_at": dataset.updated_at,
        "confirmed_at": dataset.confirmed_at,
        "processed_at": dataset.processed_at,
        "archived_at": dataset.archived_at,
    }


def _dataset_summary_queryset(queryset):
    return queryset.select_related("project").only(*DATASET_SUMMARY_ONLY_FIELDS)


def search_profile_datasets(
    profile: Profile,
    *,
    query: str | None = None,
    project_key: str | None = None,
    header_contains: str | None = None,
    status: str | None = None,
    updated_after: str | date | datetime | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    """
    Return a bounded, optionally filtered page of datasets owned by the profile.

    Query text matches dataset name, original filename, and assigned project metadata.
    Ungrouped datasets match only on dataset fields because they have no project metadata.
    """
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    normalized_query = _normalize_search_query(query)
    normalized_project_key = str(project_key or "").strip()
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
            | Q(project__name__icontains=normalized_query)
            | Q(project__description__icontains=normalized_query)
        )
    if normalized_project_key:
        try:
            project_key_uuid = UUID(normalized_project_key)
        except ValueError as exc:
            raise DatasetServiceError(400, "project_key must be a valid UUID.") from exc
        else:
            queryset = queryset.filter(project__key=project_key_uuid)
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
        Dataset.objects.select_related("project"),
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


def _stringify_cell(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _mutation_value_label(value: str, non_blank_label: str) -> str:
    if value == "":
        return "Blank"
    return non_blank_label


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
                "before": _mutation_value_label(before_value, "Previous value"),
                "after": _mutation_value_label(after_value, "New value"),
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
    if metadata is None:
        return {}
    if not isinstance(metadata, dict):
        raise DatasetServiceError(400, "Dataset metadata must be a JSON object.")

    for key in metadata:
        if not isinstance(key, str) or not key.strip():
            raise DatasetServiceError(
                400,
                "Dataset metadata keys must be non-empty strings.",
            )

    try:
        serialized_metadata = json.dumps(
            metadata,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise DatasetServiceError(400, "Dataset metadata must be JSON serializable.") from exc

    if len(serialized_metadata.encode("utf-8")) > MAX_DATASET_METADATA_BYTES:
        raise DatasetServiceError(
            400,
            f"Dataset metadata must be {MAX_DATASET_METADATA_BYTES} bytes or fewer.",
        )

    return metadata


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
        validate_choice_row_values(
            headers,
            column_schema,
            row_data,
            columns=columns,
            choice_constraints=constraints,
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


def _iter_dataset_row_data(dataset: Dataset):
    yield from dataset.rows.order_by("row_number", "id").values_list("data", flat=True).iterator(
        chunk_size=1000
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

    now = timezone.now()
    with transaction.atomic():
        dataset = Dataset.objects.create(
            profile=profile,
            project=project,
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
            },
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
        _validate_existing_choice_values(dataset, next_schema)
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
        _validate_choice_row_data(
            next_headers,
            dataset.column_schema,
            {column_name: default_cell},
            columns={column_name},
        )

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
    agent_api_key: AgentApiKey | None = None,
) -> dict:
    """Attach an existing dataset to a project owned by the profile, or detach it."""
    normalized_project_key = str(project_key or "").strip()
    project = (
        get_profile_project(profile, normalized_project_key) if normalized_project_key else None
    )

    with transaction.atomic():
        dataset = _get_profile_dataset_from_queryset(
            Dataset.objects.select_for_update(),
            profile,
            dataset_key,
        )

        _raise_if_archived(dataset)

        previous_project_key = str(dataset.project.key) if dataset.project else ""
        previous_project_name = dataset.project.name if dataset.project else ""
        dataset.project = project
        dataset.updated_by_agent_api_key = agent_api_key
        dataset.save(update_fields=["project", "updated_by_agent_api_key", "updated_at"])
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
                "project_key": str(project.key) if project else "",
                "project_name": project.name if project else "",
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

    return {
        "status": "success",
        "message": message,
        "dataset": serialize_dataset_summary(dataset),
    }


def serialize_dataset_row(row: DatasetRow) -> dict:
    return {
        "id": row.id,
        "row_number": row.row_number,
        "index_value": row.index_value,
        "data": row.data,
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
    rows = list(row_queryset[offset : offset + limit])
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
        "rows": [serialize_dataset_row(row) for row in rows],
    }


def create_profile_dataset_row(
    profile: Profile,
    dataset_key: str,
    data: dict,
    agent_api_key: AgentApiKey | None = None,
) -> dict:
    with transaction.atomic():
        dataset = get_ready_profile_dataset_for_update(profile, dataset_key)

        last_row_number = (
            dataset.rows.order_by("-row_number").values_list("row_number", flat=True).first() or 0
        )
        row_number = last_row_number + 1
        if dataset.index_generated:
            index_value = str(row_number)
            row_data = {**data, dataset.index_column: index_value}
        else:
            index_value = str(data.get(dataset.index_column, "")).strip()
            if not index_value:
                raise DatasetServiceError(
                    400,
                    f"Index column '{dataset.index_column}' is required.",
                )
            row_data = data

        if dataset.rows.filter(index_value=index_value).exists():
            raise DatasetServiceError(409, f"Row with index '{index_value}' already exists.")
        serialized_data = {header: str(row_data.get(header, "")) for header in dataset.headers}
        _validate_choice_row_data(dataset.headers, dataset.column_schema, serialized_data)

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
    return {
        "status": "success",
        "message": "Row created.",
        "dataset": str(dataset.key),
        "row": serialize_dataset_row(row),
    }


def get_profile_dataset_row(profile: Profile, dataset_key: str, row_id: int) -> dict:
    dataset = get_ready_profile_dataset(profile, dataset_key)
    try:
        row = dataset.rows.get(id=row_id)
    except DatasetRow.DoesNotExist as exc:
        raise DatasetServiceError(404, "Row not found.") from exc
    return {
        "status": "success",
        "message": "Row retrieved.",
        "dataset": str(dataset.key),
        "row": serialize_dataset_row(row),
    }


def get_profile_dataset_row_by_index(profile: Profile, dataset_key: str, index_value: str) -> dict:
    dataset = get_ready_profile_dataset(profile, dataset_key)
    try:
        row = dataset.rows.get(index_value=index_value)
    except DatasetRow.DoesNotExist as exc:
        raise DatasetServiceError(404, "Row not found.") from exc
    return {
        "status": "success",
        "message": "Row retrieved.",
        "dataset": str(dataset.key),
        "row": serialize_dataset_row(row),
    }


def patch_profile_dataset_row(
    profile: Profile,
    dataset_key: str,
    row_id: int,
    data: dict,
    agent_api_key: AgentApiKey | None = None,
) -> dict:
    with transaction.atomic():
        dataset = get_ready_profile_dataset_for_update(profile, dataset_key)
        try:
            row = dataset.rows.get(id=row_id)
        except DatasetRow.DoesNotExist as exc:
            raise DatasetServiceError(404, "Row not found.") from exc
        return _patch_dataset_row(
            dataset,
            row,
            data,
            agent_api_key=agent_api_key,
        )


def patch_profile_dataset_row_by_index(
    profile: Profile,
    dataset_key: str,
    index_value: str,
    data: dict,
    agent_api_key: AgentApiKey | None = None,
) -> dict:
    with transaction.atomic():
        dataset = get_ready_profile_dataset_for_update(profile, dataset_key)
        try:
            row = dataset.rows.get(index_value=index_value)
        except DatasetRow.DoesNotExist as exc:
            raise DatasetServiceError(404, "Row not found.") from exc
        return _patch_dataset_row(
            dataset,
            row,
            data,
            agent_api_key=agent_api_key,
        )


def _patch_dataset_row(
    dataset: Dataset,
    row: DatasetRow,
    data: dict,
    agent_api_key: AgentApiKey | None = None,
) -> dict:
    if not connection.in_atomic_block:
        raise AssertionError("_patch_dataset_row must be called inside transaction.atomic().")

    row_patch = {key: str(value) for key, value in data.items() if key in dataset.headers}
    patched_fields = sorted(row_patch)
    field_changes = _row_field_changes(row.data or {}, row_patch, patched_fields)
    changed_fields = [str(change["field"]) for change in field_changes]
    row.data = {**row.data, **row_patch}
    _validate_choice_row_data(
        dataset.headers,
        dataset.column_schema,
        row.data,
        columns=patched_fields,
    )
    index_changed = False
    if dataset.index_column in data:
        if dataset.index_generated:
            raise DatasetServiceError(
                400,
                f"Index column '{dataset.index_column}' is managed by Rowset "
                "and cannot be updated.",
            )
        index_value = str(data.get(dataset.index_column, "")).strip()
        if not index_value:
            raise DatasetServiceError(
                400,
                f"Index column '{dataset.index_column}' cannot be blank.",
            )
        if dataset.rows.exclude(id=row.id).filter(index_value=index_value).exists():
            raise DatasetServiceError(409, f"Row with index '{index_value}' already exists.")
        index_changed = row.index_value != index_value
        row.index_value = index_value
    row.updated_by_agent_api_key = agent_api_key
    row.save(update_fields=["data", "index_value", "updated_by_agent_api_key", "updated_at"])
    dataset.updated_by_agent_api_key = agent_api_key
    dataset.save(update_fields=["updated_by_agent_api_key", "updated_at"])
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
            "field_changes": field_changes,
            "index_changed": index_changed,
        },
    )
    return {
        "status": "success",
        "message": "Row updated.",
        "dataset": str(dataset.key),
        "row": serialize_dataset_row(row),
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
        row.delete()
        dataset.row_count = dataset.rows.count()
        dataset.updated_by_agent_api_key = agent_api_key
        dataset.save(update_fields=["row_count", "updated_by_agent_api_key", "updated_at"])
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
    return {"status": "success", "message": "Row deleted.", "dataset": str(dataset.key)}
