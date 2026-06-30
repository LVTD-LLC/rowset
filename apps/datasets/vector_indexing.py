from dataclasses import dataclass, field

from apps.datasets.choices import DatasetStatus
from apps.datasets.embeddings import EmbeddingProvider, get_embedding_provider
from apps.datasets.models import Dataset
from apps.datasets.vector_search import QdrantVectorStore, build_dataset_row_search_document


@dataclass(frozen=True)
class VectorBackfillError:
    row_id: int
    message: str


@dataclass(frozen=True)
class VectorBackfillResult:
    rows_seen: int = 0
    indexed: int = 0
    would_index: int = 0
    failed: int = 0
    errors: list[VectorBackfillError] = field(default_factory=list)


def _validate_backfill_dataset(dataset: Dataset) -> None:
    if dataset.status != DatasetStatus.READY:
        raise ValueError("Vector backfill requires a ready dataset.")
    if dataset.archived_at is not None:
        raise ValueError("Vector backfill cannot index archived datasets.")


def _dataset_rows_for_backfill(dataset: Dataset, *, limit: int | None = None):
    rows = dataset.rows.order_by("row_number", "id").only(
        "id",
        "dataset_id",
        "row_number",
        "index_value",
        "data",
    )
    if limit is not None:
        rows = rows[:limit]
    return rows


def backfill_dataset_vectors(
    dataset: Dataset,
    *,
    embedding_provider: EmbeddingProvider | None = None,
    vector_store: QdrantVectorStore | None = None,
    dry_run: bool = False,
    limit: int | None = None,
    batch_size: int = 500,
    stop_on_error: bool = False,
) -> VectorBackfillResult:
    _validate_backfill_dataset(dataset)
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1.")
    if limit is not None and limit < 1:
        raise ValueError("limit must be at least 1 when provided.")

    provider = None if dry_run else embedding_provider or get_embedding_provider()
    store = None
    if not dry_run:
        store = vector_store or QdrantVectorStore(
            embedding_model=provider.model,
            embedding_dimensions=provider.dimensions,
        )
        store.ensure_collection()

    rows_seen = 0
    indexed = 0
    would_index = 0
    errors: list[VectorBackfillError] = []

    rows = _dataset_rows_for_backfill(dataset, limit=limit)
    for row in rows.iterator(chunk_size=batch_size):
        rows_seen += 1
        if dry_run:
            would_index += 1
            continue

        document = build_dataset_row_search_document(
            dataset,
            row,
            embedding_model=provider.model if provider else None,
            embedding_dimensions=provider.dimensions if provider else None,
        )

        try:
            embedding = provider.embed_text(document.text)
            store.upsert_dataset_row_vector(
                dataset,
                row,
                embedding.vector,
                embedding_model=embedding.model,
                embedding_dimensions=embedding.dimensions,
            )
            indexed += 1
        except Exception as exc:
            errors.append(VectorBackfillError(row_id=row.id, message=str(exc)))
            if stop_on_error:
                raise

    return VectorBackfillResult(
        rows_seen=rows_seen,
        indexed=indexed,
        would_index=would_index,
        failed=len(errors),
        errors=errors,
    )
