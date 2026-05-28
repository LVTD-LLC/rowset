from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.core.models import Profile
from apps.datasets.choices import DatasetStatus
from apps.datasets.google_sheets import GoogleSheetsSyncError, sync_dataset_to_google_sheet
from apps.datasets.models import Dataset, DatasetRow
from apps.datasets.services import (
    GOOGLE_SHEETS_FILE_TYPE,
    CSVParseError,
    generated_index_column_name,
    validate_headers,
)

API_CREATED_FILE_TYPE = "api"
MAX_API_DATASET_CREATE_ROWS = 1000


class DatasetServiceError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(message)


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


def serialize_dataset_summary(dataset: Dataset) -> dict:
    """Return machine-friendly dataset metadata without row payloads."""
    return {
        "key": str(dataset.key),
        "name": dataset.name,
        "original_filename": dataset.original_filename,
        "file_type": dataset.file_type,
        "status": dataset.status,
        "headers": dataset.headers,
        "index_column": dataset.index_column,
        "index_generated": dataset.index_generated,
        "row_count": dataset.row_count,
        "public_enabled": dataset.public_enabled,
        "created_at": dataset.created_at,
        "updated_at": dataset.updated_at,
        "confirmed_at": dataset.confirmed_at,
        "processed_at": dataset.processed_at,
    }


def serialize_profile_datasets(profile: Profile, limit: int = 100, offset: int = 0) -> dict:
    """Return a bounded page of datasets owned by the authenticated profile."""
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    queryset = profile.datasets.only(
        "key",
        "name",
        "original_filename",
        "file_type",
        "status",
        "headers",
        "index_column",
        "index_generated",
        "row_count",
        "public_enabled",
        "created_at",
        "updated_at",
        "confirmed_at",
        "processed_at",
    )
    total_count = queryset.count()
    datasets = list(queryset[offset : offset + limit])
    return {
        "count": len(datasets),
        "total_count": total_count,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(datasets) < total_count,
        "datasets": [serialize_dataset_summary(dataset) for dataset in datasets],
    }


def get_profile_dataset(profile: Profile, dataset_key: str) -> Dataset:
    try:
        return Dataset.objects.get(key=dataset_key, profile=profile)
    except Dataset.DoesNotExist as exc:
        raise DatasetServiceError(404, "Dataset not found.") from exc


def get_ready_profile_dataset(profile: Profile, dataset_key: str) -> Dataset:
    dataset = get_profile_dataset(profile, dataset_key)
    if dataset.status != DatasetStatus.READY:
        raise DatasetServiceError(
            409,
            "Dataset is not ready yet. Confirm and wait for import first.",
        )
    return dataset


def get_ready_profile_dataset_for_update(profile: Profile, dataset_key: str) -> Dataset:
    try:
        dataset = Dataset.objects.select_for_update().get(key=dataset_key, profile=profile)
    except Dataset.DoesNotExist as exc:
        raise DatasetServiceError(404, "Dataset not found.") from exc
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


def _normalize_dataset_name(name: str) -> str:
    normalized_name = (name or "").strip()
    if not normalized_name:
        raise DatasetServiceError(400, "Dataset name is required.")
    if len(normalized_name) > 255:
        raise DatasetServiceError(400, "Dataset name must be 255 characters or fewer.")
    return normalized_name


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
    for row in rows:
        for header in row:
            if header not in headers:
                headers.append(header)
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


def create_profile_dataset(
    profile: Profile,
    *,
    name: str,
    headers: list[str] | None = None,
    rows: list[dict[str, Any]] | None = None,
    index_column: str | None = None,
) -> dict:
    """Create a ready API-backed dataset for an authenticated profile."""
    normalized_name = _normalize_dataset_name(name)
    normalized_rows = _normalize_create_rows(rows)
    base_headers = _normalize_create_headers(headers, normalized_rows)
    _validate_rows_match_headers(normalized_rows, base_headers)
    index_column, index_generated, dataset_headers = _create_dataset_index_config(
        base_headers,
        index_column,
    )

    seen_index_values = set()
    row_payloads = []
    for row_number, row_data in enumerate(normalized_rows, start=1):
        if index_generated:
            index_value = str(row_number)
            serialized_data = {
                **{header: row_data.get(header, "") for header in dataset_headers},
                index_column: index_value,
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
            name=normalized_name,
            original_filename="Created via API",
            file_type=API_CREATED_FILE_TYPE,
            status=DatasetStatus.READY,
            headers=dataset_headers,
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
                    row_number=row_number,
                    index_value=index_value,
                    data=data,
                )
                for row_number, index_value, data in row_payloads
            ],
            batch_size=1000,
        )

    return {
        "status": "success",
        "message": "Dataset created.",
        "dataset": serialize_dataset_summary(dataset),
    }


