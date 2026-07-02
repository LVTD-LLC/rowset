import hashlib
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from qdrant_client import QdrantClient
from qdrant_client.http import models as qdrant_models
from qdrant_client.http.exceptions import (
    ApiException,
    ResponseHandlingException,
    UnexpectedResponse,
)

from apps.datasets.choices import DatasetStatus
from apps.datasets.model_typing import (
    dataset_row_vector_search_fields,
    dataset_vector_search_fields,
)
from apps.datasets.models import Dataset, DatasetRow

QDRANT_CONTENT_TYPE_DATASET_ROW = "dataset_row"
QDRANT_DENSE_VECTOR_NAME = "dense"
QDRANT_COLLECTION_VERSION = 1
QDRANT_COLLECTION_KIND = "rows"
QDRANT_APP_PAYLOAD_VALUE = "rowset"
QDRANT_POINT_NAMESPACE = uuid.UUID("bbd2624c-7177-4888-8b38-16d830f078fb")


class VectorStoreError(RuntimeError):
    pass


@dataclass(frozen=True)
class DatasetRowSearchDocument:
    point_id: str
    text: str
    content_hash: str
    payload: dict[str, object]


@dataclass(frozen=True)
class DatasetRowVector:
    row: DatasetRow
    vector: list[float]
    embedding_model: str | None = None
    embedding_dimensions: int | None = None


@dataclass(frozen=True)
class DatasetRowVectorSearchHit:
    point_id: str
    score: float
    payload: dict[str, object]


