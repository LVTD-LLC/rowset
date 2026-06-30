from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from apps.datasets.choices import DatasetStatus
from apps.datasets.embeddings import EmbeddingResult
from apps.datasets.models import Dataset, DatasetRow
from apps.datasets.vector_indexing import backfill_dataset_vectors

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
        original_filename="tasks.csv",
        status=DatasetStatus.READY,
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
        self.texts = []

    def embed_text(self, text):
        self.texts.append(text)
        value = float(len(self.texts))
        return EmbeddingResult(
            vector=[value, value + 0.1, value + 0.2],
            model=self.model,
            dimensions=self.dimensions,
        )


class FakeVectorStore:
    def __init__(self):
        self.ensure_calls = 0
        self.upserts = []

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
                "vector": vector,
                "embedding_model": embedding_model,
                "embedding_dimensions": embedding_dimensions,
            }
        )


def test_backfill_dataset_vectors_upserts_ready_dataset_rows_in_row_order(dataset, rows):
    provider = FakeEmbeddingProvider()
    store = FakeVectorStore()

    result = backfill_dataset_vectors(
        dataset,
        embedding_provider=provider,
        vector_store=store,
        batch_size=1,
    )

    assert result.rows_seen == 2
    assert result.indexed == 2
    assert result.failed == 0
    assert result.would_index == 0
    assert store.ensure_calls == 1
    assert [upsert["row_id"] for upsert in store.upserts] == [rows[0].id, rows[1].id]
    assert store.upserts[0]["embedding_model"] == "fake-embedding"
    assert store.upserts[0]["embedding_dimensions"] == 3
    assert "title (Task title): Add embeddings" in provider.texts[0]


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
    assert provider.texts == []
    assert store.ensure_calls == 0
    assert store.upserts == []


def test_backfill_dataset_vectors_rejects_non_ready_datasets(dataset):
    dataset.status = DatasetStatus.PREVIEWED
    dataset.save(update_fields=["status", "updated_at"])

    with pytest.raises(ValueError, match="ready"):
        backfill_dataset_vectors(dataset, embedding_provider=FakeEmbeddingProvider())


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


def test_backfill_dataset_vectors_command_reports_missing_embedding_configuration(dataset, rows):
    with override_settings(OPENAI_API_KEY=""):
        with pytest.raises(CommandError, match="OPENAI_API_KEY"):
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
