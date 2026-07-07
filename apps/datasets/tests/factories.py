from __future__ import annotations

from collections.abc import Iterable
from itertools import count
from typing import Any

from apps.core.choices import AgentApiKeyAccessLevel
from apps.core.models import Profile
from apps.core.services import AgentApiKeyCredential, create_agent_api_key
from apps.datasets.choices import DatasetColumnType
from apps.datasets.embeddings import EmbeddingResult
from apps.datasets.models import Dataset, DatasetAsset, DatasetRelationship, DatasetRow, Project
from apps.datasets.vector_search import DatasetRowVectorSearchHit

_sequence = count(1)


def next_factory_id() -> int:
    return next(_sequence)


def create_test_user(
    django_user_model,
    *,
    username: str | None = None,
    email: str | None = None,
    password: str = "password123",
):
    sequence = next_factory_id()
    username = username or f"rowsetuser{sequence}"
    email = email or f"{username}@example.com"
    return django_user_model.objects.create_user(
        username=username,
        email=email,
        password=password,
    )


def provision_profile_api_key(
    profile: Profile,
    *,
    name: str = "Dataset API Test Agent",
    access_level: str = AgentApiKeyAccessLevel.READ_WRITE,
) -> AgentApiKeyCredential:
    credential = create_agent_api_key(profile, name, access_level)
    profile.key = credential.raw_key
    return credential


def create_profile_with_api_key(
    django_user_model,
    *,
    username: str | None = None,
    email: str | None = None,
    key_name: str = "Dataset API Test Agent",
    access_level: str = AgentApiKeyAccessLevel.READ_WRITE,
) -> Profile:
    user = create_test_user(django_user_model, username=username, email=email)
    provision_profile_api_key(user.profile, name=key_name, access_level=access_level)
    return user.profile


def create_project(profile: Profile, *, name: str | None = None, **overrides) -> Project:
    sequence = next_factory_id()
    return Project.objects.create(
        profile=profile,
        name=name or f"Project {sequence}",
        **overrides,
    )


def create_dataset(
    profile: Profile,
    *,
    name: str | None = None,
    headers: list[str] | None = None,
    rows: Iterable[dict[str, Any]] | None = None,
    index_column: str | None = None,
    row_count: int | None = None,
    **overrides,
) -> Dataset:
    headers = headers or ["name", "email"]
    index_column = index_column if index_column is not None else headers[-1]
    rows = list(rows or [])
    defaults = {
        "profile": profile,
        "name": name or f"Dataset {next_factory_id()}",
        "headers": headers,
        "index_column": index_column,
        "row_count": row_count if row_count is not None else len(rows),
    }
    defaults.update(overrides)
    dataset = Dataset.objects.create(**defaults)
    for row_number, data in enumerate(rows, start=1):
        index_value = str(data.get(index_column, row_number)) if index_column else ""
        create_dataset_row(dataset, row_number=row_number, index_value=index_value, data=data)
    return dataset


def create_ready_dataset(profile: Profile) -> Dataset:
    return create_dataset(
        profile,
        name="People",
        headers=["name", "email"],
        index_column="email",
        preview_rows=[{"name": "Ada", "email": "ada@example.com"}],
        rows=[
            {"name": "Ada", "email": "ada@example.com"},
            {"name": "Grace", "email": "grace@example.com"},
        ],
    )


def create_dataset_row(
    dataset: Dataset,
    *,
    row_number: int | None = None,
    index_value: str | None = None,
    data: dict[str, Any] | None = None,
    **overrides,
) -> DatasetRow:
    row_number = row_number or dataset.rows.count() + 1
    data = data or {}
    if index_value is None:
        index_value = str(data.get(dataset.index_column, row_number))
    return DatasetRow.objects.create(
        dataset=dataset,
        row_number=row_number,
        index_value=index_value,
        data=data,
        **overrides,
    )


