from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings
from django.utils import timezone

from apps.datasets.embeddings import EmbeddingResult
from apps.datasets.models import Dataset, DatasetRow
from apps.datasets.services import (
    VectorBackfillResult,
    backfill_dataset_vectors,
    delete_dataset_row_vectors,
    delete_dataset_vectors,
    index_dataset_row_vector,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def profile(django_user_model):
    user = django_user_model.objects.create_user(
        username="vectorbackfilluser",
        email="vectorbackfilluser@example.com",
        password="password123",
    )
    return user.profile


@pytest.fixture
def dataset(profile):
    return Dataset.objects.create(
        profile=profile,
        name="Vector Tasks",
        headers=["task_id", "title"],
        column_schema={"title": {"type": "text", "description": "Task title"}},
        index_column="task_id",
        row_count=2,
    )


@pytest.fixture
def rows(dataset):
    return [
        DatasetRow.objects.create(
            dataset=dataset,
            row_number=1,
            index_value="TASK-1",
            data={"task_id": "TASK-1", "title": "Add embeddings"},
        ),
        DatasetRow.objects.create(
            dataset=dataset,
            row_number=2,
            index_value="TASK-2",
            data={"task_id": "TASK-2", "title": "Backfill vectors"},
        ),
    ]


class FakeEmbeddingProvider:
    model = "fake-embedding"
    dimensions = 3

    def __init__(self):
        self.text_batches = []

    def embed_text(self, text):
        return self.embed_texts([text])[0]

    def embed_texts(self, texts):
        self.text_batches.append(list(texts))
        results = []
        for index, _text in enumerate(texts, start=1):
            value = float(index)
            results.append(
                EmbeddingResult(
                    vector=[value, value + 0.1, value + 0.2],
                    model=self.model,
                    dimensions=self.dimensions,
                )
            )
        return results


class FakeVectorStore:
    def __init__(self):
        self.ensure_calls = 0
        self.upserts = []
        self.upsert_batches = []
        self.deleted_row_ids = []
        self.deleted_dataset_keys = []

    def ensure_collection(self):
        self.ensure_calls += 1

    def upsert_dataset_row_vector(
        self,
        dataset,
        row,
        vector,
        *,
        embedding_model=None,
        embedding_dimensions=None,
    ):
        self.upserts.append(
            {
                "dataset_key": str(dataset.key),
                "row_id": row.id,
                "dataset_archived": dataset.archived_at is not None,
                "vector": vector,
                "embedding_model": embedding_model,
                "embedding_dimensions": embedding_dimensions,
            }
        )

    def upsert_dataset_row_vectors(self, dataset, row_vectors):
        self.upsert_batches.append(list(row_vectors))
        for row_vector in row_vectors:
            self.upsert_dataset_row_vector(
                dataset,
                row_vector.row,
                row_vector.vector,
                embedding_model=row_vector.embedding_model,
                embedding_dimensions=row_vector.embedding_dimensions,
            )

    def delete_dataset_row_vectors(self, dataset, row_ids):
        self.deleted_row_ids.append((str(dataset.key), list(row_ids)))

    def delete_dataset_vectors(self, dataset):
        self.deleted_dataset_keys.append(str(dataset.key))


def test_backfill_dataset_vectors_upserts_dataset_rows_in_row_order(dataset, rows):
    provider = FakeEmbeddingProvider()
    store = FakeVectorStore()

    result = backfill_dataset_vectors(
        dataset,
        embedding_provider=provider,
        vector_store=store,
        batch_size=2,
    )

    assert result.rows_seen == 2
    assert result.indexed == 2
    assert result.failed == 0
    assert result.would_index == 0
    assert store.ensure_calls == 1
    assert len(store.upsert_batches) == 1
    assert [row_vector.row.id for row_vector in store.upsert_batches[0]] == [
        rows[0].id,
        rows[1].id,
    ]
    assert [upsert["row_id"] for upsert in store.upserts] == [rows[0].id, rows[1].id]
    assert store.upserts[0]["embedding_model"] == "fake-embedding"
    assert store.upserts[0]["embedding_dimensions"] == 3
    assert len(provider.text_batches) == 1
    assert "title (Task title): Add embeddings" in provider.text_batches[0][0]
    assert "title (Task title): Backfill vectors" in provider.text_batches[0][1]


def test_backfill_dataset_vectors_dry_run_counts_rows_without_external_calls(dataset, rows):
    provider = FakeEmbeddingProvider()
    store = FakeVectorStore()

    result = backfill_dataset_vectors(
        dataset,
        embedding_provider=provider,
        vector_store=store,
        dry_run=True,
        limit=1,
    )

    assert result.rows_seen == 1
    assert result.indexed == 0
    assert result.failed == 0
    assert result.would_index == 1
    assert provider.text_batches == []
    assert store.ensure_calls == 0
    assert store.upserts == []


def test_index_dataset_row_vector_embeds_and_upserts_one_row(dataset, rows):
    provider = FakeEmbeddingProvider()
    store = FakeVectorStore()

    index_dataset_row_vector(
        rows[0],
        embedding_provider=provider,
        vector_store=store,
    )

    assert store.ensure_calls == 1
    assert len(provider.text_batches) == 1
    assert len(provider.text_batches[0]) == 1
    assert "title (Task title): Add embeddings" in provider.text_batches[0][0]
    assert [upsert["row_id"] for upsert in store.upserts] == [rows[0].id]
    assert store.upserts[0]["embedding_model"] == "fake-embedding"
    assert store.upserts[0]["embedding_dimensions"] == 3


def test_delete_dataset_row_vectors_delegates_to_store(dataset, rows):
    store = FakeVectorStore()

    delete_dataset_row_vectors(dataset, [rows[0].id], vector_store=store)

    assert store.deleted_row_ids == [(str(dataset.key), [rows[0].id])]


def test_delete_dataset_vectors_delegates_to_store(dataset):
    store = FakeVectorStore()

    delete_dataset_vectors(dataset, vector_store=store)

    assert store.deleted_dataset_keys == [str(dataset.key)]


def test_reindex_dataset_vectors_task_backfills_when_enabled(
    dataset,
    monkeypatch,
):
    from apps.datasets.tasks import reindex_dataset_vectors_task

    calls = []

    def fake_backfill_dataset_vectors(task_dataset):
        calls.append(("backfill", task_dataset.id))
        return VectorBackfillResult(rows_seen=2, indexed=2, failed=0)

    monkeypatch.setattr(
        "apps.datasets.tasks.backfill_dataset_vectors",
        fake_backfill_dataset_vectors,
    )

    with override_settings(ROWSET_VECTOR_SEARCH_ENABLED=True):
        reindex_dataset_vectors_task(dataset.id)

    assert calls == [("backfill", dataset.id)]


def test_backfill_dataset_vectors_indexes_archived_dataset_rows(dataset, rows):
    dataset.archived_at = timezone.now()
    dataset.save(update_fields=["archived_at", "updated_at"])
    provider = FakeEmbeddingProvider()
    store = FakeVectorStore()

    result = backfill_dataset_vectors(dataset, embedding_provider=provider, vector_store=store)

    assert result.indexed == 2
    assert {upsert["dataset_archived"] for upsert in store.upserts} == {True}


def test_backfill_dataset_vectors_command_supports_dry_run(dataset, rows):
    stdout = StringIO()

    call_command(
        "backfill_dataset_vectors",
        str(dataset.key),
        "--dry-run",
        "--limit",
        "1",
        stdout=stdout,
    )

    output = stdout.getvalue()
    assert "1 row(s) would be indexed" in output
    assert "0 indexed" in output


def test_backfill_dataset_vectors_command_supports_every_active_dataset(
    dataset, profile, monkeypatch
):
    second = Dataset.objects.create(
        profile=profile,
        name="More vectors",
        headers=["id"],
        index_column="id",
    )
    archived = Dataset.objects.create(
        profile=profile,
        name="Archived vectors",
        headers=["id"],
        index_column="id",
        archived_at=timezone.now(),
    )
    seen = []

    def record_backfill(selected, **_kwargs):
        seen.append(selected.id)
        return VectorBackfillResult(rows_seen=1, indexed=1)

    monkeypatch.setattr(
        "apps.datasets.management.commands.backfill_dataset_vectors.backfill_dataset_vectors",
        record_backfill,
    )
    stdout = StringIO()

    call_command("backfill_dataset_vectors", "--all", stdout=stdout)

    assert seen == [dataset.id, second.id]
    assert archived.id not in seen
    assert "2 indexed, 0 failed, 2 row(s) seen" in stdout.getvalue()


def test_backfill_dataset_vectors_command_requires_one_scope():
    with pytest.raises(CommandError, match="dataset_key or --all"):
        call_command("backfill_dataset_vectors")


def test_backfill_dataset_vectors_command_reports_missing_embedding_configuration(dataset, rows):
    with override_settings(ROWSET_VECTOR_SEARCH_ENABLED=True, OPENROUTER_API_KEY=""):
        with pytest.raises(CommandError, match="OPENROUTER_API_KEY"):
            call_command("backfill_dataset_vectors", str(dataset.key))


def test_backfill_dataset_vectors_command_reports_runtime_backfill_errors(
    dataset,
    rows,
    monkeypatch,
):
    def fail_backfill(*args, **kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(
        "apps.datasets.management.commands.backfill_dataset_vectors.backfill_dataset_vectors",
        fail_backfill,
    )

    with pytest.raises(CommandError, match="provider unavailable"):
        call_command("backfill_dataset_vectors", str(dataset.key), "--stop-on-error")


def test_backfill_dataset_vectors_command_exits_nonzero_on_partial_failures(
    dataset,
    rows,
    monkeypatch,
):
    def partially_fail_backfill(*args, **kwargs):
        return VectorBackfillResult(rows_seen=2, indexed=1, failed=1)

    monkeypatch.setattr(
        "apps.datasets.management.commands.backfill_dataset_vectors.backfill_dataset_vectors",
        partially_fail_backfill,
    )

    with pytest.raises(CommandError, match="1 indexed, 1 failed, 2 row"):
        call_command("backfill_dataset_vectors", str(dataset.key))
