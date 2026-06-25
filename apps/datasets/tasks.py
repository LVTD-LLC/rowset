from django.db import transaction
from django.utils import timezone

from apps.datasets.choices import DatasetStatus
from apps.datasets.models import Dataset, DatasetRow
from apps.datasets.services import (
    generated_index_column_schema,
    generated_index_column_name,
    iter_indexed_rows,
    normalize_column_schema,
    source_text_from_file,
)
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
        logger.info("Finished CSV dataset import", dataset_id=dataset.id, row_count=len(rows))
    except Exception as exc:
        dataset.status = DatasetStatus.FAILED
        dataset.parse_error = str(exc)
        dataset.save(update_fields=["status", "parse_error", "updated_at"])
        logger.exception("CSV dataset import failed", dataset_id=dataset.id)
        raise