def create_dataset_asset(
    dataset: Dataset,
    row: DatasetRow,
    *,
    column_name: str = "photo",
    file_name: str = "dataset-assets/test/original.png",
    **overrides,
) -> DatasetAsset:
    return DatasetAsset.objects.create(
        profile=dataset.profile,
        dataset=dataset,
        row=row,
        column_name=column_name,
        file=file_name,
        original_filename="photo.png",
        content_type="image/png",
        byte_size=10,
        width=3,
        height=2,
        checksum="a" * 64,
        **overrides,
    )


def create_dataset_relationship(
    source_dataset: Dataset,
    target_dataset: Dataset,
    *,
    source_column: str,
    name: str | None = None,
    enforce_integrity: bool = True,
) -> DatasetRelationship:
    return DatasetRelationship.objects.create(
        profile=source_dataset.profile,
        source_dataset=source_dataset,
        target_dataset=target_dataset,
        name=name or source_column,
        source_column=source_column,
        target_index_column=target_dataset.index_column,
        enforce_integrity=enforce_integrity,
    )


def create_crm_datasets(profile: Profile) -> tuple[Dataset, Dataset]:
    people = create_dataset(
        profile,
        name="People",
        headers=["person_id", "name", "email"],
        index_column="person_id",
        rows=[
            {
                "person_id": "P-1",
                "name": "Ada Lovelace",
                "email": "ada@example.com",
            }
        ],
    )
    messages = create_dataset(
        profile,
        name="CRM Messages",
        headers=["message_id", "person_id", "body"],
        index_column="message_id",
        rows=[
            {
                "message_id": "M-1",
                "person_id": "P-1",
                "body": "Intro call completed.",
            }
        ],
    )
    return people, messages


def configure_filterable_dataset(dataset: Dataset) -> Dataset:
    dataset.headers = ["name", "email", "score", "active"]
    dataset.column_schema = {
        "name": {"type": DatasetColumnType.TEXT},
        "email": {"type": DatasetColumnType.EMAIL},
        "score": {"type": DatasetColumnType.NUMBER},
        "active": {"type": DatasetColumnType.BOOLEAN},
    }
    dataset.row_count = 3
    dataset.rows.all().delete()
    dataset.save(update_fields=["headers", "column_schema", "row_count"])
    DatasetRow.objects.bulk_create(
        [
            DatasetRow(
                dataset=dataset,
                row_number=1,
                index_value="ada@example.com",
                data={
                    "name": "Ada Lovelace",
                    "email": "ada@example.com",
                    "score": "10.0",
                    "active": "true",
                },
            ),
            DatasetRow(
                dataset=dataset,
                row_number=2,
                index_value="grace@example.com",
                data={
                    "name": "Grace Hopper",
                    "email": "grace@example.com",
                    "score": "8",
                    "active": "false",
                },
            ),
            DatasetRow(
                dataset=dataset,
                row_number=3,
                index_value="katherine@example.com",
                data={
                    "name": "Katherine Johnson",
                    "email": "katherine@example.com",
                    "score": "010",
                    "active": "true",
                },
            ),
        ]
    )
    return dataset


def configure_datetime_dataset(dataset: Dataset) -> Dataset:
    dataset.headers = ["event_id", "event_name", "event_at"]
    dataset.column_schema = {
        "event_id": {"type": DatasetColumnType.TEXT},
        "event_name": {"type": DatasetColumnType.TEXT},
        "event_at": {"type": DatasetColumnType.DATETIME},
    }
    dataset.index_column = "event_id"
    dataset.row_count = 3
    dataset.rows.all().delete()
    dataset.save(update_fields=["headers", "column_schema", "index_column", "row_count"])
    DatasetRow.objects.bulk_create(
        [
            DatasetRow(
                dataset=dataset,
                row_number=1,
                index_value="E-1",
                data={
                    "event_id": "E-1",
                    "event_name": "UTC later",
                    "event_at": "2026-05-14T09:00:00Z",
                },
            ),
            DatasetRow(
                dataset=dataset,
                row_number=2,
                index_value="E-2",
                data={
                    "event_id": "E-2",
                    "event_name": "Offset early",
                    "event_at": "2026-05-14T10:00:00+02:00",
                },
            ),
            DatasetRow(
                dataset=dataset,
                row_number=3,
                index_value="E-3",
                data={
                    "event_id": "E-3",
                    "event_name": "Next day",
                    "event_at": "2026-05-15T08:00:00Z",
                },
            ),
        ]
    )
    return dataset


