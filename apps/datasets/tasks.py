from apps.datasets.models import Dataset, DatasetRow
from apps.datasets.services import (
    backfill_dataset_vectors,
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
from rowset.utils import get_rowset_logger

logger = get_rowset_logger(__name__)


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


def reindex_dataset_vectors_task(dataset_id: int) -> None:
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

    logger.info(
        "Vector dataset reindex complete",
        dataset_id=dataset_id,
        dataset_key=str(dataset.key),
        rows_seen=result.rows_seen,
        indexed=result.indexed,
        failed=result.failed,
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
