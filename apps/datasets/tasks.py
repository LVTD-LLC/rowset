from collections.abc import Iterable

from django.db import transaction
from django.utils import timezone

from apps.datasets.choices import DatasetStatus
from apps.datasets.model_typing import (
    DatasetDoesNotExist,
    DatasetRowDoesNotExist,
    dataset_import_task_fields,
    dataset_objects,
    dataset_row_objects,
    dataset_row_task_fields,
)
from apps.datasets.models import Dataset, DatasetRow
from apps.datasets.services import (
    backfill_dataset_vectors,
    generated_index_column_name,
    generated_index_column_schema,
    iter_indexed_rows,
    normalize_column_schema,
    source_text_from_file,
)
from apps.datasets.services import (
    delete_dataset_row_vectors as delete_dataset_row_vectors_service,
)
from apps.datasets.services import (
    delete_dataset_vectors as delete_dataset_vectors_service,
)
from apps.datasets.services import (
    index_dataset_row_vector as index_dataset_row_vector_service,
)
from apps.datasets.vector_search import qdrant_is_enabled
from apps.datasets.vector_tasks import enqueue_vector_task
from rowset.utils import get_rowset_logger

logger = get_rowset_logger(__name__)
VECTOR_ROW_DELETE_TASK_BATCH_SIZE = 1000


def _enqueue_stale_row_vector_deletes(dataset_id: int, row_ids: Iterable[int]) -> int:
    stale_row_count = 0
    batch = []
    for row_id in row_ids:
        stale_row_count += 1
        batch.append(int(row_id))
        if len(batch) < VECTOR_ROW_DELETE_TASK_BATCH_SIZE:
            continue

        enqueue_vector_task("apps.datasets.tasks.delete_dataset_row_vectors", dataset_id, batch)
        batch = []

    if batch:
        enqueue_vector_task("apps.datasets.tasks.delete_dataset_row_vectors", dataset_id, batch)

    return stale_row_count


def _ensure_index_config(dataset: Dataset) -> None:
    dataset_fields = dataset_import_task_fields(dataset)
    if dataset_fields.index_column:
        return

    dataset_fields.index_column = generated_index_column_name(dataset_fields.headers)
    dataset_fields.index_generated = True
    existing_headers = [
        header for header in dataset_fields.headers if header != dataset_fields.index_column
    ]
    if dataset_fields.index_column not in dataset_fields.headers:
        dataset_fields.headers = [dataset_fields.index_column, *dataset_fields.headers]
    dataset_fields.column_schema = {
        dataset_fields.index_column: generated_index_column_schema(),
        **normalize_column_schema(existing_headers, dataset_fields.column_schema),
    }


def import_dataset_rows(dataset_id: int) -> None:
    dataset = dataset_objects().get(id=dataset_id)
    dataset_fields = dataset_import_task_fields(dataset)
    logger.info(
        "Starting CSV dataset import",
        dataset_id=dataset_fields.id,
        dataset_key=str(dataset_fields.key),
    )

    try:
        source_text = dataset_fields.source_text or source_text_from_file(
            dataset_fields.source_file,
            dataset_fields.file_type,
        )
        _ensure_index_config(dataset)
        row_iterator = iter_indexed_rows(
            file_type=dataset_fields.file_type,
            source_text=source_text,
            headers=dataset_fields.headers,
            index_column=dataset_fields.index_column,
            index_generated=dataset_fields.index_generated,
        )
        rows = [
            DatasetRow(
                dataset=dataset,
                row_number=row.row_number,
                index_value=row.index_value,
                data=row.data,
            )
            for row in row_iterator
        ]

        with transaction.atomic():
            stale_row_count = _enqueue_stale_row_vector_deletes(
                dataset_fields.id,
                dataset_fields.rows.values_list("id", flat=True).iterator(
                    chunk_size=VECTOR_ROW_DELETE_TASK_BATCH_SIZE
                ),
            )
            dataset_fields.rows.all().delete()
            dataset_row_objects().bulk_create(rows, batch_size=1000)
            dataset_fields.row_count = len(rows)
            dataset_fields.status = DatasetStatus.READY
            dataset_fields.parse_error = ""
            dataset_fields.processed_at = timezone.now()
            dataset.save(
                update_fields=[
                    "headers",
                    "column_schema",
                    "index_column",
                    "index_generated",
                    "row_count",
                    "status",
                    "parse_error",
                    "processed_at",
                    "updated_at",
                ]
            )
            enqueue_vector_task(
                "apps.datasets.tasks.reindex_dataset_vectors_task",
                dataset_fields.id,
            )
        logger.info(
            "Finished CSV dataset import",
            dataset_id=dataset_fields.id,
            row_count=len(rows),
            stale_row_count=stale_row_count,
        )
    except Exception as exc:
        dataset_fields.status = DatasetStatus.FAILED
        dataset_fields.parse_error = str(exc)
        dataset.save(update_fields=["status", "parse_error", "updated_at"])
        logger.exception("CSV dataset import failed", dataset_id=dataset_fields.id)
        raise


