from types import SimpleNamespace

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings
from httpx import Headers
from qdrant_client.http.exceptions import UnexpectedResponse

from apps.datasets.choices import DatasetStatus
from apps.datasets.models import Dataset, DatasetRow
from apps.datasets.vector_search import (
    QDRANT_DENSE_VECTOR_NAME,
    DatasetRowVector,
    QdrantVectorStore,
    VectorStoreError,
    build_dataset_row_point,
    build_dataset_row_search_document,
    dataset_row_content_hash,
    dataset_row_point_id,
    dataset_row_search_text,
    get_qdrant_client,
    qdrant_is_enabled,
    qdrant_row_collection_name,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def profile(django_user_model):
    user = django_user_model.objects.create_user(
        username="vectorsearchuser",
        email="vectorsearchuser@example.com",
        password="password123",
    )
    return user.profile


@pytest.fixture
def vector_dataset(profile):
    return Dataset.objects.create(
        profile=profile,
        name="Launch Tasks",
        original_filename="tasks.csv",
        status=DatasetStatus.READY,
        headers=["task_id", "status", "notes", "empty"],
        column_schema={
            "task_id": {"type": "text", "description": "Stable task identifier"},
            "status": {"type": "choice", "description": "Workflow state"},
            "notes": {"type": "text"},
        },
        index_column="task_id",
        row_count=1,
    )


@pytest.fixture
def vector_row(vector_dataset):
    return DatasetRow.objects.create(
        dataset=vector_dataset,
        row_number=1,
        index_value="TASK-1",
        data={
            "task_id": "TASK-1",
            "status": "Ready",
            "notes": "Wire Qdrant search foundation",
            "empty": "",
        },
    )


def test_qdrant_row_collection_name_uses_prefix_model_and_version():
    with override_settings(
        QDRANT_COLLECTION_PREFIX="Rowset Prod",
        ROWSET_EMBEDDING_MODEL="text-embedding-3-small",
        ROWSET_EMBEDDING_DIMENSIONS=768,
    ):
        assert qdrant_row_collection_name(version=2) == (
            "rowset_prod_rows_text_embedding_3_small_d768_v2"
        )


def test_qdrant_is_enabled_follows_feature_flag():
    with override_settings(ROWSET_VECTOR_SEARCH_ENABLED=False):
        assert qdrant_is_enabled() is False
    with override_settings(ROWSET_VECTOR_SEARCH_ENABLED=True):
        assert qdrant_is_enabled() is True


def test_get_qdrant_client_requires_feature_flag():
    with override_settings(ROWSET_VECTOR_SEARCH_ENABLED=False, QDRANT_URL="http://qdrant:6333"):
        with pytest.raises(ImproperlyConfigured, match="ROWSET_VECTOR_SEARCH_ENABLED"):
            get_qdrant_client()


def test_get_qdrant_client_requires_url_after_feature_flag_enabled():
    with override_settings(ROWSET_VECTOR_SEARCH_ENABLED=True, QDRANT_URL=""):
        with pytest.raises(ImproperlyConfigured, match="QDRANT_URL"):
            get_qdrant_client()


def test_dataset_row_search_text_is_deterministic_and_descriptive(vector_dataset, vector_row):
    text = dataset_row_search_text(vector_dataset, vector_row)

    assert text == "\n".join(
        [
            "Dataset: Launch Tasks",
            "Index column: task_id",
            "task_id (Stable task identifier): TASK-1",
            "status (Workflow state): Ready",
            "notes: Wire Qdrant search foundation",
        ]
    )


def test_build_dataset_row_search_document_has_stable_id_hash_and_payload(
    vector_dataset,
    vector_row,
):
    document = build_dataset_row_search_document(vector_dataset, vector_row)

    assert document.point_id == dataset_row_point_id(vector_dataset, vector_row)
    assert document.content_hash == dataset_row_content_hash(document.text)
    assert document.payload == {
        "app": "rowset",
        "content_type": "dataset_row",
        "profile_id": vector_dataset.profile_id,
        "dataset_id": vector_dataset.id,
        "dataset_key": str(vector_dataset.key),
        "dataset_status": DatasetStatus.READY,
        "dataset_archived": False,
        "row_id": vector_row.id,
        "row_number": 1,
        "index_column": "task_id",
        "index_value": "TASK-1",
        "chunk_index": 0,
        "content_hash": document.content_hash,
        "embedding_model": "text-embedding-3-small",
        "embedding_dimensions": 1536,
    }


def test_build_dataset_row_point_uses_named_dense_vector(vector_dataset, vector_row):
    vector = [0.1, 0.2, 0.3]

    with override_settings(ROWSET_EMBEDDING_DIMENSIONS=3):
        point = build_dataset_row_point(vector_dataset, vector_row, vector)

    assert point.id == dataset_row_point_id(vector_dataset, vector_row)
    assert point.vector == {QDRANT_DENSE_VECTOR_NAME: vector}
    assert point.payload["content_hash"] == dataset_row_content_hash(
        dataset_row_search_text(vector_dataset, vector_row)
    )


def test_build_dataset_row_point_rejects_wrong_vector_dimensions(vector_dataset, vector_row):
    with override_settings(ROWSET_EMBEDDING_DIMENSIONS=3):
        with pytest.raises(ValueError, match="3 dimensions"):
            build_dataset_row_point(vector_dataset, vector_row, [0.1, 0.2])


class FakeQdrantClient:
    def __init__(
        self,
        *,
        exists=False,
        exists_sequence=None,
        create_exception=None,
        upsert_exception=None,
        query_response=None,
        query_exception=None,
        delete_exception=None,
    ):
        self.exists = exists
        self.exists_sequence = list(exists_sequence or [])
        self.create_exception = create_exception
        self.upsert_exception = upsert_exception
        self.query_response = query_response or SimpleNamespace(points=[])
        self.query_exception = query_exception
        self.delete_exception = delete_exception
        self.created_collection = None
        self.upserted = None
        self.upsert_calls = []
        self.query_points_call = None
        self.deleted = None

    def collection_exists(self, *, collection_name):
        if self.exists_sequence:
            return self.exists_sequence.pop(0)
        return self.exists

    def create_collection(self, **kwargs):
        if self.create_exception is not None:
            raise self.create_exception
        self.created_collection = kwargs
        self.exists = True

    def upsert(self, **kwargs):
        if self.upsert_exception is not None:
            raise self.upsert_exception
        self.upserted = kwargs
        self.upsert_calls.append(kwargs)

    def query_points(self, **kwargs):
        if self.query_exception is not None:
            raise self.query_exception
        self.query_points_call = kwargs
        return self.query_response

    def delete(self, **kwargs):
        if self.delete_exception is not None:
            raise self.delete_exception
        self.deleted = kwargs


def test_vector_store_ensure_collection_creates_named_dense_collection():
    client = FakeQdrantClient(exists=False)
    store = QdrantVectorStore(
        client=client,
        collection_name="rowset_rows_test_d3_v1",
        embedding_dimensions=3,
    )

    store.ensure_collection()

    vector_config = client.created_collection["vectors_config"][QDRANT_DENSE_VECTOR_NAME]
    assert client.created_collection["collection_name"] == "rowset_rows_test_d3_v1"
    assert vector_config.size == 3
    assert vector_config.distance == "Cosine"


def _unexpected_response(status_code=409, content=b"collection already exists"):
    return UnexpectedResponse(
        status_code=status_code,
        reason_phrase="Conflict" if status_code == 409 else "Server Error",
        content=content,
        headers=Headers(),
    )


def test_vector_store_ensure_collection_tolerates_concurrent_create():
    client = FakeQdrantClient(
        exists_sequence=[False, True],
        create_exception=_unexpected_response(),
    )
    store = QdrantVectorStore(client=client, collection_name="rowset_rows_test_v1")

    store.ensure_collection()

    assert client.exists_sequence == []


def test_vector_store_ensure_collection_reraises_unexpected_qdrant_errors():
    error = _unexpected_response(status_code=500, content=b"internal error")
    client = FakeQdrantClient(exists_sequence=[False], create_exception=error)
    store = QdrantVectorStore(client=client, collection_name="rowset_rows_test_v1")

    with pytest.raises(UnexpectedResponse):
        store.ensure_collection()


def test_vector_store_upserts_dataset_row_point(vector_dataset, vector_row):
    client = FakeQdrantClient(exists=True)
    store = QdrantVectorStore(
        client=client,
        collection_name="rowset_rows_custom_embedding_d3_v1",
        embedding_model="custom-embedding",
        embedding_dimensions=3,
    )

    store.upsert_dataset_row_vector(
        vector_dataset,
        vector_row,
        [0.1, 0.2, 0.3],
        embedding_model="custom-embedding",
        embedding_dimensions=3,
    )

    assert client.upserted["collection_name"] == "rowset_rows_custom_embedding_d3_v1"
    assert client.upserted["wait"] is True
    assert len(client.upsert_calls) == 1
    assert len(client.upserted["points"]) == 1
    assert client.upserted["points"][0].payload["row_id"] == vector_row.id
    assert client.upserted["points"][0].payload["embedding_model"] == "custom-embedding"
    assert client.upserted["points"][0].payload["embedding_dimensions"] == 3


def test_vector_store_upserts_dataset_row_vectors_in_one_call(vector_dataset, vector_row):
    second_row = DatasetRow.objects.create(
        dataset=vector_dataset,
        row_number=2,
        index_value="TASK-2",
        data={
            "task_id": "TASK-2",
            "status": "Doing",
            "notes": "Batch Qdrant writes",
        },
    )
    client = FakeQdrantClient(exists=True)
    store = QdrantVectorStore(
        client=client,
        collection_name="rowset_rows_custom_embedding_d3_v1",
        embedding_model="custom-embedding",
        embedding_dimensions=3,
    )

    store.upsert_dataset_row_vectors(
        vector_dataset,
        [
            DatasetRowVector(
                row=vector_row,
                vector=[0.1, 0.2, 0.3],
                embedding_model="custom-embedding",
                embedding_dimensions=3,
            ),
            DatasetRowVector(
                row=second_row,
                vector=[0.4, 0.5, 0.6],
                embedding_model="custom-embedding",
                embedding_dimensions=3,
            ),
        ],
    )

    assert len(client.upsert_calls) == 1
    assert client.upserted["collection_name"] == "rowset_rows_custom_embedding_d3_v1"
    assert client.upserted["wait"] is True
    assert [point.payload["row_id"] for point in client.upserted["points"]] == [
        vector_row.id,
        second_row.id,
    ]


def test_vector_store_wraps_qdrant_upsert_errors(vector_dataset, vector_row):
    client = FakeQdrantClient(
        exists=True,
        upsert_exception=_unexpected_response(status_code=500, content=b"qdrant down"),
    )
    store = QdrantVectorStore(
        client=client,
        collection_name="rowset_rows_custom_embedding_d3_v1",
        embedding_model="custom-embedding",
        embedding_dimensions=3,
    )

    with pytest.raises(VectorStoreError, match="Qdrant vector upsert failed"):
        store.upsert_dataset_row_vectors(
            vector_dataset,
            [
                DatasetRowVector(
                    row=vector_row,
                    vector=[0.1, 0.2, 0.3],
                    embedding_model="custom-embedding",
                    embedding_dimensions=3,
                )
            ],
        )


def _filter_match_values(vector_filter):
    values = {}
    for condition in vector_filter.must:
        if hasattr(condition.match, "value"):
            values[condition.key] = condition.match.value
    return values


def test_vector_store_searches_dataset_rows_with_required_payload_filter(
    vector_dataset,
    vector_row,
):
    client = FakeQdrantClient(
        exists=True,
        query_response=SimpleNamespace(
            points=[
                SimpleNamespace(
                    id="point-1",
                    score=0.91,
                    payload={
                        "row_id": vector_row.id,
                        "chunk_index": 0,
                        "content_hash": "abc123",
                    },
                )
            ]
        ),
    )
    store = QdrantVectorStore(
        client=client,
        collection_name="rowset_rows_custom_embedding_d3_v1",
        embedding_model="custom-embedding",
        embedding_dimensions=3,
    )

    hits = store.search_dataset_rows(vector_dataset, [0.1, 0.2, 0.3], limit=5)

    assert len(hits) == 1
    assert hits[0].point_id == "point-1"
    assert hits[0].score == 0.91
    assert hits[0].payload["row_id"] == vector_row.id
    assert client.query_points_call["collection_name"] == "rowset_rows_custom_embedding_d3_v1"
    assert client.query_points_call["query"] == [0.1, 0.2, 0.3]
    assert client.query_points_call["using"] == QDRANT_DENSE_VECTOR_NAME
    assert client.query_points_call["limit"] == 5
    assert client.query_points_call["with_vectors"] is False
    assert _filter_match_values(client.query_points_call["query_filter"]) == {
        "app": "rowset",
        "content_type": "dataset_row",
        "profile_id": vector_dataset.profile_id,
        "dataset_id": vector_dataset.id,
        "dataset_status": DatasetStatus.READY,
        "dataset_archived": False,
    }


def test_vector_store_rejects_search_dimension_mismatch(vector_dataset):
    client = FakeQdrantClient(exists=True)
    store = QdrantVectorStore(
        client=client,
        collection_name="rowset_rows_custom_embedding_d3_v1",
        embedding_model="custom-embedding",
        embedding_dimensions=3,
    )

    with pytest.raises(ValueError, match="3 dimensions"):
        store.search_dataset_rows(vector_dataset, [0.1, 0.2], limit=5)


def test_vector_store_deletes_dataset_row_vectors_with_payload_filter(
    vector_dataset,
    vector_row,
):
    client = FakeQdrantClient(exists=True)
    store = QdrantVectorStore(
        client=client,
        collection_name="rowset_rows_custom_embedding_d3_v1",
        embedding_model="custom-embedding",
        embedding_dimensions=3,
    )

    store.delete_dataset_row_vectors(vector_dataset, [vector_row.id])

    selector = client.deleted["points_selector"]
    assert client.deleted["collection_name"] == "rowset_rows_custom_embedding_d3_v1"
    assert client.deleted["wait"] is True
    assert _filter_match_values(selector.filter) == {
        "app": "rowset",
        "content_type": "dataset_row",
        "profile_id": vector_dataset.profile_id,
        "dataset_id": vector_dataset.id,
    }
    row_condition = next(
        condition for condition in selector.filter.must if condition.key == "row_id"
    )
    assert row_condition.match.any == [vector_row.id]


def test_vector_store_deletes_all_dataset_vectors_with_payload_filter(vector_dataset):
    client = FakeQdrantClient(exists=True)
    store = QdrantVectorStore(
        client=client,
        collection_name="rowset_rows_custom_embedding_d3_v1",
        embedding_model="custom-embedding",
        embedding_dimensions=3,
    )

    store.delete_dataset_vectors(vector_dataset)

    selector = client.deleted["points_selector"]
    assert _filter_match_values(selector.filter) == {
        "app": "rowset",
        "content_type": "dataset_row",
        "profile_id": vector_dataset.profile_id,
        "dataset_id": vector_dataset.id,
    }
    assert all(condition.key != "row_id" for condition in selector.filter.must)


def test_vector_store_wraps_qdrant_delete_errors(vector_dataset, vector_row):
    client = FakeQdrantClient(
        exists=True,
        delete_exception=_unexpected_response(status_code=500, content=b"qdrant down"),
    )
    store = QdrantVectorStore(
        client=client,
        collection_name="rowset_rows_custom_embedding_d3_v1",
        embedding_model="custom-embedding",
        embedding_dimensions=3,
    )

    with pytest.raises(VectorStoreError, match="Qdrant vector delete failed"):
        store.delete_dataset_row_vectors(vector_dataset, [vector_row.id])


def test_vector_store_rejects_upsert_model_mismatch(vector_dataset, vector_row):
    client = FakeQdrantClient(exists=True)
    store = QdrantVectorStore(
        client=client,
        collection_name="rowset_rows_custom_embedding_d3_v1",
        embedding_model="custom-embedding",
        embedding_dimensions=3,
    )

    with pytest.raises(ValueError, match="does not match collection model"):
        store.upsert_dataset_row_vector(
            vector_dataset,
            vector_row,
            [0.1, 0.2, 0.3],
            embedding_model="other-embedding",
            embedding_dimensions=3,
        )


def test_vector_store_rejects_upsert_dimension_mismatch(vector_dataset, vector_row):
    client = FakeQdrantClient(exists=True)
    store = QdrantVectorStore(
        client=client,
        collection_name="rowset_rows_custom_embedding_d3_v1",
        embedding_model="custom-embedding",
        embedding_dimensions=3,
    )

    with pytest.raises(ValueError, match="do not match collection dimensions"):
        store.upsert_dataset_row_vector(
            vector_dataset,
            vector_row,
            [0.1, 0.2, 0.3, 0.4],
            embedding_model="custom-embedding",
            embedding_dimensions=4,
        )