def _slug(value: str, *, fallback: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")
    return slug or fallback


def qdrant_row_collection_name(
    *,
    prefix: str | None = None,
    embedding_model: str | None = None,
    embedding_dimensions: int | None = None,
    version: int = QDRANT_COLLECTION_VERSION,
) -> str:
    """Return the collection name for Rowset row vectors."""
    normalized_prefix = _slug(prefix or settings.QDRANT_COLLECTION_PREFIX, fallback="rowset")
    normalized_model = _slug(
        embedding_model or settings.ROWSET_EMBEDDING_MODEL,
        fallback="embedding",
    )
    dimensions = embedding_dimensions or settings.ROWSET_EMBEDDING_DIMENSIONS
    return (
        f"{normalized_prefix}_{QDRANT_COLLECTION_KIND}_{normalized_model}_d{dimensions}_v{version}"
    )


def qdrant_is_configured() -> bool:
    return bool(str(settings.QDRANT_URL or "").strip())


def qdrant_is_enabled() -> bool:
    return bool(settings.ROWSET_VECTOR_SEARCH_ENABLED)


def get_qdrant_client() -> QdrantClient:
    if not qdrant_is_enabled():
        raise ImproperlyConfigured(
            "ROWSET_VECTOR_SEARCH_ENABLED must be true before using vector search."
        )
    if not qdrant_is_configured():
        raise ImproperlyConfigured("QDRANT_URL must be configured before using vector search.")

    if settings.QDRANT_API_KEY:
        return QdrantClient(
            url=settings.QDRANT_URL,
            timeout=settings.QDRANT_TIMEOUT_SECONDS,
            api_key=settings.QDRANT_API_KEY,
        )
    return QdrantClient(url=settings.QDRANT_URL, timeout=settings.QDRANT_TIMEOUT_SECONDS)


def _is_qdrant_collection_exists_error(exc: UnexpectedResponse) -> bool:
    if exc.status_code == 409:
        return True
    return "already exists" in str(exc).lower()


def _payload_match(key: str, value: int | str) -> qdrant_models.FieldCondition:
    return qdrant_models.FieldCondition(
        key=key,
        match=qdrant_models.MatchValue(value=value),
    )


def _dataset_row_filter(
    dataset: Dataset,
    *,
    row_ids: Sequence[int] | None = None,
    extra_must: Sequence[qdrant_models.FieldCondition] = (),
) -> qdrant_models.Filter:
    dataset_fields = dataset_vector_search_fields(dataset)
    must = [
        _payload_match("app", QDRANT_APP_PAYLOAD_VALUE),
        _payload_match("content_type", QDRANT_CONTENT_TYPE_DATASET_ROW),
        _payload_match("profile_id", dataset_fields.profile_id),
        _payload_match("dataset_id", dataset_fields.id),
    ]
    if row_ids:
        must.append(
            qdrant_models.FieldCondition(
                key="row_id",
                match=qdrant_models.MatchAny(any=list(row_ids)),
            )
        )
    must.extend(extra_must)
    return qdrant_models.Filter(must=must)


def dataset_row_search_filter(dataset: Dataset) -> qdrant_models.Filter:
    return _dataset_row_filter(
        dataset,
        extra_must=[
            _payload_match("dataset_status", DatasetStatus.READY),
            _payload_match("dataset_archived", False),
        ],
    )


def profile_dataset_row_search_filter(
    profile_id: int,
    *,
    dataset_ids: Sequence[int] | None = None,
    dataset_status: str | None = DatasetStatus.READY,
    dataset_archived: bool | None = False,
) -> qdrant_models.Filter:
    must = [
        _payload_match("app", QDRANT_APP_PAYLOAD_VALUE),
        _payload_match("content_type", QDRANT_CONTENT_TYPE_DATASET_ROW),
        _payload_match("profile_id", profile_id),
    ]
    if dataset_ids:
        must.append(
            qdrant_models.FieldCondition(
                key="dataset_id",
                match=qdrant_models.MatchAny(any=list(dataset_ids)),
            )
        )
    if dataset_status:
        must.append(_payload_match("dataset_status", dataset_status))
    if dataset_archived is not None:
        must.append(_payload_match("dataset_archived", dataset_archived))
    return qdrant_models.Filter(must=must)


def dataset_row_point_id(dataset: Dataset, row: DatasetRow, *, chunk_index: int = 0) -> str:
    row_fields = dataset_row_vector_search_fields(row)
    raw_id = f"rowset:dataset:{dataset.key}:row:{row_fields.id}:chunk:{chunk_index}"
    return str(uuid.uuid5(QDRANT_POINT_NAMESPACE, raw_id))


def dataset_row_search_text(dataset: Dataset, row: DatasetRow) -> str:
    """Return deterministic text used to embed a dataset row."""
    dataset_fields = dataset_vector_search_fields(dataset)
    row_fields = dataset_row_vector_search_fields(row)
    column_schema = dataset_fields.column_schema or {}
    lines = [f"Dataset: {dataset_fields.name}"]
    if dataset_fields.index_column:
        lines.append(f"Index column: {dataset_fields.index_column}")

    for header in dataset_fields.headers:
        value = str((row_fields.data or {}).get(header, "") or "").strip()
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
    dataset_fields = dataset_vector_search_fields(dataset)
    row_fields = dataset_row_vector_search_fields(row)
    text = dataset_row_search_text(dataset, row)
    content_hash = dataset_row_content_hash(text)
    model = embedding_model or settings.ROWSET_EMBEDDING_MODEL
    dimensions = embedding_dimensions or settings.ROWSET_EMBEDDING_DIMENSIONS

    payload = {
        "app": QDRANT_APP_PAYLOAD_VALUE,
        "content_type": QDRANT_CONTENT_TYPE_DATASET_ROW,
        "profile_id": dataset_fields.profile_id,
        "dataset_id": dataset_fields.id,
        "dataset_key": str(dataset_fields.key),
        "dataset_status": dataset_fields.status,
        "dataset_archived": dataset_fields.archived_at is not None,
        "row_id": row_fields.id,
        "row_number": row_fields.row_number,
        "index_column": dataset_fields.index_column,
        "index_value": row_fields.index_value,
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
        embedding_model: str | None = None,
        embedding_dimensions: int | None = None,
    ) -> None:
        self.client = client or get_qdrant_client()
        self.embedding_model = embedding_model or settings.ROWSET_EMBEDDING_MODEL
        self.embedding_dimensions = embedding_dimensions or settings.ROWSET_EMBEDDING_DIMENSIONS
        self.collection_name = collection_name or qdrant_row_collection_name(
            embedding_model=self.embedding_model,
            embedding_dimensions=self.embedding_dimensions,
        )

    def ensure_collection(self) -> None:
        if self.client.collection_exists(collection_name=self.collection_name):
            return

        try:
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config={
                    QDRANT_DENSE_VECTOR_NAME: qdrant_models.VectorParams(
                        size=self.embedding_dimensions,
                        distance=qdrant_models.Distance.COSINE,
                    ),
                },
            )
        except UnexpectedResponse as exc:
            if not _is_qdrant_collection_exists_error(exc):
                raise
            if self.client.collection_exists(collection_name=self.collection_name):
                return
            raise

    def _validate_embedding_config(self, model: str, dimensions: int) -> None:
        if model != self.embedding_model:
            raise ValueError(
                f"Embedding model {model!r} does not match collection model "
                f"{self.embedding_model!r}."
            )
        if dimensions != self.embedding_dimensions:
            raise ValueError(
                f"Embedding dimensions {dimensions} do not match collection dimensions "
                f"{self.embedding_dimensions}."
            )

    def _validate_vector_dimensions(self, vector: list[float]) -> None:
        if len(vector) != self.embedding_dimensions:
            raise ValueError(f"Vector must contain {self.embedding_dimensions} dimensions.")

    def upsert_dataset_row_vector(
        self,
        dataset: Dataset,
        row: DatasetRow,
        vector: list[float],
        *,
        embedding_model: str | None = None,
        embedding_dimensions: int | None = None,
    ) -> None:
        self.upsert_dataset_row_vectors(
            dataset,
            [
                DatasetRowVector(
                    row=row,
                    vector=vector,
                    embedding_model=embedding_model,
                    embedding_dimensions=embedding_dimensions,
                )
            ],
        )

    def upsert_dataset_row_vectors(
        self,
        dataset: Dataset,
        row_vectors: Sequence[DatasetRowVector],
    ) -> None:
        if not row_vectors:
            return

        points = []
        for row_vector in row_vectors:
            model = row_vector.embedding_model or self.embedding_model
            dimensions = row_vector.embedding_dimensions or self.embedding_dimensions
            self._validate_embedding_config(model, dimensions)
            points.append(
                build_dataset_row_point(
                    dataset,
                    row_vector.row,
                    row_vector.vector,
                    embedding_model=model,
                    embedding_dimensions=dimensions,
                )
            )

        try:
            self.client.upsert(
                collection_name=self.collection_name,
                points=points,
                wait=True,
            )
        except (ApiException, ResponseHandlingException, UnexpectedResponse) as exc:
            raise VectorStoreError(f"Qdrant vector upsert failed: {exc}") from exc

    def search_dataset_rows(
        self,
        dataset: Dataset,
        vector: list[float],
        *,
        limit: int = 10,
    ) -> list[DatasetRowVectorSearchHit]:
        self._validate_vector_dimensions(vector)
        try:
            response = self.client.query_points(
                collection_name=self.collection_name,
                query=vector,
                using=QDRANT_DENSE_VECTOR_NAME,
                query_filter=dataset_row_search_filter(dataset),
                limit=limit,
                with_payload=True,
                with_vectors=False,
            )
        except (ApiException, ResponseHandlingException, UnexpectedResponse) as exc:
            raise VectorStoreError(f"Qdrant vector search failed: {exc}") from exc

        return [
            DatasetRowVectorSearchHit(
                point_id=str(point.id),
                score=float(point.score),
                payload=dict(point.payload or {}),
            )
            for point in response.points
        ]

    def search_profile_dataset_rows(
        self,
        profile,
        vector: list[float],
        *,
        dataset_ids: Sequence[int] | None = None,
        dataset_status: str | None = DatasetStatus.READY,
        dataset_archived: bool | None = False,
        limit: int = 10,
    ) -> list[DatasetRowVectorSearchHit]:
        self._validate_vector_dimensions(vector)
        try:
            response = self.client.query_points(
                collection_name=self.collection_name,
                query=vector,
                using=QDRANT_DENSE_VECTOR_NAME,
                query_filter=profile_dataset_row_search_filter(
                    profile.id,
                    dataset_ids=dataset_ids,
                    dataset_status=dataset_status,
                    dataset_archived=dataset_archived,
                ),
                limit=limit,
                with_payload=True,
                with_vectors=False,
            )
        except (ApiException, ResponseHandlingException, UnexpectedResponse) as exc:
            raise VectorStoreError(f"Qdrant vector search failed: {exc}") from exc

        return [
            DatasetRowVectorSearchHit(
                point_id=str(point.id),
                score=float(point.score),
                payload=dict(point.payload or {}),
            )
            for point in response.points
        ]

    def delete_dataset_row_vectors(self, dataset: Dataset, row_ids: Sequence[int]) -> None:
        normalized_row_ids = [int(row_id) for row_id in row_ids]
        if not normalized_row_ids:
            return
        self._delete_by_filter(_dataset_row_filter(dataset, row_ids=normalized_row_ids))

    def delete_dataset_vectors(self, dataset: Dataset) -> None:
        self._delete_by_filter(_dataset_row_filter(dataset))

    def _delete_by_filter(self, vector_filter: qdrant_models.Filter) -> None:
        try:
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=qdrant_models.FilterSelector(filter=vector_filter),
                wait=True,
            )
        except (ApiException, ResponseHandlingException, UnexpectedResponse) as exc:
            raise VectorStoreError(f"Qdrant vector delete failed: {exc}") from exc
