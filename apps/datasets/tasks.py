from django.db import transaction
from django.utils import timezone

from apps.datasets.choices import DatasetStatus
from apps.datasets.models import Dataset, DatasetRow
from apps.datasets.services import iter_csv_rows, iter_csv_text_rows
from filebridge.utils import get_filebridge_logger

logger = get_filebridge_logger(__name__)


def import_dataset_rows(dataset_id: int) -> None:
    dataset = Dataset.objects.get(id=dataset_id)
    logger.info("Starting CSV dataset import", dataset_id=dataset.id, dataset_key=str(dataset.key))

    try:
        row_iterator = (
            iter_csv_text_rows(dataset.source_text)
            if dataset.source_text
            else iter_csv_rows(dataset.source_file)
        )
        rows = [
            DatasetRow(dataset=dataset, row_number=row_number, data=data)
            for row_number, data in row_iterator
        ]
        with transaction.atomic():
            dataset.rows.all().delete()
            DatasetRow.objects.bulk_create(rows, batch_size=1000)
            dataset.row_count = len(rows)
            dataset.status = DatasetStatus.READY
            dataset.parse_error = ""
            dataset.processed_at = timezone.now()
            dataset.save(
                update_fields=["row_count", "status", "parse_error", "processed_at", "updated_at"]
            )
        logger.info("Finished CSV dataset import", dataset_id=dataset.id, row_count=len(rows))
    except Exception as exc:
        dataset.status = DatasetStatus.FAILED
        dataset.parse_error = str(exc)
        dataset.save(update_fields=["status", "parse_error", "updated_at"])
        logger.exception("CSV dataset import failed", dataset_id=dataset.id)
        raise