def serialize_dataset_row(row: DatasetRow) -> dict:
    return {
        "id": row.id,
        "row_number": row.row_number,
        "index_value": row.index_value,
        "data": row.data,
    }


def sync_dataset_source(dataset: Dataset) -> dict | None:
    if dataset.file_type != GOOGLE_SHEETS_FILE_TYPE:
        return None

    try:
        status = sync_dataset_to_google_sheet(dataset)
    except GoogleSheetsSyncError as exc:
        return {"status": "failed", "message": str(exc)}
    if status == "skipped":
        return None
    return {"status": "synced", "message": "Google Sheets source updated."}


def add_source_sync_result(result: dict, source_sync: dict | None) -> dict:
    if not source_sync or source_sync["status"] == "synced":
        return result
    result["source_sync"] = source_sync
    result["message"] = f"{result['message']} {source_sync['message']}"
    return result


def list_profile_dataset_rows(
    profile: Profile,
    dataset_key: str,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    dataset = get_ready_profile_dataset(profile, dataset_key)
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    total_count = dataset.rows.count()
    rows = dataset.rows.all()[offset : offset + limit]
    return {
        "dataset": str(dataset.key),
        "count": total_count,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(rows) < total_count,
        "rows": [serialize_dataset_row(row) for row in rows],
    }


def create_profile_dataset_row(profile: Profile, dataset_key: str, data: dict) -> dict:
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

        row = DatasetRow.objects.create(
            dataset=dataset,
            row_number=row_number,
            index_value=index_value,
            data={header: str(row_data.get(header, "")) for header in dataset.headers},
        )
        dataset.row_count = dataset.rows.count()
        dataset.save(update_fields=["row_count", "updated_at"])
    source_sync = sync_dataset_source(dataset)
    return add_source_sync_result(
        {"status": "success", "message": "Row created.", "row": serialize_dataset_row(row)},
        source_sync,
    )


def get_profile_dataset_row(profile: Profile, dataset_key: str, row_id: int) -> dict:
    dataset = get_ready_profile_dataset(profile, dataset_key)
    try:
        row = dataset.rows.get(id=row_id)
    except DatasetRow.DoesNotExist as exc:
        raise DatasetServiceError(404, "Row not found.") from exc
    return {"status": "success", "message": "Row retrieved.", "row": serialize_dataset_row(row)}


def get_profile_dataset_row_by_index(profile: Profile, dataset_key: str, index_value: str) -> dict:
    dataset = get_ready_profile_dataset(profile, dataset_key)
    try:
        row = dataset.rows.get(index_value=index_value)
    except DatasetRow.DoesNotExist as exc:
        raise DatasetServiceError(404, "Row not found.") from exc
    return {"status": "success", "message": "Row retrieved.", "row": serialize_dataset_row(row)}


def patch_profile_dataset_row(profile: Profile, dataset_key: str, row_id: int, data: dict) -> dict:
    with transaction.atomic():
        dataset = get_ready_profile_dataset_for_update(profile, dataset_key)
        try:
            row = dataset.rows.get(id=row_id)
        except DatasetRow.DoesNotExist as exc:
            raise DatasetServiceError(404, "Row not found.") from exc

        row.data = {
            **row.data,
            **{key: str(value) for key, value in data.items() if key in dataset.headers},
        }
        if dataset.index_column in data:
            if dataset.index_generated:
                raise DatasetServiceError(
                    400,
                    f"Index column '{dataset.index_column}' is managed by FileBridge "
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
            row.index_value = index_value
        row.save(update_fields=["data", "index_value", "updated_at"])
    source_sync = sync_dataset_source(dataset)
    return add_source_sync_result(
        {"status": "success", "message": "Row updated.", "row": serialize_dataset_row(row)},
        source_sync,
    )


def delete_profile_dataset_row(profile: Profile, dataset_key: str, row_id: int) -> dict:
    with transaction.atomic():
        dataset = get_ready_profile_dataset_for_update(profile, dataset_key)
        deleted_count, _ = dataset.rows.filter(id=row_id).delete()
        if deleted_count == 0:
            raise DatasetServiceError(404, "Row not found.")
        dataset.row_count = dataset.rows.count()
        dataset.save(update_fields=["row_count", "updated_at"])
    source_sync = sync_dataset_source(dataset)
    return add_source_sync_result(
        {"status": "success", "message": "Row deleted."},
        source_sync,
    )
