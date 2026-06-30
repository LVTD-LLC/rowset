import hashlib
import re
import uuid
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from qdrant_client import QdrantClient
from qdrant_client.http import models as qdrant_models

from apps.datasets.models import Dataset, DatasetRow

QDRANT_CONTENT_TYPE_DATASET_ROW = "dataset_row"
QDRANT_DENSE_VECTOR_NAME = "dense"
QDRANT_COLLECTION_VERSION = 1
QDRANT_COLLECTION_KIND = "rows"
QDRANT_APP_PAYLOAD_VALUE = "rowset"
QDRANT_POINT_NAMESPACE = uuid.UUID("bbd2624c-7177-4888-8b38-16d830f078fb")


@dataclass(frozen=True)
class DatasetRowSearchDocument:
    point_id: str
    text: str
    content_hash: str
    payload: dict[str, Any]


def _slug(value: str, *, fallback: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")
    return slug or fallback


def qdrant_row_collection_name(
    *,
    prefix: str | None = None,
    embedding_model: str | None = None,
    version: int = QDRANT_COLLECTION_VERSION,
) -> str:
    """Return the collection name for Rowset row vectors."""
    normalized_prefix = _slug(prefix or settings.QDRANT_COLLECTION_PREFIX, fallback="rowset")
    normalized_model = _slug(
        embedding_model or settings.ROWSET_EMBEDDING_MODEL,
        fallback="embedding",
    )
    return f"{normalized_prefix}_{QDRANT_COLLECTION_KIND}_{normalized_model}_v{version}"


def qdrant_is_configured() -> bool:
    return bool(str(settings.QDRANT_URL or "").strip())


def get_qdrant_client() -> QdrantClient:
    if not qdrant_is_configured():
        raise ImproperlyConfigured("QDRANT_URL must be configured before using vector search.")

    kwargs: dict[str, Any] = {
        "url": settings.QDRANT_URL,
        "timeout": settings.QDRANT_TIMEOUT_SECONDS,
    }
    if settings.QDRANT_API_KEY:
        kwargs["api_key"] = settings.QDRANT_API_KEY
    return QdrantClient(**kwargs)


def dataset_row_point_id(dataset: Dataset, row: DatasetRow, *, chunk_index: int = 0) -> str:
    raw_id = f"rowset:dataset:{dataset.key}:row:{row.id}:chunk:{chunk_index}"
    return str(uuid.uuid5(QDRANT_POINT_NAMESPACE, raw_id))


def dataset_row_search_text(dataset: Dataset, row: DatasetRow) -> str:
    """Return deterministic text used to embed a dataset row."""
    column_schema = dataset.column_schema or {}
    lines = [f"Dataset: {dataset.name}"]
    if dataset.index_column:
        lines.append(f"Index column: {dataset.index_column}")

    for header in dataset.headers:
        value = str((row.data or {}).get(header, "") or "").strip()
        if not value:
            continue

        column_metadata = column_schema.get(header) or {}
        description = str(column_metadata.get("description") or "").strip()
        label = header
        if description:
            label = f"{header} ({description})"
        lines.append(f"{label}: {value}")

    return "\n".join(lines)


def dataset_row_content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_dataset_row_search_document(
    dataset: Dataset,
    row: DatasetRow,
    *,
    embedding_model: str | None = None,
    embedding_dimensions: int | None = None,
    chunk_index: int = 0,
) -> DatasetRowSearchDocument:
    text = dataset_row_search_text(dataset, row)
    content_hash = dataset_row_content_hash(text)
    model = embedding_model or settings.ROWSET_EMBEDDING_MODEL
    dimensions = embedding_dimensions or settings.ROWSET_EMBEDDING_DIMENSIONS

    payload = {
        "app": QDRANT_APP_PAYLOAD_VALUE,
        "content_type": QDRANT_CONTENT_TYPE_DATASET_ROW,
        "profile_id": dataset.profile_id,
        "dataset_id": dataset.id,
        "dataset_key": str(dataset.key),
        "dataset_status": dataset.status,
        "dataset_archived": dataset.archived_at is not None,
        "row_id": row.id,
        "row_number": row.row_number,
        "index_column": dataset.index_column,
        "index_value": row.index_value,
        "chunk_index": chunk_index,
        "content_hash": content_hash,
        "embedding_model": model,
        "embedding_dimensions": dimensions,
    }

    return DatasetRowSearchDocument(
        point_id=dataset_row_point_id(dataset, row, chunk_index=chunk_index),
        text=text,
        content_hash=content_hash,
        payload=payload,
    )


def build_dataset_row_point(
    dataset: Dataset,
    row: DatasetRow,
    vector: list[float],
    *,
    embedding_model: str | None = None,
    embedding_dimensions: int | None = None,
    chunk_index: int = 0,
) -> qdrant_models.PointStruct:
    document = build_dataset_row_search_document(
        dataset,
        row,
        embedding_model=embedding_model,
        embedding_dimensions=embedding_dimensions,
        chunk_index=chunk_index,
    )
    dimensions = embedding_dimensions or settings.ROWSET_EMBEDDING_DIMENSIONS
    if len(vector) != dimensions:
        raise ValueError(f"Vector must contain {dimensions} dimensions.")

    return qdrant_models.PointStruct(
        id=document.point_id,
        vector={QDRANT_DENSE_VECTOR_NAME: vector},
        payload=document.payload,
    )


class QdrantVectorStore:
    def __init__(
        self,
        *,
        client: QdrantClient | None = None,
        collection_name: str | None = None,
    ) -> None:
        self.client = client or get_qdrant_client()
        self.collection_name = collection_name or qdrant_row_collection_name()

    def ensure_collection(self) -> None:
        if self.client.collection_exists(collection_name=self.collection_name):
            return

        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config={
                QDRANT_DENSE_VECTOR_NAME: qdrant_models.VectorParams(
                    size=settings.ROWSET_EMBEDDING_DIMENSIONS,
                    distance=qdrant_models.Distance.COSINE,
                ),
            },
        )

    def upsert_dataset_row_vector(
        self,
        dataset: Dataset,
        row: DatasetRow,
        vector: list[float],
    ) -> None:
        point = build_dataset_row_point(dataset, row, vector)
        self.client.upsert(
            collection_name=self.collection_name,
            points=[point],
            wait=True,
        )
