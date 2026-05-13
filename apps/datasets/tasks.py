from django.db import transaction
from django.utils import timezone

from apps.datasets.choices import DatasetStatus
from apps.datasets.models import Dataset, DatasetRow
from apps.datasets.services import iter_indexed_rows, source_text_from_file
from filebridge.utils import get_filebridge_logger

logger = get_filebridge_logger(__name__)


def _ensure_index_config(dataset: Dataset) -> None:
    if dataset.index_column:
        return

    dataset.index_column = "filebridge_id"
    dataset.index_generated = True
    if dataset.index_column not in dataset.headers:
        dataset.headers = [dataset.index_column, *dataset.headers]


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