def add_invalid_datetime_row(dataset: Dataset) -> None:
    DatasetRow.objects.bulk_create(
        [
            DatasetRow(
                dataset=dataset,
                row_number=4,
                index_value="E-4",
                data={
                    "event_id": "E-4",
                    "event_name": "Invalid date",
                    "event_at": "2026-02-30",
                },
            ),
            DatasetRow(
                dataset=dataset,
                row_number=5,
                index_value="E-5",
                data={
                    "event_id": "E-5",
                    "event_name": "Invalid time",
                    "event_at": "2026-05-14T99:00:00Z",
                },
            ),
            DatasetRow(
                dataset=dataset,
                row_number=6,
                index_value="E-6",
                data={
                    "event_id": "E-6",
                    "event_name": "Invalid year",
                    "event_at": "not-a-date",
                },
            ),
        ]
    )
    dataset.row_count = 6
    dataset.save(update_fields=["row_count"])


def add_supported_datetime_format_rows(dataset: Dataset) -> None:
    rows = [
        ("E-7", "MDY slash", "05/14/2026 08:30 PM"),
        ("E-8", "YMD slash", "2026/05/13"),
        ("E-9", "YMD slash datetime", "2026/05/13 12:00"),
        ("E-10", "MDY slash date", "05/13/2026"),
        ("E-11", "MDY slash compact time", "05/14/2026 8:30"),
        ("E-12", "Century leap", "2000-02-29"),
        ("E-13", "Century slash leap", "02/29/2000"),
    ]
    DatasetRow.objects.bulk_create(
        [
            DatasetRow(
                dataset=dataset,
                row_number=7 + index,
                index_value=event_id,
                data={
                    "event_id": event_id,
                    "event_name": event_name,
                    "event_at": event_at,
                },
            )
            for index, (event_id, event_name, event_at) in enumerate(rows)
        ]
    )
    dataset.row_count = 3 + len(rows)
    dataset.save(update_fields=["row_count"])


class FakeEmbeddingProvider:
    model = "fake-embedding-model"
    dimensions = 3

    def __init__(self, vectors_by_text: dict[str, list[float]] | None = None):
        self.vectors_by_text = vectors_by_text or {}
        self.texts: list[str] = []
        self.text_batches: list[list[str]] = []

    def embed_text(self, text: str) -> EmbeddingResult:
        self.texts.append(text)
        return EmbeddingResult(
            vector=self.vectors_by_text.get(text, [0.1, 0.2, 0.3]),
            model=self.model,
            dimensions=self.dimensions,
        )

    def embed_texts(self, texts: list[str]) -> list[EmbeddingResult]:
        self.text_batches.append(texts)
        return [self.embed_text(text) for text in texts]


class FakeDatasetRowVectorStore:
    def __init__(self, hits: list[DatasetRowVectorSearchHit] | None = None):
        self.hits = hits or []
        self.searches: list[tuple[str, list[float], int]] = []
        self.upserts: list[tuple[Dataset, DatasetRow, list[float]]] = []
        self.deleted_row_ids: list[list[int]] = []
        self.deleted_datasets: list[Dataset] = []

    def search_dataset_rows(
        self,
        dataset: Dataset,
        vector: list[float],
        *,
        limit: int = 10,
    ) -> list[DatasetRowVectorSearchHit]:
        self.searches.append((str(dataset.key), vector, limit))
        return self.hits[:limit]

    def upsert_dataset_row_vector(
        self,
        dataset: Dataset,
        row: DatasetRow,
        vector: list[float],
        **kwargs,
    ) -> None:
        self.upserts.append((dataset, row, vector))

    def delete_dataset_row_vectors(self, dataset: Dataset, row_ids: list[int]) -> None:
        self.deleted_row_ids.append(row_ids)

    def delete_dataset_vectors(self, dataset: Dataset) -> None:
        self.deleted_datasets.append(dataset)
