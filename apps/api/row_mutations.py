from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from django.db import connection

from apps.api.errors import DatasetServiceError
from apps.core.analytics import ROWSET_DATASET_ROW_MUTATED, agent_api_key_tracking_properties
from apps.core.models import AgentApiKey, Profile
from apps.datasets.choices import DatasetMutationType
from apps.datasets.history import record_dataset_mutation
from apps.datasets.models import Dataset, DatasetAsset, DatasetMutation, DatasetRow
from apps.datasets.services import (
    audio_columns_from_schema,
    calculated_column_names,
    dataset_asset_key_from_ref,
    image_columns_from_schema,
)

ROW_MUTATION_TYPES = (
    DatasetMutationType.ROW_CREATED,
    DatasetMutationType.ROW_UPDATED,
    DatasetMutationType.ROW_DELETED,
)
RowWritePayload = Mapping[str, object]
RowData = dict[str, str]


def stringify_cell(value: object) -> str:
    if value is None:
        return ""
    return str(value)


def normalize_row_data_for_headers(data: RowWritePayload, headers: Iterable[str]) -> RowData:
    return {header: stringify_cell(data.get(header, "")) for header in headers}


def normalize_row_patch_for_headers(data: RowWritePayload, headers: Iterable[str]) -> RowData:
    allowed_headers = set(headers)
    return {
        header: stringify_cell(value) for header, value in data.items() if header in allowed_headers
    }


def _writable_dataset_headers(dataset: Dataset) -> list[str]:
    calculated_columns = calculated_column_names(dataset.headers, dataset.column_schema)
    return [header for header in dataset.headers if header not in calculated_columns]


@dataclass(frozen=True)
class RowMutationHooks:
    validate_choice_row_data: Callable[..., Any]
    validate_image_row_data: Callable[..., Any]
    validate_audio_row_data: Callable[..., Any]
    normalize_reference_row_data: Callable[..., dict[str, str]]
    validate_relationship_row_data: Callable[..., Any]
    raise_if_target_row_is_referenced: Callable[[Dataset, str], None]
    serialize_dataset_row: Callable[..., dict]
    enqueue_dataset_row_vector_index: Callable[[int], None]
    enqueue_dataset_row_vector_delete: Callable[[int, list[int]], None]
    track_activation_event: Callable[..., Any]


def normalize_row_ids(row_ids: Iterable[int | str]) -> list[int]:
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
    return ordered_row_ids


def create_dataset_row(
    profile: Profile,
    dataset: Dataset,
    data: RowWritePayload,
    *,
    agent_api_key: AgentApiKey | None = None,
    hooks: RowMutationHooks,
) -> dict:
    row_number = _next_row_number(dataset)
    row_data = _create_row_data(dataset, data, row_number)
    writable_headers = _writable_dataset_headers(dataset)
    serialized_data = normalize_row_data_for_headers(row_data, writable_headers)
    hooks.validate_choice_row_data(dataset.headers, dataset.column_schema, serialized_data)
    hooks.validate_image_row_data(dataset.headers, dataset.column_schema, serialized_data)
    hooks.validate_audio_row_data(dataset.headers, dataset.column_schema, serialized_data)
    serialized_data = hooks.normalize_reference_row_data(
        profile,
        dataset.headers,
        dataset.column_schema,
        serialized_data,
    )
    index_value = _required_create_index_value(dataset, serialized_data)
    _raise_if_duplicate_index(dataset, index_value)
    hooks.validate_relationship_row_data(dataset, serialized_data)

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
    is_first_row_mutation = not profile_has_row_mutation(profile)
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
    track_dataset_row_mutation(
        profile=profile,
        dataset=dataset,
        mutation_type=DatasetMutationType.ROW_CREATED,
        agent_api_key=agent_api_key,
        is_first_row_mutation=is_first_row_mutation,
        changed_field_count=len(row.data),
        track_activation_event_func=hooks.track_activation_event,
    )
    hooks.enqueue_dataset_row_vector_index(row.id)
    row = dataset.rows.prefetch_related("assets").get(id=row.id)
    return {
        "status": "success",
        "message": "Row created.",
        "dataset": str(dataset.key),
        "row": hooks.serialize_dataset_row(row, dataset=dataset),
    }


