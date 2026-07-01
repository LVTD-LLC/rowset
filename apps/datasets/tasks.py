from django.db import transaction
from django.utils import timezone

from apps.datasets.choices import DatasetStatus
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


def _ensure_index_config(dataset: Dataset) -> None:
    if dataset.index_column:
        return

    dataset.index_column = generated_index_column_name(dataset.headers)
    dataset.index_generated = True
    existing_headers = [header for header in dataset.headers if header != dataset.index_column]
    if dataset.index_column not in dataset.headers:
        dataset.headers = [dataset.index_column, *dataset.headers]
    dataset.column_schema = {
        dataset.index_column: generated_index_column_schema(),
        **normalize_column_schema(existing_headers, dataset.column_schema),
    }


def import_dataset_rows(dataset_id: int) -> None:
    dataset = Dataset.objects.get(id=dataset_id)
    logger.info("Starting CSV dataset import", dataset_id=dataset.id, dataset_key=str(dataset.key))

    try:
        source_text = dataset.source_text or source_text_from_file(
            dataset.source_file,
            dataset.file_type,
        )
        _ensure_index_config(dataset)
        row_iterator = iter_indexed_rows(
            file_type=dataset.file_type,
            source_text=source_text,
            headers=dataset.headers,
            index_column=dataset.index_column,
            index_generated=dataset.index_generated,
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
            stale_row_ids = list(dataset.rows.values_list("id", flat=True))
            dataset.rows.all().delete()
            DatasetRow.objects.bulk_create(rows, batch_size=1000)
            dataset.row_count = len(rows)
            dataset.status = DatasetStatus.READY
            dataset.parse_error = ""
            dataset.processed_at = timezone.now()
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
                dataset.id,
                stale_row_ids,
            )
        logger.info("Finished CSV dataset import", dataset_id=dataset.id, row_count=len(rows))
    except Exception as exc:
        dataset.status = DatasetStatus.FAILED
        dataset.parse_error = str(exc)
        dataset.save(update_fields=["status", "parse_error", "updated_at"])
        logger.exception("CSV dataset import failed", dataset_id=dataset.id)
        raise


def index_dataset_row_vector(row_id: int) -> None:
    if not qdrant_is_enabled():
        return
    try:
        row = DatasetRow.objects.select_related("dataset").get(id=row_id)
    except DatasetRow.DoesNotExist:
        logger.info("Skipping vector row indexing for missing row", row_id=row_id)
        return

    try:
        index_dataset_row_vector_service(row)
    except Exception:
        logger.exception("Vector row indexing failed", row_id=row_id)
    else:
        logger.info(
            "Vector row indexing complete",
            dataset_id=row.dataset_id,
            dataset_key=str(row.dataset.key),
            row_id=row_id,
        )


def backfill_dataset_vectors_task(dataset_id: int) -> None:
    if not qdrant_is_enabled():
        return
    try:
        dataset = Dataset.objects.get(id=dataset_id)
    except Dataset.DoesNotExist:
        logger.info("Skipping vector backfill for missing dataset", dataset_id=dataset_id)
        return

    try:
        result = backfill_dataset_vectors(dataset)
    except Exception:
        logger.exception("Vector dataset backfill failed", dataset_id=dataset_id)
    else:
        logger.info(
            "Vector dataset backfill complete",
            dataset_id=dataset_id,
            dataset_key=str(dataset.key),
            rows_seen=result.rows_seen,
            indexed=result.indexed,
            failed=result.failed,
        )


def reindex_dataset_vectors_task(dataset_id: int, stale_row_ids: list[int] | None = None) -> None:
    if not qdrant_is_enabled():
        return
    try:
        dataset = Dataset.objects.get(id=dataset_id)
    except Dataset.DoesNotExist:
        logger.info("Skipping vector reindex for missing dataset", dataset_id=dataset_id)
        return

    try:
        result = backfill_dataset_vectors(dataset)
    except Exception:
        logger.exception("Vector dataset reindex failed", dataset_id=dataset_id)
        return

    stale_cleanup_failed = False
    if stale_row_ids:
        try:
            delete_dataset_row_vectors_service(dataset, stale_row_ids)
        except Exception:
            stale_cleanup_failed = True
            logger.exception(
                "Vector stale row cleanup failed after reindex",
                dataset_id=dataset_id,
                stale_row_count=len(stale_row_ids),
            )

    logger.info(
        "Vector dataset reindex complete",
        dataset_id=dataset_id,
        dataset_key=str(dataset.key),
        rows_seen=result.rows_seen,
        indexed=result.indexed,
        failed=result.failed,
        stale_row_count=len(stale_row_ids or []),
        stale_cleanup_failed=stale_cleanup_failed,
    )


def delete_dataset_row_vectors(dataset_id: int, row_ids: list[int]) -> None:
    if not qdrant_is_enabled():
        return
    try:
        dataset = Dataset.objects.get(id=dataset_id)
    except Dataset.DoesNotExist:
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
        logger.info(
            "Vector row deletion complete",
            dataset_id=dataset_id,
            dataset_key=str(dataset.key),
            row_count=len(row_ids),
        )


def delete_dataset_vectors(dataset_id: int) -> None:
    if not qdrant_is_enabled():
        return
    try:
        dataset = Dataset.objects.get(id=dataset_id)
    except Dataset.DoesNotExist:
        logger.info("Skipping vector dataset deletion for missing dataset", dataset_id=dataset_id)
        return

    try:
        delete_dataset_vectors_service(dataset)
    except Exception:
        logger.exception("Vector dataset deletion failed", dataset_id=dataset_id)
    else:
        logger.info(
            "Vector dataset deletion complete",
            dataset_id=dataset_id,
            dataset_key=str(dataset.key),
        )