def index_dataset_row_vector(row_id: int) -> None:
    if not qdrant_is_enabled():
        return
    try:
        row = dataset_row_objects().select_related("dataset").get(id=row_id)
    except DatasetRowDoesNotExist:
        logger.info("Skipping vector row indexing for missing row", row_id=row_id)
        return

    try:
        index_dataset_row_vector_service(row)
    except Exception:
        logger.exception("Vector row indexing failed", row_id=row_id)
    else:
        row_fields = dataset_row_task_fields(row)
        dataset_fields = dataset_import_task_fields(row_fields.dataset)
        logger.info(
            "Vector row indexing complete",
            dataset_id=row_fields.dataset_id,
            dataset_key=str(dataset_fields.key),
            row_id=row_id,
        )


def backfill_dataset_vectors_task(dataset_id: int) -> None:
    if not qdrant_is_enabled():
        return
    try:
        dataset = dataset_objects().get(id=dataset_id)
    except DatasetDoesNotExist:
        logger.info("Skipping vector backfill for missing dataset", dataset_id=dataset_id)
        return

    try:
        result = backfill_dataset_vectors(dataset)
    except Exception:
        logger.exception("Vector dataset backfill failed", dataset_id=dataset_id)
    else:
        dataset_fields = dataset_import_task_fields(dataset)
        logger.info(
            "Vector dataset backfill complete",
            dataset_id=dataset_id,
            dataset_key=str(dataset_fields.key),
            rows_seen=result.rows_seen,
            indexed=result.indexed,
            failed=result.failed,
        )


def reindex_dataset_vectors_task(dataset_id: int) -> None:
    if not qdrant_is_enabled():
        return
    try:
        dataset = dataset_objects().get(id=dataset_id)
    except DatasetDoesNotExist:
        logger.info("Skipping vector reindex for missing dataset", dataset_id=dataset_id)
        return

    try:
        result = backfill_dataset_vectors(dataset)
    except Exception:
        logger.exception("Vector dataset reindex failed", dataset_id=dataset_id)
        return

    dataset_fields = dataset_import_task_fields(dataset)
    logger.info(
        "Vector dataset reindex complete",
        dataset_id=dataset_id,
        dataset_key=str(dataset_fields.key),
        rows_seen=result.rows_seen,
        indexed=result.indexed,
        failed=result.failed,
    )


def delete_dataset_row_vectors(dataset_id: int, row_ids: list[int]) -> None:
    if not qdrant_is_enabled():
        return
    try:
        dataset = dataset_objects().get(id=dataset_id)
    except DatasetDoesNotExist:
        logger.info(
            "Skipping vector row deletion for missing dataset",
            dataset_id=dataset_id,
            row_ids=row_ids,
        )
        return

    try:
        delete_dataset_row_vectors_service(dataset, row_ids)
    except Exception:
        logger.exception(
            "Vector row deletion failed",
            dataset_id=dataset_id,
            row_ids=row_ids,
        )
    else:
        dataset_fields = dataset_import_task_fields(dataset)
        logger.info(
            "Vector row deletion complete",
            dataset_id=dataset_id,
            dataset_key=str(dataset_fields.key),
            row_count=len(row_ids),
        )


def delete_dataset_vectors(dataset_id: int) -> None:
    if not qdrant_is_enabled():
        return
    try:
        dataset = dataset_objects().get(id=dataset_id)
    except DatasetDoesNotExist:
        logger.info("Skipping vector dataset deletion for missing dataset", dataset_id=dataset_id)
        return

    try:
        delete_dataset_vectors_service(dataset)
    except Exception:
        logger.exception("Vector dataset deletion failed", dataset_id=dataset_id)
    else:
        dataset_fields = dataset_import_task_fields(dataset)
        logger.info(
            "Vector dataset deletion complete",
            dataset_id=dataset_id,
            dataset_key=str(dataset_fields.key),
        )