def patch_dataset_row(
    profile: Profile,
    dataset: Dataset,
    row: DatasetRow,
    data: RowWritePayload,
    *,
    agent_api_key: AgentApiKey | None = None,
    hooks: RowMutationHooks,
) -> dict:
    if not connection.in_atomic_block:
        raise AssertionError("patch_dataset_row must be called inside transaction.atomic().")

    writable_headers = _writable_dataset_headers(dataset)
    row_patch = normalize_row_patch_for_headers(data, writable_headers)
    patched_fields = sorted(row_patch)
    changed_asset_columns = _changed_asset_columns(dataset, row, row_patch, patched_fields)
    _raise_if_patch_references_asset(row_patch, changed_asset_columns)
    changed_image_columns = _changed_columns_for_type(changed_asset_columns, "image")
    changed_audio_columns = _changed_columns_for_type(changed_asset_columns, "audio")
    hooks.validate_image_row_data(
        dataset.headers,
        dataset.column_schema,
        row_patch,
        columns=changed_image_columns,
    )
    hooks.validate_audio_row_data(
        dataset.headers,
        dataset.column_schema,
        row_patch,
        columns=changed_audio_columns,
    )
    cleared_asset_columns = _cleared_asset_columns(row_patch, changed_asset_columns)
    row_patch = hooks.normalize_reference_row_data(
        profile,
        dataset.headers,
        dataset.column_schema,
        row_patch,
        columns=patched_fields,
    )
    hooks.validate_choice_row_data(
        dataset.headers,
        dataset.column_schema,
        row_patch,
        columns=patched_fields,
    )
    current_data = row.data or {}
    field_changes = _row_field_changes(current_data, row_patch, patched_fields)
    changed_fields = [str(change["field"]) for change in field_changes]
    row.data = {**current_data, **row_patch}
    index_changed = _apply_index_patch(dataset, row, row_patch, data, hooks)
    hooks.validate_relationship_row_data(dataset, row.data, columns=patched_fields)
    _delete_cleared_assets(dataset, row, cleared_asset_columns)
    row.updated_by_agent_api_key = agent_api_key
    row.save(update_fields=["data", "index_value", "updated_by_agent_api_key", "updated_at"])
    dataset.updated_by_agent_api_key = agent_api_key
    dataset.save(update_fields=["updated_by_agent_api_key", "updated_at"])
    is_first_row_mutation = not profile_has_row_mutation(profile)
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
    track_dataset_row_mutation(
        profile=profile,
        dataset=dataset,
        mutation_type=DatasetMutationType.ROW_UPDATED,
        agent_api_key=agent_api_key,
        is_first_row_mutation=is_first_row_mutation,
        changed_field_count=len(changed_fields),
        index_changed=index_changed,
        track_activation_event_func=hooks.track_activation_event,
    )
    hooks.enqueue_dataset_row_vector_index(row.id)
    row = dataset.rows.prefetch_related("assets").get(id=row.id)
    return {
        "status": "success",
        "message": "Row updated.",
        "dataset": str(dataset.key),
        "row": hooks.serialize_dataset_row(row, dataset=dataset),
    }


def delete_dataset_row(
    profile: Profile,
    dataset: Dataset,
    row: DatasetRow,
    *,
    agent_api_key: AgentApiKey | None = None,
    hooks: RowMutationHooks,
) -> dict:
    row_id = row.id
    row_number = row.row_number
    hooks.raise_if_target_row_is_referenced(dataset, row.index_value)
    row.delete()
    dataset.row_count = dataset.rows.count()
    dataset.updated_by_agent_api_key = agent_api_key
    dataset.save(update_fields=["row_count", "updated_by_agent_api_key", "updated_at"])
    is_first_row_mutation = not profile_has_row_mutation(profile)
    _record_row_deleted(
        dataset,
        row_id=row_id,
        row_number=row_number,
        agent_api_key=agent_api_key,
    )
    track_dataset_row_mutation(
        profile=profile,
        dataset=dataset,
        mutation_type=DatasetMutationType.ROW_DELETED,
        agent_api_key=agent_api_key,
        is_first_row_mutation=is_first_row_mutation,
        deleted_count=1,
        track_activation_event_func=hooks.track_activation_event,
    )
    hooks.enqueue_dataset_row_vector_delete(dataset.id, [row_id])
    return {"status": "success", "message": "Row deleted.", "dataset": str(dataset.key)}


def delete_dataset_rows(
    profile: Profile,
    dataset: Dataset,
    ordered_row_ids: list[int],
    *,
    agent_api_key: AgentApiKey | None = None,
    hooks: RowMutationHooks,
) -> dict:
    ordered_rows = _ordered_rows_for_delete(dataset, ordered_row_ids)
    for row in ordered_rows:
        hooks.raise_if_target_row_is_referenced(dataset, row.index_value)

    deleted_rows = [(row.id, row.row_number) for row in ordered_rows]
    dataset.rows.filter(id__in=ordered_row_ids).delete()
    dataset.row_count = dataset.rows.count()
    dataset.updated_by_agent_api_key = agent_api_key
    dataset.save(update_fields=["row_count", "updated_by_agent_api_key", "updated_at"])
    is_first_row_mutation = not profile_has_row_mutation(profile)
    for row_id, row_number in deleted_rows:
        _record_row_deleted(
            dataset,
            row_id=row_id,
            row_number=row_number,
            agent_api_key=agent_api_key,
        )
    track_dataset_row_mutation(
        profile=profile,
        dataset=dataset,
        mutation_type=DatasetMutationType.ROW_DELETED,
        agent_api_key=agent_api_key,
        is_first_row_mutation=is_first_row_mutation,
        deleted_count=len(deleted_rows),
        track_activation_event_func=hooks.track_activation_event,
    )
    hooks.enqueue_dataset_row_vector_delete(dataset.id, [row_id for row_id, _ in deleted_rows])

    row_label = "row" if len(deleted_rows) == 1 else "rows"
    return {
        "status": "success",
        "message": f"Deleted {len(deleted_rows)} {row_label}.",
        "dataset": str(dataset.key),
        "deleted_count": len(deleted_rows),
    }


def _next_row_number(dataset: Dataset) -> int:
    last_row_number = (
        dataset.rows.order_by("-row_number").values_list("row_number", flat=True).first() or 0
    )
    return last_row_number + 1


def _create_row_data(dataset: Dataset, data: RowWritePayload, row_number: int) -> RowWritePayload:
    if dataset.index_generated:
        return {**data, dataset.index_column: str(row_number)}
    return data


def _required_create_index_value(dataset: Dataset, serialized_data: RowData) -> str:
    index_value = str(serialized_data.get(dataset.index_column, "")).strip()
    if not index_value:
        raise DatasetServiceError(
            400,
            f"Index column '{dataset.index_column}' is required.",
        )
    return index_value


def _raise_if_duplicate_index(dataset: Dataset, index_value: str) -> None:
    if dataset.rows.filter(index_value=index_value).exists():
        raise DatasetServiceError(409, f"Row with index '{index_value}' already exists.")


def _changed_asset_columns(
    dataset: Dataset,
    row: DatasetRow,
    row_patch: RowData,
    patched_fields: list[str],
) -> dict[str, str]:
    image_columns = set(image_columns_from_schema(dataset.headers, dataset.column_schema))
    audio_columns = set(audio_columns_from_schema(dataset.headers, dataset.column_schema))
    changed_columns = {}
    for field in patched_fields:
        if row_patch.get(field, "") == str((row.data or {}).get(field, "") or ""):
            continue
        if field in image_columns:
            changed_columns[field] = "image"
        elif field in audio_columns:
            changed_columns[field] = "audio"
    return changed_columns


def _changed_columns_for_type(
    changed_asset_columns: dict[str, str],
    asset_type: str,
) -> list[str]:
    return [
        column
        for column, column_asset_type in changed_asset_columns.items()
        if column_asset_type == asset_type
    ]


def _raise_if_patch_references_asset(
    row_patch: RowData,
    changed_asset_columns: dict[str, str],
) -> None:
    for column, asset_type in changed_asset_columns.items():
        if dataset_asset_key_from_ref(row_patch.get(column, "")):
            raise DatasetServiceError(
                400,
                f"Column '{column}' is an {asset_type} column. "
                f"Attach a new {asset_type} asset instead.",
            )


def _cleared_asset_columns(
    row_patch: RowData,
    changed_asset_columns: dict[str, str],
) -> list[str]:
    return [field for field in changed_asset_columns if row_patch.get(field, "") == ""]


def _delete_cleared_assets(
    dataset: Dataset,
    row: DatasetRow,
    cleared_asset_columns: list[str],
) -> None:
    if not cleared_asset_columns:
        return
    DatasetAsset.objects.filter(
        dataset=dataset,
        row=row,
        column_name__in=cleared_asset_columns,
    ).delete()


def _apply_index_patch(
    dataset: Dataset,
    row: DatasetRow,
    row_patch: RowData,
    raw_patch: RowWritePayload,
    hooks: RowMutationHooks,
) -> bool:
    if dataset.index_column not in raw_patch:
        return False

    index_value = str(row_patch.get(dataset.index_column, "")).strip()
    if dataset.index_generated and index_value != row.index_value:
        raise DatasetServiceError(
            400,
            f"Index column '{dataset.index_column}' is managed by Rowset and cannot be updated.",
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
        hooks.raise_if_target_row_is_referenced(dataset, row.index_value)
    row.index_value = index_value
    return index_changed


def _row_field_changes(
    current_data: dict,
    patch_data: RowData,
    candidate_fields: list[str],
) -> list[dict[str, str]]:
    field_changes = []
    for field in candidate_fields:
        before_value = stringify_cell(current_data.get(field, ""))
        after_value = stringify_cell(patch_data.get(field, ""))
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


def _ordered_rows_for_delete(dataset: Dataset, ordered_row_ids: list[int]) -> list[DatasetRow]:
    rows_by_id = {row.id: row for row in dataset.rows.filter(id__in=ordered_row_ids)}
    ordered_rows = []
    for row_id in ordered_row_ids:
        row = rows_by_id.get(row_id)
        if row is None:
            raise DatasetServiceError(404, "Row not found.")
        ordered_rows.append(row)
    return ordered_rows


def _record_row_deleted(
    dataset: Dataset,
    *,
    row_id: int,
    row_number: int,
    agent_api_key: AgentApiKey | None,
) -> None:
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


def profile_has_row_mutation(profile: Profile) -> bool:
    return DatasetMutation.objects.filter(
        profile=profile,
        mutation_type__in=ROW_MUTATION_TYPES,
    ).exists()


def track_dataset_row_mutation(
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
    track_activation_event_func: Callable[..., Any],
) -> None:
    track_activation_event_func(
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
