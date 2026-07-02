import base64
import csv
import io
import json
import re
import sqlite3
import xml.etree.ElementTree as ET
import zipfile
from datetime import timedelta

import polars as pl
import pytest
from django.contrib import messages as message_constants
from django.contrib.messages import get_messages
from django.core.files.storage import storages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from apps.api.services import (
    DatasetServiceError,
    attach_profile_dataset_image_asset,
    create_profile_dataset,
    create_profile_dataset_row,
    list_profile_dataset_rows,
    patch_profile_dataset_row,
    serialize_dataset_detail,
)
from apps.core.analytics import ROWSET_DATASET_ROW_MUTATED
from apps.core.choices import ProfileStates
from apps.core.services import create_agent_api_key
from apps.datasets import models as dataset_models
from apps.datasets.choices import DatasetColumnType, DatasetMutationType, DatasetStatus
from apps.datasets.constants import MAX_DATASET_IMAGE_BYTES
from apps.datasets.history import record_dataset_mutation
from apps.datasets.models import (
    DATASET_ASSET_STORAGE_ALIAS,
    Dataset,
    DatasetAsset,
    DatasetAssetFileDeletion,
    DatasetMutation,
    DatasetRelationship,
    DatasetRow,
    Project,
    retry_dataset_asset_file_deletions,
)
from apps.datasets.services import (
    CSVParseError,
    DatasetImageError,
    apply_dataset_row_query,
    choice_constraints_from_schema,
    decode_image_base64,
    infer_column_type,
    normalize_column_schema,
    prepare_dataset_image,
    preview_csv_file,
    preview_uploaded_table,
    rows_to_sqlite_bytes,
)
from apps.datasets.tasks import import_dataset_rows
from apps.datasets.views import (
    DATASET_CHANGES_PAGE_SIZE,
    DATASET_DETAIL_ROW_PAGE_SIZE,
    PROJECT_DETAIL_DATASET_PAGE_SIZE,
)

pytestmark = pytest.mark.django_db


def csv_upload(content="name,email\nAda,ada@example.com\nGrace,grace@example.com\n"):
    return SimpleUploadedFile("people.csv", content.encode(), content_type="text/csv")


def parquet_upload(data=None):
    buffer = io.BytesIO()
    pl.DataFrame(
        data
        or {
            "name": ["Ada", "Grace"],
            "email": ["ada@example.com", "grace@example.com"],
            "score": [10, None],
        }
    ).write_parquet(buffer)
    return SimpleUploadedFile(
        "people.parquet",
        buffer.getvalue(),
        content_type="application/vnd.apache.parquet",
    )


def image_base64() -> str:
    return base64.b64encode(image_bytes()).decode()


def image_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (3, 2), (12, 34, 56)).save(buffer, format="PNG")
    return buffer.getvalue()


def palette_image_bytes() -> bytes:
    buffer = io.BytesIO()
    image = Image.new("P", (3, 2), 0)
    image.putpalette([12, 34, 56, 240, 244, 248] + [0, 0, 0] * 254)
    image.putdata([0, 1, 0, 1, 0, 1])
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def xlsx_cell_texts(content: bytes) -> list[str]:
    root = ET.fromstring(xlsx_sheet_xml(content))
    namespace = {"xlsx": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    return [element.text or "" for element in root.findall(".//xlsx:t", namespace)]


def xlsx_sheet_xml(content: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(content)) as workbook:
        return workbook.read("xl/worksheets/sheet1.xml").decode()


def sqlite_rows(content: bytes) -> list[dict[str, str]]:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    try:
        connection.deserialize(content)
        return [dict(row) for row in connection.execute("SELECT * FROM rows")]
    finally:
        connection.close()


def sqlite_table_columns(content: bytes, table_name: str = "rows") -> list[str]:
    connection = sqlite3.connect(":memory:")
    try:
        connection.deserialize(content)
        return [row[1] for row in connection.execute(f"PRAGMA table_info({table_name})")]
    finally:
        connection.close()


def create_ready_dataset(profile):
    dataset = Dataset.objects.create(
        profile=profile,
        name="People",
        original_filename="people.csv",
        source_file=csv_upload(),
        status=DatasetStatus.READY,
        headers=["name", "email"],
        index_column="email",
        preview_rows=[{"name": "Ada", "email": "ada@example.com"}],
        row_count=2,
    )
    DatasetRow.objects.create(
        dataset=dataset,
        row_number=1,
        index_value="ada@example.com",
        data={"name": "Ada", "email": "ada@example.com"},
    )
    DatasetRow.objects.create(
        dataset=dataset,
        row_number=2,
        index_value="grace@example.com",
        data={"name": "Grace", "email": "grace@example.com"},
    )
    return dataset


def create_crm_datasets(profile):
    people = Dataset.objects.create(
        profile=profile,
        name="People",
        original_filename="Created via API",
        file_type="api",
        status=DatasetStatus.READY,
        headers=["person_id", "name", "email"],
        index_column="person_id",
        row_count=1,
        confirmed_at=timezone.now(),
        processed_at=timezone.now(),
    )
    DatasetRow.objects.create(
        dataset=people,
        row_number=1,
        index_value="P-1",
        data={
            "person_id": "P-1",
            "name": "Ada Lovelace",
            "email": "ada@example.com",
        },
    )
    messages = Dataset.objects.create(
        profile=profile,
        name="CRM Messages",
        original_filename="Created via API",
        file_type="api",
        status=DatasetStatus.READY,
        headers=["message_id", "person_id", "body"],
        index_column="message_id",
        row_count=1,
        confirmed_at=timezone.now(),
        processed_at=timezone.now(),
    )
    DatasetRow.objects.create(
        dataset=messages,
        row_number=1,
        index_value="M-1",
        data={
            "message_id": "M-1",
            "person_id": "P-1",
            "body": "Intro call completed.",
        },
    )
    return people, messages


def configure_filterable_dataset(dataset):
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


def configure_datetime_dataset(dataset):
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


TYPED_ROW_HEADERS = [
    "row_id",
    "status",
    "active",
    "due_on",
    "scheduled_at",
    "count",
    "score",
    "budget",
    "contact",
    "website",
    "related_dataset",
    "notes",
    "photo",
]


def typed_row_data(**overrides):
    data = {
        "row_id": "ROW-1",
        "status": "Backlog",
        "active": "true",
        "due_on": "2026-07-01",
        "scheduled_at": "2026-07-01T09:30",
        "count": "2",
        "score": "9.5",
        "budget": "120.00",
        "contact": "ada@example.com",
        "website": "https://example.com",
        "related_dataset": "",
        "notes": "Initial row",
        "photo": "",
    }
    data.update(overrides)
    return data


def typed_row_post_data(**overrides):
    data = typed_row_data(**overrides)
    data.pop("photo")
    return data


def create_typed_row_dataset(profile):
    row_data = typed_row_data()
    dataset = Dataset.objects.create(
        profile=profile,
        name="Typed rows",
        original_filename="Created via API",
        file_type="api",
        status=DatasetStatus.READY,
        headers=TYPED_ROW_HEADERS,
        index_column="row_id",
        row_count=1,
        column_schema={
            "row_id": {"type": DatasetColumnType.TEXT},
            "status": {
                "type": DatasetColumnType.CHOICE,
                "choices": ["Backlog", "Doing", "Done"],
            },
            "active": {"type": DatasetColumnType.BOOLEAN},
            "due_on": {"type": DatasetColumnType.DATE},
            "scheduled_at": {"type": DatasetColumnType.DATETIME},
            "count": {"type": DatasetColumnType.INTEGER},
            "score": {"type": DatasetColumnType.NUMBER},
            "budget": {"type": DatasetColumnType.CURRENCY},
            "contact": {"type": DatasetColumnType.EMAIL},
            "website": {"type": DatasetColumnType.URL},
            "related_dataset": {"type": DatasetColumnType.REFERENCE},
            "notes": {"type": DatasetColumnType.TEXT},
            "photo": {"type": DatasetColumnType.IMAGE},
        },
    )
    DatasetRow.objects.create(
        dataset=dataset,
        row_number=1,
        index_value="ROW-1",
        data=row_data,
    )
    return dataset


def add_invalid_datetime_row(dataset):
    DatasetRow.objects.bulk_create(
        [
            DatasetRow(
                dataset=dataset,
                row_number=4,
                index_value="E-4",
                data={
                    "event_id": "E-4",
                    "event_name": "Invalid date",
                    "event_at": "2026-13-01",
                },
            ),
            DatasetRow(
                dataset=dataset,
                row_number=5,
                index_value="E-5",
                data={
                    "event_id": "E-5",
                    "event_name": "Invalid time",
                    "event_at": "2026-05-14T29:00:00Z",
                },
            ),
            DatasetRow(
                dataset=dataset,
                row_number=6,
                index_value="E-6",
                data={
                    "event_id": "E-6",
                    "event_name": "Invalid year",
                    "event_at": "0000-01-01",
                },
            ),
        ]
    )
    dataset.row_count = 6
    dataset.save(update_fields=["row_count"])
    return dataset


def add_supported_datetime_format_rows(dataset):
    DatasetRow.objects.bulk_create(
        [
            DatasetRow(
                dataset=dataset,
                row_number=4,
                index_value="E-4",
                data={
                    "event_id": "E-4",
                    "event_name": "YMD slash",
                    "event_at": "2026/05/13",
                },
            ),
            DatasetRow(
                dataset=dataset,
                row_number=5,
                index_value="E-5",
                data={
                    "event_id": "E-5",
                    "event_name": "MDY slash",
                    "event_at": "05/14/2026 08:45",
                },
            ),
            DatasetRow(
                dataset=dataset,
                row_number=6,
                index_value="E-6",
                data={
                    "event_id": "E-6",
                    "event_name": "Century leap",
                    "event_at": "2000-02-29",
                },
            ),
            DatasetRow(
                dataset=dataset,
                row_number=7,
                index_value="E-7",
                data={
                    "event_id": "E-7",
                    "event_name": "Century slash leap",
                    "event_at": "02/29/2000",
                },
            ),
            DatasetRow(
                dataset=dataset,
                row_number=8,
                index_value="E-8",
                data={
                    "event_id": "E-8",
                    "event_name": "YMD slash datetime",
                    "event_at": "2026/5/13 8:45",
                },
            ),
            DatasetRow(
                dataset=dataset,
                row_number=9,
                index_value="E-9",
                data={
                    "event_id": "E-9",
                    "event_name": "MDY slash date",
                    "event_at": "5/14/2026",
                },
            ),
            DatasetRow(
                dataset=dataset,
                row_number=10,
                index_value="E-10",
                data={
                    "event_id": "E-10",
                    "event_name": "MDY slash compact time",
                    "event_at": "5/14/2026 8:5",
                },
            ),
        ]
    )
    dataset.row_count = dataset.rows.count()
    dataset.save(update_fields=["row_count"])
    return dataset


def test_preview_csv_file_returns_headers_sample_and_count():
    preview = preview_csv_file(csv_upload())

    assert preview.headers == ["name", "email"]
    assert preview.text == "name,email\nAda,ada@example.com\nGrace,grace@example.com\n"
    assert preview.row_count == 2
    assert preview.preview_rows == [
        {"name": "Ada", "email": "ada@example.com"},
        {"name": "Grace", "email": "grace@example.com"},
    ]
    assert preview.column_schema == {
        "name": {"type": "text"},
        "email": {"type": "email"},
    }


def test_infer_column_type_detects_common_semantic_types():
    assert infer_column_type("id", ["1", "2"]) == "integer"
    assert infer_column_type("score", ["98.5", "100"]) == "number"
    assert infer_column_type("price", ["19.99", "29"]) == "currency"
    assert infer_column_type("total_items", ["1", "2"]) == "integer"
    assert infer_column_type("active", ["true", "false"]) == "boolean"
    assert infer_column_type("launched_on", ["2026-05-14", "2026-05-15"]) == "date"
    assert infer_column_type("created_at", ["2026-05-14T10:15:00Z"]) == "datetime"
    assert infer_column_type("email", ["ada@example.com"]) == "email"
    assert infer_column_type("website", ["https://example.com"]) == "url"
    assert infer_column_type("date", ["31/01/2026"]) == "text"
    assert infer_column_type("mixed", ["Ada", "10"]) == "text"


def test_preview_csv_file_rejects_duplicate_headers():
    with pytest.raises(CSVParseError, match="Duplicate headers"):
        preview_csv_file(csv_upload("name,name\nAda,Lovelace\n"))


def test_preview_uploaded_table_strips_parquet_header_whitespace():
    preview = preview_uploaded_table(
        parquet_upload({" name ": ["Ada"], " email ": ["ada@example.com"]}),
        "people.parquet",
    )

    assert preview.headers == ["name", "email"]
    assert preview.preview_rows == [{"name": "Ada", "email": "ada@example.com"}]


def test_preview_uploaded_table_accepts_parquet_files():
    preview = preview_uploaded_table(parquet_upload(), "people.parquet")

    assert preview.file_type == "parquet"
    assert preview.headers == ["name", "email", "score"]
    assert preview.row_count == 2
    assert preview.preview_rows == [
        {"name": "Ada", "email": "ada@example.com", "score": "10"},
        {"name": "Grace", "email": "grace@example.com", "score": ""},
    ]
    assert (
        preview.source_text
        == 'name,email,score\nAda,ada@example.com,10\nGrace,grace@example.com,""\n'
    )


def test_import_uses_stored_source_text_when_file_is_not_available(profile):
    dataset = Dataset.objects.create(
        profile=profile,
        name="People",
        original_filename="people.csv",
        source_file="datasets/csv/missing.csv",
        source_text="name,email\nAda,ada@example.com\nGrace,grace@example.com\n",
        status=DatasetStatus.PROCESSING,
        headers=["name", "email"],
        index_column="email",
        preview_rows=[{"name": "Ada", "email": "ada@example.com"}],
        row_count=2,
    )

    import_dataset_rows(dataset.id)

    dataset.refresh_from_db()
    assert dataset.status == DatasetStatus.READY
    assert dataset.rows.count() == 2


def test_import_enqueues_vector_reindex_after_commit_when_enabled(
    profile,
    django_capture_on_commit_callbacks,
    monkeypatch,
):
    dataset = Dataset.objects.create(
        profile=profile,
        name="People",
        original_filename="people.csv",
        source_file="datasets/csv/missing.csv",
        source_text="name,email\nAda,ada@example.com\nGrace,grace@example.com\n",
        status=DatasetStatus.PROCESSING,
        headers=["name", "email"],
        index_column="email",
        preview_rows=[{"name": "Ada", "email": "ada@example.com"}],
        row_count=2,
    )
    stale_row = DatasetRow.objects.create(
        dataset=dataset,
        row_number=1,
        index_value="old@example.com",
        data={"name": "Old", "email": "old@example.com"},
    )
    calls = []
    monkeypatch.setattr(
        "apps.datasets.vector_tasks.async_task",
        lambda task_path, *args: calls.append((task_path, args)),
    )

    with override_settings(ROWSET_VECTOR_SEARCH_ENABLED=True):
        with django_capture_on_commit_callbacks(execute=True):
            import_dataset_rows(dataset.id)

    dataset.refresh_from_db()
    assert dataset.status == DatasetStatus.READY
    assert calls == [
        ("apps.datasets.tasks.delete_dataset_row_vectors", (dataset.id, [stale_row.id])),
        ("apps.datasets.tasks.reindex_dataset_vectors_task", (dataset.id,)),
    ]


def test_import_chunks_stale_vector_delete_tasks_when_enabled(
    profile,
    django_capture_on_commit_callbacks,
    monkeypatch,
):
    dataset = Dataset.objects.create(
        profile=profile,
        name="People",
        original_filename="people.csv",
        source_file="datasets/csv/missing.csv",
        source_text="name,email\nAda,ada@example.com\nGrace,grace@example.com\n",
        status=DatasetStatus.PROCESSING,
        headers=["name", "email"],
        index_column="email",
        row_count=3,
    )
    stale_rows = [
        DatasetRow.objects.create(
            dataset=dataset,
            row_number=index,
            index_value=f"old-{index}@example.com",
            data={"name": f"Old {index}", "email": f"old-{index}@example.com"},
        )
        for index in range(1, 4)
    ]
    calls = []
    monkeypatch.setattr(
        "apps.datasets.vector_tasks.async_task",
        lambda task_path, *args: calls.append((task_path, args)),
    )
    monkeypatch.setattr("apps.datasets.tasks.VECTOR_ROW_DELETE_TASK_BATCH_SIZE", 2)

    with override_settings(ROWSET_VECTOR_SEARCH_ENABLED=True):
        with django_capture_on_commit_callbacks(execute=True):
            import_dataset_rows(dataset.id)

    assert calls == [
        (
            "apps.datasets.tasks.delete_dataset_row_vectors",
            (dataset.id, [stale_rows[0].id, stale_rows[1].id]),
        ),
        ("apps.datasets.tasks.delete_dataset_row_vectors", (dataset.id, [stale_rows[2].id])),
        ("apps.datasets.tasks.reindex_dataset_vectors_task", (dataset.id,)),
    ]


def test_import_file_fallback_uses_selected_index_column(profile):
    dataset = Dataset.objects.create(
        profile=profile,
        name="People",
        original_filename="people.csv",
        source_file=csv_upload(),
        source_text="",
        status=DatasetStatus.PROCESSING,
        headers=["name", "email"],
        index_column="email",
        preview_rows=[{"name": "Ada", "email": "ada@example.com"}],
        row_count=2,
    )

    import_dataset_rows(dataset.id)

    dataset.refresh_from_db()
    assert dataset.status == DatasetStatus.READY
    assert dataset.rows.first().index_value == "ada@example.com"


def test_dataset_list_hides_unconfirmed_preview_dataset(auth_client, profile):
    create_ready_dataset(profile)
    Dataset.objects.create(
        profile=profile,
        name="Preview Only",
        original_filename="preview.csv",
        status=DatasetStatus.PREVIEWED,
        headers=["name"],
        preview_rows=[{"name": "Ada"}],
        row_count=1,
    )

    response = auth_client.get(reverse("home"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "People" in content
    assert "Preview Only" not in content


def test_dataset_and_project_index_pages_redirect_to_home(auth_client):
    dataset_response = auth_client.get(reverse("dataset_list"))
    project_response = auth_client.get(reverse("project_list"))

    assert dataset_response.status_code == 302
    assert dataset_response["Location"] == reverse("home")
    assert project_response.status_code == 302
    assert project_response["Location"] == reverse("home")


def test_dataset_list_supports_search_sort_and_omits_row_actions(auth_client, profile):
    project = Project.objects.create(profile=profile, name="Research")
    dataset = create_ready_dataset(profile)
    dataset.project = project
    dataset.public_enabled = True
    dataset.save(update_fields=["project", "public_enabled"])
    Dataset.objects.create(
        profile=profile,
        name="Invoices",
        original_filename="invoices.csv",
        status=DatasetStatus.READY,
        headers=["invoice_id"],
        row_count=10,
    )

    response = auth_client.get(reverse("home"), {"q": "people", "sort": "rows"})

    content = response.content.decode()
    assert response.status_code == 200
    assert response.context["search_query"] == "people"
    assert response.context["selected_sort"] == "rows"
    assert response.context["dataset_stats"] == {
        "total_datasets": 2,
        "total_rows": 12,
        "public_preview_count": 1,
        "total_projects": 1,
    }
    assert "<title>Dashboard · Rowset</title>" in content
    assert "Search datasets" in content
    assert "People" in content
    assert "Research" in content
    assert "Invoices" not in content
    assert reverse("archived_dataset_list") in content
    assert reverse("dataset_export", args=[dataset.key, "csv"]) not in content
    assert reverse("dataset_export", args=[dataset.key, "parquet"]) not in content
    assert reverse("dataset_delete", args=[dataset.key]) not in content
    assert "Dataset status" not in content


def test_home_defaults_to_project_grouped_recent_order(auth_client, profile):
    older_dataset = Dataset.objects.create(
        profile=profile,
        name="Alpha",
        original_filename="alpha.csv",
        status=DatasetStatus.READY,
        headers=["id"],
        index_column="id",
    )
    newer_dataset = Dataset.objects.create(
        profile=profile,
        name="Beta",
        original_filename="beta.csv",
        status=DatasetStatus.READY,
        headers=["id"],
        index_column="id",
    )
    now = timezone.now()
    Dataset.objects.filter(pk=older_dataset.pk).update(
        created_at=now - timedelta(days=4),
        updated_at=now - timedelta(days=2),
    )
    Dataset.objects.filter(pk=newer_dataset.pk).update(
        created_at=now - timedelta(days=3),
        updated_at=now - timedelta(days=1),
    )

    response = auth_client.get(reverse("home"))

    assert response.status_code == 200
    assert response.context["selected_view_mode"] == "grouped"
    assert response.context["selected_sort"] == "recent"
    assert [group["label"] for group in response.context["dataset_groups"]] == ["No project"]
    assert [dataset.name for dataset in response.context["datasets"]] == ["Beta", "Alpha"]


def test_dataset_list_supports_created_sort(auth_client, profile):
    older_created_dataset = Dataset.objects.create(
        profile=profile,
        name="Recently updated",
        original_filename="recently-updated.csv",
        status=DatasetStatus.READY,
        headers=["id"],
        index_column="id",
    )
    newer_created_dataset = Dataset.objects.create(
        profile=profile,
        name="Recently created",
        original_filename="recently-created.csv",
        status=DatasetStatus.READY,
        headers=["id"],
        index_column="id",
    )
    now = timezone.now()
    Dataset.objects.filter(pk=older_created_dataset.pk).update(
        created_at=now - timedelta(days=6),
        updated_at=now,
    )
    Dataset.objects.filter(pk=newer_created_dataset.pk).update(
        created_at=now - timedelta(days=1),
        updated_at=now - timedelta(days=5),
    )

    response = auth_client.get(reverse("home"), {"sort": "created"})

    assert response.status_code == 200
    assert response.context["selected_sort"] == "created"
    assert response.context["dataset_table_date_heading"] == "Created"
    assert [dataset.name for dataset in response.context["datasets"]] == [
        "Recently created",
        "Recently updated",
    ]


def test_home_project_sort_puts_unassigned_dataset_group_last(auth_client, profile):
    project = Project.objects.create(profile=profile, name="Research")
    Dataset.objects.create(
        profile=profile,
        name="Alpha loose dataset",
        original_filename="loose.csv",
        status=DatasetStatus.READY,
        headers=["id"],
        index_column="id",
    )
    Dataset.objects.create(
        profile=profile,
        project=project,
        name="Zulu project dataset",
        original_filename="project.csv",
        status=DatasetStatus.READY,
        headers=["id"],
        index_column="id",
    )

    response = auth_client.get(reverse("home"), {"sort": "project", "view": "raw"})

    assert response.status_code == 200
    assert response.context["selected_view_mode"] == "grouped"
    assert [group["label"] for group in response.context["dataset_groups"]] == [
        "Research",
        "No project",
    ]
    assert [dataset.name for dataset in response.context["datasets"]] == [
        "Zulu project dataset",
        "Alpha loose dataset",
    ]


def test_dataset_list_groups_datasets_by_project(auth_client, profile):
    research = Project.objects.create(
        profile=profile,
        name="Research",
        description="Datasets for customer interviews.",
    )
    launch = Project.objects.create(profile=profile, name="Launch")
    people = create_ready_dataset(profile)
    people.project = research
    people.row_count = 10
    people.save(update_fields=["project", "row_count"])
    notes = Dataset.objects.create(
        profile=profile,
        project=research,
        name="Research notes",
        original_filename="notes.csv",
        status=DatasetStatus.READY,
        headers=["note_id", "body"],
        index_column="note_id",
        row_count=1,
    )
    Dataset.objects.create(
        profile=profile,
        project=launch,
        name="Launch tasks",
        original_filename="tasks.csv",
        status=DatasetStatus.READY,
        headers=["task_id", "owner"],
        index_column="task_id",
        row_count=8,
    )
    Dataset.objects.create(
        profile=profile,
        name="Loose contacts",
        original_filename="contacts.csv",
        status=DatasetStatus.READY,
        headers=["email"],
        index_column="email",
        row_count=4,
    )

    response = auth_client.get(reverse("home"), {"sort": "rows", "view": "grouped"})

    content = response.content.decode()
    groups = response.context["dataset_groups"]
    assert response.status_code == 200
    assert response.context["selected_view_mode"] == "grouped"
    assert [group["label"] for group in groups] == ["Launch", "Research", "No project"]
    assert [dataset.name for dataset in groups[1]["datasets"]] == ["People", notes.name]
    assert groups[1]["dataset_count"] == 2
    assert groups[1]["row_count"] == 11
    assert "Datasets by project" in content
    assert "border-l-2 border-emerald-200" not in content
    assert "Datasets for customer interviews." in content
    assert "2 datasets · 11 rows" in content
    assert "No project" in content
    assert "Datasets that are not assigned to a project." in content


def test_home_groups_project_datasets_by_section(auth_client, profile):
    project = Project.objects.create(profile=profile, name="Content")
    blog = dataset_models.ProjectSection.objects.create(
        profile=profile,
        project=project,
        name="Blog",
    )
    Dataset.objects.create(
        profile=profile,
        project=project,
        section=blog,
        name="Content ledger",
        original_filename="content.csv",
        status=DatasetStatus.READY,
        headers=["slug"],
        index_column="slug",
    )
    Dataset.objects.create(
        profile=profile,
        project=project,
        name="Topic backlog",
        original_filename="topics.csv",
        status=DatasetStatus.READY,
        headers=["topic"],
        index_column="topic",
    )

    response = auth_client.get(reverse("home"))

    content = response.content.decode()
    group = response.context["dataset_groups"][0]
    assert response.status_code == 200
    assert group["label"] == "Content"
    assert [section_group["label"] for section_group in group["section_groups"]] == [
        "Blog",
        "Unsectioned",
    ]
    assert group["section_groups"][0]["datasets"][0].name == "Content ledger"
    assert group["section_groups"][1]["datasets"][0].name == "Topic backlog"
    assert "Blog" in content
    assert "Unsectioned" in content


def test_dataset_list_group_counts_use_filtered_totals_across_pages(auth_client, profile):
    project = Project.objects.create(profile=profile, name="Research")
    for index in range(101):
        Dataset.objects.create(
            profile=profile,
            project=project,
            name=f"Research dataset {index:03}",
            original_filename=f"research-{index:03}.csv",
            status=DatasetStatus.READY,
            headers=["record_id"],
            index_column="record_id",
            row_count=1,
        )

    page_one = auth_client.get(reverse("home"), {"sort": "name", "view": "grouped"})
    page_two = auth_client.get(f"{reverse('home')}?sort=name&view=grouped&page=2")

    assert page_one.status_code == 200
    assert page_two.status_code == 200
    assert len(page_one.context["dataset_groups"][0]["datasets"]) == 100
    assert len(page_two.context["dataset_groups"][0]["datasets"]) == 1
    for response in (page_one, page_two):
        group = response.context["dataset_groups"][0]
        assert group["label"] == "Research"
        assert group["dataset_count"] == 101
        assert group["row_count"] == 101
        assert "101 datasets · 101 rows" in response.content.decode()


def test_archived_dataset_list_shows_archived_datasets_only(
    auth_client,
    django_user_model,
    profile,
):
    project = Project.objects.create(profile=profile, name="Research")
    active_project = Project.objects.create(profile=profile, name="Active only")
    active_dataset = create_ready_dataset(profile)
    active_dataset.name = "Archived active people"
    active_dataset.project = active_project
    active_dataset.save(update_fields=["name", "project"])
    archived_dataset = Dataset.objects.create(
        profile=profile,
        project=project,
        name="Archived people",
        original_filename="archived-people.csv",
        file_type="api",
        status=DatasetStatus.READY,
        headers=["email"],
        index_column="email",
        row_count=4,
        archived_at=timezone.now(),
    )
    Dataset.objects.create(
        profile=profile,
        name="Archived draft",
        original_filename="draft.csv",
        status=DatasetStatus.PREVIEWED,
        headers=["email"],
        index_column="email",
        archived_at=timezone.now(),
    )
    other_user = django_user_model.objects.create_user(
        username="other-archive-list",
        email="other-archive-list@example.com",
        password="password123",
    )
    Dataset.objects.create(
        profile=other_user.profile,
        name="Archived other account dataset",
        original_filename="other.csv",
        file_type="api",
        status=DatasetStatus.READY,
        headers=["email"],
        index_column="email",
        archived_at=timezone.now(),
    )

    response = auth_client.get(
        reverse("archived_dataset_list"),
        {"q": "archived", "sort": "archived"},
    )

    content = response.content.decode()
    assert response.status_code == 200
    assert [dataset.key for dataset in response.context["datasets"]] == [archived_dataset.key]
    assert response.context["search_query"] == "archived"
    assert response.context["selected_sort"] == "archived"
    assert response.context["dataset_stats"] == {
        "total_datasets": 1,
        "total_rows": 4,
        "public_preview_count": 0,
        "total_projects": 1,
    }
    assert "<title>Archived datasets · Rowset</title>" in content
    assert "Archived datasets" in content
    assert "Archived rows" in content
    assert "Archived projects" in content
    assert "Search archived datasets" in content
    assert "Active datasets" in content
    assert "Archived people" in content
    assert "Research" in content
    assert "Active only" not in content
    assert "Archived active people" not in content
    assert "Archived draft" not in content
    assert "Archived other account dataset" not in content
    assert reverse("home") in content
    assert f'href="{reverse("project_list")}"' not in content
    assert reverse("dataset_export", args=[archived_dataset.key, "csv"]) not in content
    assert reverse("dataset_delete", args=[archived_dataset.key]) not in content


def test_archived_dataset_list_paginates_archived_datasets(auth_client, profile):
    for index in range(101):
        Dataset.objects.create(
            profile=profile,
            name=f"Archived dataset {index:03}",
            original_filename="Created via API",
            file_type="api",
            status=DatasetStatus.READY,
            headers=["email"],
            index_column="email",
            row_count=0,
            archived_at=timezone.now(),
        )

    response = auth_client.get(reverse("archived_dataset_list"))
    content = response.content.decode()

    assert response.status_code == 200
    assert len(response.context["datasets"]) == 100
    assert "Page 1 of 2" in content

    page_two = auth_client.get(f"{reverse('archived_dataset_list')}?page=2")

    assert page_two.status_code == 200
    assert len(page_two.context["datasets"]) == 1
    assert "Page 2 of 2" in page_two.content.decode()


def test_dataset_detail_orders_row_cells_by_headers(auth_client, profile):
    dataset = Dataset.objects.create(
        profile=profile,
        name="Customers",
        original_filename="customers.csv",
        source_text="customer_id,name,plan\nC-1001,Ada Lovelace,Scale\n",
        status=DatasetStatus.READY,
        headers=["customer_id", "name", "plan"],
        preview_rows=[{"name": "Ada Lovelace", "plan": "Scale", "customer_id": "C-1001"}],
        index_column="customer_id",
        row_count=1,
    )
    DatasetRow.objects.create(
        dataset=dataset,
        row_number=1,
        index_value="C-1001",
        data={"name": "Ada Lovelace", "plan": "Scale", "customer_id": "C-1001"},
    )

    response = auth_client.get(dataset.get_absolute_url())
    content = response.content.decode()

    assert response.status_code == 200
    assert "<title>Customers · Rowset</title>" in content
    customer_id_position = content.index("C-1001")
    name_position = content.index("Ada Lovelace")
    plan_position = content.index("Scale")
    assert customer_id_position < name_position < plan_position


def test_dataset_detail_links_imported_rows_and_truncates_cells(auth_client, profile):
    dataset = create_ready_dataset(profile)
    row = dataset.rows.first()

    response = auth_client.get(dataset.get_absolute_url())
    content = response.content.decode()

    assert response.status_code == 200
    assert reverse("dataset_row_detail", args=[dataset.key, row.id]) in content
    assert 'class="fb-focus block max-w-64 truncate' in content
    assert 'aria-label="View row 1 details"' in content
    assert content.count('aria-label="View row 1 details"') == 1
    assert 'aria-hidden="true" tabindex="-1"' in content


def test_dataset_detail_links_row_create_and_bulk_actions(auth_client, profile):
    dataset = create_ready_dataset(profile)
    row = dataset.rows.first()

    response = auth_client.get(dataset.get_absolute_url())
    content = response.content.decode()

    assert response.status_code == 200
    assert reverse("dataset_row_create", args=[dataset.key]) in content
    assert reverse("dataset_rows_bulk_action", args=[dataset.key]) in content
    assert "Delete selected rows" in content
    assert f'value="{row.id}"' in content
    assert 'x-data="rowBulkActions"' in content


def test_dataset_detail_links_dataset_reference_cells(auth_client, profile):
    target = create_ready_dataset(profile)
    target.name = "Archived sprint tasks"
    target.archived_at = timezone.now()
    target.save(update_fields=["name", "archived_at"])
    source = Dataset.objects.create(
        profile=profile,
        name="Sprint history",
        original_filename="Created via API",
        file_type="api",
        status=DatasetStatus.READY,
        headers=["sprint_id", "task_dataset"],
        column_schema={
            "sprint_id": {"type": DatasetColumnType.TEXT},
            "task_dataset": {
                "type": DatasetColumnType.REFERENCE,
                "target": "dataset",
            },
        },
        index_column="sprint_id",
        row_count=1,
        confirmed_at=timezone.now(),
        processed_at=timezone.now(),
    )
    DatasetRow.objects.create(
        dataset=source,
        row_number=1,
        index_value="SPRINT-1",
        data={
            "sprint_id": "SPRINT-1",
            "task_dataset": str(target.key),
        },
    )

    response = auth_client.get(source.get_absolute_url())
    content = response.content.decode()

    assert response.status_code == 200
    assert f'href="{target.get_absolute_url()}"' in content
    assert "Archived sprint tasks" in content
    assert "Archived dataset" in content


def test_dataset_detail_links_project_reference_cells(auth_client, profile):
    target = Project.objects.create(
        profile=profile,
        name="Launch ops",
        description="Project referenced from a dataset cell.",
    )
    source = Dataset.objects.create(
        profile=profile,
        name="Sprint history",
        original_filename="Created via API",
        file_type="api",
        status=DatasetStatus.READY,
        headers=["sprint_id", "owning_project"],
        column_schema={
            "sprint_id": {"type": DatasetColumnType.TEXT},
            "owning_project": {
                "type": DatasetColumnType.REFERENCE,
                "target": "project",
            },
        },
        index_column="sprint_id",
        row_count=1,
        confirmed_at=timezone.now(),
        processed_at=timezone.now(),
    )
    DatasetRow.objects.create(
        dataset=source,
        row_number=1,
        index_value="SPRINT-1",
        data={
            "sprint_id": "SPRINT-1",
            "owning_project": str(target.key),
        },
    )

    response = auth_client.get(source.get_absolute_url())
    content = response.content.decode()

    assert response.status_code == 200
    assert f'href="{target.get_absolute_url()}"' in content
    assert "Launch ops" in content


def test_dataset_detail_renders_archived_project_reference_cells_without_dead_link(
    auth_client,
    profile,
):
    target = Project.objects.create(profile=profile, name="Archived launch ops")
    target.archived_at = timezone.now()
    target.save(update_fields=["archived_at"])
    source = Dataset.objects.create(
        profile=profile,
        name="Sprint history",
        original_filename="Created via API",
        file_type="api",
        status=DatasetStatus.READY,
        headers=["sprint_id", "owning_project"],
        column_schema={
            "sprint_id": {"type": DatasetColumnType.TEXT},
            "owning_project": {
                "type": DatasetColumnType.REFERENCE,
                "target": "project",
            },
        },
        index_column="sprint_id",
        row_count=1,
        confirmed_at=timezone.now(),
        processed_at=timezone.now(),
    )
    DatasetRow.objects.create(
        dataset=source,
        row_number=1,
        index_value="SPRINT-1",
        data={
            "sprint_id": "SPRINT-1",
            "owning_project": str(target.key),
        },
    )

    response = auth_client.get(source.get_absolute_url())
    content = response.content.decode()

    assert response.status_code == 200
    assert f'href="{target.get_absolute_url()}"' not in content
    assert "Archived launch ops" in content


def test_dataset_detail_renders_rowset_dataset_urls_as_text(
    auth_client,
    profile,
):
    source_dataset = create_ready_dataset(profile)
    target_dataset = Dataset.objects.create(
        profile=profile,
        name="Sprint task board",
        original_filename="Created via API",
        file_type="api",
        status=DatasetStatus.READY,
        headers=["task_id", "title"],
        index_column="task_id",
        row_count=0,
    )
    source_dataset.headers = ["name", "task_dataset_url"]
    source_dataset.save(update_fields=["headers"])
    row = source_dataset.rows.first()
    raw_url = f"https://rowset.lvtd.dev/datasets/{target_dataset.key}/"
    row.data = {
        "name": "Review Gate Sprint History",
        "task_dataset_url": raw_url,
    }
    row.save(update_fields=["data"])

    response = auth_client.get(source_dataset.get_absolute_url())
    content = response.content.decode()

    assert response.status_code == 200
    assert raw_url in content
    assert f'href="{target_dataset.get_absolute_url()}"' not in content
    assert "Sprint task board" not in content
    assert "Ready" not in content
    assert "Open Rowset dataset Sprint task board" not in content


def test_dataset_detail_keeps_row_detail_link_for_single_rowset_url_column(
    auth_client,
    profile,
):
    source_dataset = create_ready_dataset(profile)
    target_dataset = create_ready_dataset(profile)
    target_dataset.name = "Sprint task board"
    target_dataset.save(update_fields=["name"])
    source_dataset.headers = ["task_dataset_url"]
    source_dataset.save(update_fields=["headers"])
    row = source_dataset.rows.first()
    raw_url = f"https://rowset.lvtd.dev/datasets/{target_dataset.key}/"
    row.data = {"task_dataset_url": raw_url}
    row.save(update_fields=["data"])
    row_url = reverse("dataset_row_detail", args=[source_dataset.key, row.id])

    response = auth_client.get(source_dataset.get_absolute_url())
    content = response.content.decode()

    assert response.status_code == 200
    assert f'href="{row_url}"' in content
    assert raw_url in content
    assert f'href="{target_dataset.get_absolute_url()}"' not in content
    assert 'aria-label="View row 1 details"' in content
    assert content.count('aria-label="View row 1 details"') == 1
    assert 'class="sr-only">View row 1 details' not in content


def test_dataset_detail_renders_unresolved_rowset_urls_as_text(
    auth_client,
    profile,
):
    dataset = create_ready_dataset(profile)
    missing_dataset_key = "4b7b8e47-15a5-4bd5-82cb-8c4f4fd40ce9"
    raw_url = f"https://rowset.lvtd.dev/datasets/{missing_dataset_key}/"
    row = dataset.rows.first()
    row.data["name"] = raw_url
    row.save(update_fields=["data"])

    response = auth_client.get(dataset.get_absolute_url())
    content = response.content.decode()

    assert response.status_code == 200
    assert raw_url in content
    assert f'href="{raw_url}"' not in content
    assert "Open Rowset URL" not in content
    assert "Rowset dataset" not in content


def test_dataset_detail_does_not_link_protocol_relative_rowset_urls(
    auth_client,
    profile,
):
    dataset = create_ready_dataset(profile)
    target_dataset = create_ready_dataset(profile)
    dataset.headers = ["name", "task_dataset_url"]
    dataset.save(update_fields=["headers"])
    row = dataset.rows.first()
    raw_url = f"//evil.example/datasets/{target_dataset.key}/"
    row.data = {
        "name": "Review Gate Sprint History",
        "task_dataset_url": raw_url,
    }
    row.save(update_fields=["data"])

    response = auth_client.get(dataset.get_absolute_url())
    content = response.content.decode()

    assert response.status_code == 200
    assert raw_url in content
    assert f'href="{raw_url}"' not in content
    assert f'href="{target_dataset.get_absolute_url()}"' not in content
    assert "Rowset dataset" not in content


def test_dataset_detail_falls_back_for_malformed_rowset_row_urls(
    auth_client,
    profile,
):
    dataset = create_ready_dataset(profile)
    target_dataset = create_ready_dataset(profile)
    raw_url = f"https://rowset.lvtd.dev/datasets/{target_dataset.key}/rows/not-a-row/"
    row = dataset.rows.first()
    row.data["name"] = raw_url
    row.save(update_fields=["data"])

    response = auth_client.get(dataset.get_absolute_url())
    content = response.content.decode()

    assert response.status_code == 200
    assert raw_url in content
    assert f'href="{raw_url}"' not in content
    assert f'href="{target_dataset.get_absolute_url()}"' not in content
    assert "Rowset row" not in content


def test_dataset_detail_ignores_invalid_ipv6_rowset_url_candidates(
    auth_client,
    profile,
):
    dataset = create_ready_dataset(profile)
    raw_url = "https://[rowset.lvtd.dev/datasets/5f250d73-2a70-414e-826e-271e28837f28/"
    row = dataset.rows.first()
    row.data["name"] = raw_url
    row.save(update_fields=["data"])

    response = auth_client.get(dataset.get_absolute_url())
    content = response.content.decode()

    assert response.status_code == 200
    assert raw_url in content
    assert f'href="{raw_url}"' not in content
    assert "Rowset dataset" not in content


def test_dataset_detail_ignores_json_array_rowset_url_candidates(
    auth_client,
    profile,
):
    dataset = create_ready_dataset(profile)
    dataset.headers = ["report_id", "result", "checks_passed", "changed_files", "artifact_url"]
    dataset.column_schema = {
        "report_id": {"type": DatasetColumnType.TEXT},
        "result": {
            "type": DatasetColumnType.CHOICE,
            "choices": ["dry_run", "pending", "pass", "fail", "blocked"],
        },
        "checks_passed": {"type": DatasetColumnType.TEXT},
        "changed_files": {"type": DatasetColumnType.TEXT},
        "artifact_url": {"type": DatasetColumnType.URL},
    }
    dataset.index_column = "report_id"
    dataset.save(update_fields=["headers", "column_schema", "index_column"])
    row = dataset.rows.first()
    row.index_value = "sample-dry-run-report-001"
    row.data = {
        "report_id": "sample-dry-run-report-001",
        "result": "dry_run",
        "checks_passed": "[]",
        "changed_files": '["TODO: record changed files after the run"]',
        "artifact_url": "",
    }
    row.save(update_fields=["index_value", "data"])

    response = auth_client.get(dataset.get_absolute_url())
    content = response.content.decode()

    assert response.status_code == 200
    assert "sample-dry-run-report-001" in content
    assert "[]" in content
    assert "TODO: record changed files after the run" in content
    assert 'href="https://[]"' not in content
    assert "Rowset dataset" not in content


def test_dataset_detail_falls_back_for_unsupported_rowset_row_subpaths(
    auth_client,
    profile,
):
    dataset = create_ready_dataset(profile)
    target_dataset = create_ready_dataset(profile)
    target_row = target_dataset.rows.first()
    raw_url = f"https://rowset.lvtd.dev/datasets/{target_dataset.key}/rows/{target_row.id}/edit/"
    row = dataset.rows.first()
    row.data["name"] = raw_url
    row.save(update_fields=["data"])

    response = auth_client.get(dataset.get_absolute_url())
    content = response.content.decode()

    assert response.status_code == 200
    assert raw_url in content
    assert f'href="{raw_url}"' not in content
    assert f'href="{target_row.get_absolute_url()}"' not in content
    assert f'href="{target_dataset.get_absolute_url()}"' not in content
    assert "Rowset row" not in content


def test_dataset_detail_falls_back_for_stale_rowset_row_urls(
    auth_client,
    profile,
):
    dataset = create_ready_dataset(profile)
    target_dataset = create_ready_dataset(profile)
    raw_url = f"https://rowset.lvtd.dev/datasets/{target_dataset.key}/rows/999999/"
    row = dataset.rows.first()
    row.data["name"] = raw_url
    row.save(update_fields=["data"])

    response = auth_client.get(dataset.get_absolute_url())
    content = response.content.decode()

    assert response.status_code == 200
    assert raw_url in content
    assert f'href="{raw_url}"' not in content
    assert f'href="{target_dataset.get_absolute_url()}"' not in content
    assert "Rowset row" not in content


def test_dataset_detail_falls_back_for_root_relative_stale_rowset_row_urls(
    auth_client,
    profile,
):
    dataset = create_ready_dataset(profile)
    target_dataset = create_ready_dataset(profile)
    raw_url = f"/datasets/{target_dataset.key}/rows/999999/"
    row = dataset.rows.first()
    row.data["name"] = raw_url
    row.save(update_fields=["data"])

    response = auth_client.get(dataset.get_absolute_url())
    content = response.content.decode()

    assert response.status_code == 200
    assert raw_url in content
    assert f'href="{raw_url}"' not in content
    assert f'href="{target_dataset.get_absolute_url()}"' not in content
    assert "Rowset row" not in content


def test_dataset_detail_does_not_resolve_disabled_share_urls_to_private_links(
    auth_client,
    profile,
):
    dataset = create_ready_dataset(profile)
    target_dataset = create_ready_dataset(profile)
    target_dataset.name = "Private Sprint Tasks"
    target_dataset.public_enabled = False
    target_dataset.save(update_fields=["name", "public_enabled"])
    raw_url = f"https://rowset.lvtd.dev/share/datasets/{target_dataset.public_key}/"
    row = dataset.rows.first()
    row.data["name"] = raw_url
    row.save(update_fields=["data"])

    response = auth_client.get(dataset.get_absolute_url())
    content = response.content.decode()

    assert response.status_code == 200
    assert raw_url in content
    assert f'href="{raw_url}"' not in content
    assert target_dataset.get_absolute_url() not in content
    assert "Private Sprint Tasks" not in content
    assert "Open Rowset URL" not in content


def test_dataset_detail_paginates_imported_rows_without_public_preview(auth_client, profile):
    dataset = create_ready_dataset(profile)
    dataset.rows.all().delete()
    total_rows = DATASET_DETAIL_ROW_PAGE_SIZE + 1
    DatasetRow.objects.bulk_create(
        [
            DatasetRow(
                dataset=dataset,
                row_number=row_number,
                index_value=f"person-{row_number:03}",
                data={
                    "name": f"Detail row {row_number:03}",
                    "email": f"person-{row_number:03}@example.com",
                },
            )
            for row_number in range(1, total_rows + 1)
        ]
    )
    dataset.row_count = total_rows
    dataset.public_enabled = False
    dataset.save(update_fields=["row_count", "public_enabled"])

    response = auth_client.get(f"{dataset.get_absolute_url()}?view=compact")
    content = response.content.decode()

    assert response.status_code == 200
    assert "Public preview:" not in content
    assert f"Showing 1-{DATASET_DETAIL_ROW_PAGE_SIZE} of {total_rows} rows" in content
    assert "Page 1 of 2" in content
    assert 'href="?view=compact&amp;page=2"' in content
    assert "Detail row 001" in content
    assert f"Detail row {total_rows:03}" not in content

    page_two = auth_client.get(f"{dataset.get_absolute_url()}?view=compact&page=2")
    page_two_content = page_two.content.decode()
    assert page_two.status_code == 200
    assert "Page 2 of 2" in page_two_content
    assert f"Detail row {total_rows:03}" in page_two_content


def test_dataset_detail_filters_and_sorts_rows(auth_client, profile):
    dataset = configure_filterable_dataset(create_ready_dataset(profile))

    search_response = auth_client.get(dataset.get_absolute_url(), {"row_q": "grace"})
    search_content = search_response.content.decode()

    assert search_response.status_code == 200
    assert search_response.context["row_page_obj"].paginator.count == 1
    assert "Grace Hopper" in search_content
    assert "Ada Lovelace" not in search_content
    assert "Katherine Johnson" not in search_content
    assert 'value="grace"' in search_content

    filter_response = auth_client.get(
        dataset.get_absolute_url(),
        {"filter_2": "10", "filter_3": "true"},
    )
    filter_content = filter_response.content.decode()

    assert filter_response.status_code == 200
    assert filter_response.context["row_page_obj"].paginator.count == 2
    assert "Ada Lovelace" in filter_content
    assert "Katherine Johnson" in filter_content
    assert "Grace Hopper" not in filter_content
    assert ">Clear</a>" in filter_content
    assert "Column filters" not in filter_content

    sort_response = auth_client.get(
        dataset.get_absolute_url(),
        {"row_sort": "col_0", "row_dir": "desc"},
    )
    sort_content = sort_response.content.decode()

    assert sort_response.status_code == 200
    assert sort_content.index("Katherine Johnson") < sort_content.index("Grace Hopper")
    assert sort_content.index("Grace Hopper") < sort_content.index("Ada Lovelace")

    numeric_sort_response = auth_client.get(
        dataset.get_absolute_url(),
        {"row_sort": "col_2"},
    )
    numeric_sort_content = numeric_sort_response.content.decode()

    assert numeric_sort_response.status_code == 200
    assert numeric_sort_content.index("Grace Hopper") < numeric_sort_content.index("Ada Lovelace")
    assert numeric_sort_content.index("Ada Lovelace") < numeric_sort_content.index(
        "Katherine Johnson"
    )


def test_dataset_detail_filters_numeric_columns_with_above_and_below(auth_client, profile):
    dataset = configure_filterable_dataset(create_ready_dataset(profile))

    above_response = auth_client.get(
        dataset.get_absolute_url(),
        {"filter_2": "9", "filter_op_2": "above"},
    )
    above_content = above_response.content.decode()

    assert above_response.status_code == 200
    assert above_response.context["row_page_obj"].paginator.count == 2
    assert above_response.context["row_filter_fields"][2]["operator"] == "above"
    assert "Ada Lovelace" in above_content
    assert "Katherine Johnson" in above_content
    assert "Grace Hopper" not in above_content
    assert 'name="filter_op_2"' in above_content
    assert '<option value="above" selected>Above</option>' in above_content

    below_response = auth_client.get(
        dataset.get_absolute_url(),
        {"filter_2": "9", "filter_op_2": "below"},
    )
    below_content = below_response.content.decode()

    assert below_response.status_code == 200
    assert below_response.context["row_page_obj"].paginator.count == 1
    assert "Grace Hopper" in below_content
    assert "Ada Lovelace" not in below_content
    assert "Katherine Johnson" not in below_content


def test_dataset_detail_filters_datetime_columns_with_above_and_below(auth_client, profile):
    dataset = configure_datetime_dataset(create_ready_dataset(profile))
    add_invalid_datetime_row(dataset)

    above_response = auth_client.get(
        dataset.get_absolute_url(),
        {"filter_2": "2026-05-14T08:30", "filter_op_2": "above"},
    )
    above_content = above_response.content.decode()

    assert above_response.status_code == 200
    assert above_response.context["row_page_obj"].paginator.count == 2
    assert above_response.context["row_filter_fields"][2]["operator"] == "above"
    assert "UTC later" in above_content
    assert "Next day" in above_content
    assert "Offset early" not in above_content
    assert "Invalid date" not in above_content
    assert "Invalid time" not in above_content
    assert "Invalid year" not in above_content
    assert 'name="filter_op_2"' in above_content
    assert '<option value="above" selected>Above</option>' in above_content

    below_response = auth_client.get(
        dataset.get_absolute_url(),
        {"filter_2": "2026-05-14T08:30", "filter_op_2": "below"},
    )
    below_content = below_response.content.decode()

    assert below_response.status_code == 200
    assert below_response.context["row_page_obj"].paginator.count == 1
    assert "Offset early" in below_content
    assert "UTC later" not in below_content
    assert "Next day" not in below_content
    assert "Invalid date" not in below_content
    assert "Invalid time" not in below_content
    assert "Invalid year" not in below_content


def test_dataset_detail_filters_choice_columns_by_exact_choice(auth_client, profile):
    dataset = create_ready_dataset(profile)
    dataset.headers = ["task_id", "component", "priority"]
    dataset.column_schema = {
        "task_id": {"type": DatasetColumnType.TEXT},
        "component": {"type": DatasetColumnType.TEXT},
        "priority": {
            "type": DatasetColumnType.CHOICE,
            "choices": ["P1", "P10", "P2"],
        },
    }
    dataset.row_count = 3
    dataset.rows.all().delete()
    dataset.save(update_fields=["headers", "column_schema", "row_count"])
    DatasetRow.objects.bulk_create(
        [
            DatasetRow(
                dataset=dataset,
                row_number=1,
                index_value="TASK-1",
                data={"task_id": "TASK-1", "component": "API", "priority": "P1"},
            ),
            DatasetRow(
                dataset=dataset,
                row_number=2,
                index_value="TASK-2",
                data={"task_id": "TASK-2", "component": "UI", "priority": "P10"},
            ),
            DatasetRow(
                dataset=dataset,
                row_number=3,
                index_value="TASK-3",
                data={"task_id": "TASK-3", "component": "Docs", "priority": "P2"},
            ),
        ]
    )

    response = auth_client.get(dataset.get_absolute_url(), {"filter_2": "P1"})
    content = response.content.decode()

    assert response.status_code == 200
    assert response.context["row_page_obj"].paginator.count == 1
    assert response.context["row_filter_fields"][2]["is_choice"] is True
    assert response.context["row_filter_fields"][2]["operator"] == "is"
    assert '<option value="P1" selected>P1</option>' in content
    assert "TASK-1" in content
    assert "TASK-2" not in content
    assert "TASK-3" not in content


def test_dataset_detail_semantic_text_filters_accept_partial_values(auth_client, profile):
    dataset = create_ready_dataset(profile)
    dataset.headers = ["email", "website"]
    dataset.column_schema = {
        "email": {"type": DatasetColumnType.EMAIL},
        "website": {"type": DatasetColumnType.URL},
    }
    dataset.preview_rows = []
    dataset.rows.all().delete()
    dataset.save(update_fields=["headers", "column_schema", "preview_rows"])
    DatasetRow.objects.create(
        dataset=dataset,
        row_number=1,
        index_value="ada@example.com",
        data={"email": "ada@example.com", "website": "https://example.com/ada"},
    )

    response = auth_client.get(dataset.get_absolute_url())
    content = response.content.decode()

    assert response.status_code == 200
    assert "Column filters" not in content
    assert 'id="row-column-filter-0"' in content
    assert 'id="row-column-filter-1"' in content
    assert 'name="filter_0"' in content
    assert 'name="filter_1"' in content


def test_dataset_detail_renders_url_cells_as_text(auth_client, profile):
    dataset = create_ready_dataset(profile)
    dataset.headers = ["name", "website", "unsafe"]
    dataset.column_schema = {
        "name": {"type": DatasetColumnType.TEXT},
        "website": {"type": DatasetColumnType.URL},
        "unsafe": {"type": DatasetColumnType.TEXT},
    }
    dataset.save(update_fields=["headers", "column_schema"])
    row = dataset.rows.first()
    row.data = {
        "name": "Ada",
        "website": "https://example.com/ada?ref=rowset&ok=1",
        "unsafe": "javascript:alert(1)",
    }
    row.save(update_fields=["data"])

    response = auth_client.get(dataset.get_absolute_url())
    content = response.content.decode()

    assert response.status_code == 200
    assert "https://example.com/ada?ref=rowset&amp;ok=1" in content
    assert 'href="https://example.com/ada?ref=rowset&amp;ok=1"' not in content
    assert 'target="_blank" rel="nofollow ugc noopener noreferrer"' not in content
    assert "javascript:alert(1)" in content
    assert 'href="javascript:alert(1)"' not in content


def test_dataset_detail_keeps_row_detail_link_for_single_text_url_column(auth_client, profile):
    dataset = create_ready_dataset(profile)
    dataset.headers = ["website"]
    dataset.column_schema = {"website": {"type": DatasetColumnType.URL}}
    dataset.save(update_fields=["headers", "column_schema"])
    row = dataset.rows.first()
    row.data = {"website": "https://example.com/ada"}
    row.save(update_fields=["data"])
    row_url = reverse("dataset_row_detail", args=[dataset.key, row.id])

    response = auth_client.get(dataset.get_absolute_url())
    content = response.content.decode()

    assert response.status_code == 200
    assert "https://example.com/ada" in content
    assert 'href="https://example.com/ada"' not in content
    assert f'href="{row_url}"' in content
    assert 'aria-label="View row 1 details"' in content
    assert 'aria-label="Open external link for row 1"' not in content
    assert ">Open</a>" not in content


def test_dataset_detail_filtered_empty_state_does_not_show_preview_rows(auth_client, profile):
    dataset = configure_filterable_dataset(create_ready_dataset(profile))

    response = auth_client.get(dataset.get_absolute_url(), {"row_q": "missing"})
    content = response.content.decode()

    assert response.status_code == 200
    assert response.context["row_page_obj"].paginator.count == 0
    assert "No rows match these filters." in content
    assert "Ada" not in content


def test_dataset_detail_unknown_boolean_filter_returns_no_rows(auth_client, profile):
    dataset = configure_filterable_dataset(create_ready_dataset(profile))

    response = auth_client.get(dataset.get_absolute_url(), {"filter_3": "maybe"})
    content = response.content.decode()

    assert response.status_code == 200
    assert response.context["row_page_obj"].paginator.count == 0
    assert "No rows match these filters." in content
    assert "Ada Lovelace" not in content
    assert "Grace Hopper" not in content
    assert "Katherine Johnson" not in content


def test_dataset_detail_row_search_caps_wide_schema(auth_client, profile):
    dataset = create_ready_dataset(profile)
    headers = [f"field_{index:02d}" for index in range(25)]
    dataset.headers = headers
    dataset.column_schema = {header: {"type": DatasetColumnType.TEXT} for header in headers}
    dataset.row_count = 1
    dataset.preview_rows = []
    dataset.rows.all().delete()
    dataset.save(update_fields=["headers", "column_schema", "row_count", "preview_rows"])
    DatasetRow.objects.create(
        dataset=dataset,
        row_number=1,
        index_value="wide-row",
        data={
            **{header: "" for header in headers},
            "field_19": "Visible within cap",
            "field_20": "Hidden outside cap",
        },
    )

    within_cap_response = auth_client.get(dataset.get_absolute_url(), {"row_q": "visible"})
    within_cap_content = within_cap_response.content.decode()

    assert within_cap_response.status_code == 200
    assert within_cap_response.context["row_page_obj"].paginator.count == 1
    assert "Visible within cap" in within_cap_content

    outside_cap_response = auth_client.get(dataset.get_absolute_url(), {"row_q": "hidden"})
    outside_cap_content = outside_cap_response.content.decode()

    assert outside_cap_response.status_code == 200
    assert outside_cap_response.context["row_page_obj"].paginator.count == 0
    assert "No rows match these filters." in outside_cap_content
    assert "Hidden outside cap" not in outside_cap_content


def test_dataset_detail_row_search_empty_headers_returns_no_rows(auth_client, profile):
    dataset = create_ready_dataset(profile)
    dataset.headers = []
    dataset.column_schema = {}
    dataset.row_count = 1
    dataset.preview_rows = []
    dataset.rows.all().delete()
    dataset.save(update_fields=["headers", "column_schema", "row_count", "preview_rows"])
    DatasetRow.objects.create(
        dataset=dataset,
        row_number=1,
        index_value="empty-header-row",
        data={"stored_field": "Invisible to header search"},
    )

    response = auth_client.get(dataset.get_absolute_url(), {"row_q": "invisible"})
    content = response.content.decode()

    assert response.status_code == 200
    assert response.context["row_page_obj"].paginator.count == 0
    assert "No rows match these filters." in content
    assert "Invisible to header search" not in content


def test_dataset_row_detail_displays_full_row_data(auth_client, profile):
    dataset = create_ready_dataset(profile)
    dataset.headers = ["name", "email", "notes"]
    dataset.save(update_fields=["headers"])
    row = dataset.rows.first()
    full_value = "Line one\n" + "Full untruncated value " * 12
    row.data = {
        "name": "Ada",
        "email": "ada@example.com",
        "notes": full_value,
        "extra_field": "Stored outside declared headers",
    }
    row.save(update_fields=["data"])

    response = auth_client.get(reverse("dataset_row_detail", args=[dataset.key, row.id]))
    content = response.content.decode()

    assert response.status_code == 200
    assert "<title>People · ada@example.com · Rowset</title>" in content
    assert "Row 1" in content
    assert "notes" in content
    assert full_value in content
    assert "extra_field" in content
    assert "Stored outside declared headers" in content
    assert "Back to dataset" in content
    assert 'td class="min-w-96 whitespace-pre-wrap break-words"' not in content
    assert '<span class="whitespace-pre-wrap break-words">Ada</span>' in content
    assert 'x-data="rowInlineEdit"' in content
    assert 'aria-label="Edit name"' in content
    assert 'aria-label="Edit email"' in content
    email_input_index = content.index('name="email"')
    email_input_snippet = content[email_input_index : email_input_index + 420]
    assert "required" in email_input_snippet
    assert "Save row" in content


def test_dataset_row_detail_hides_edit_controls_for_archived_dataset(auth_client, profile):
    dataset = create_ready_dataset(profile)
    dataset.archived_at = timezone.now()
    dataset.save(update_fields=["archived_at"])
    row = dataset.rows.get(row_number=1)

    response = auth_client.get(reverse("dataset_row_detail", args=[dataset.key, row.id]))
    content = response.content.decode()

    assert response.status_code == 200
    assert "Ada" in content
    assert "Edit individual values without leaving the row." not in content
    assert 'x-data="rowInlineEdit"' not in content
    assert 'aria-label="Edit name"' not in content
    assert "Save row" not in content


def test_dataset_row_create_view_creates_row(auth_client, profile):
    dataset = create_ready_dataset(profile)

    response = auth_client.post(
        reverse("dataset_row_create", args=[dataset.key]),
        data={"name": "Katherine", "email": "kat@example.com"},
    )

    assert response.status_code == 302
    row = dataset.rows.get(index_value="kat@example.com")
    assert response.url == row.get_absolute_url()
    dataset.refresh_from_db()
    assert dataset.row_count == 3
    assert row.data == {"name": "Katherine", "email": "kat@example.com"}
    assert dataset.mutations.filter(mutation_type=DatasetMutationType.ROW_CREATED).exists()


def test_dataset_row_create_view_renders_schema_specific_inputs(auth_client, profile):
    dataset = create_typed_row_dataset(profile)

    response = auth_client.get(reverse("dataset_row_create", args=[dataset.key]))
    content = response.content.decode()

    assert response.status_code == 200
    assert "<title>New row · Typed rows · Rowset</title>" in content
    fields = {field["header"]: field for field in response.context["row_form_fields"]}
    assert fields["row_id"]["input_type"] == "text"
    assert fields["row_id"]["is_textarea"] is False
    assert fields["status"]["is_choice"] is True
    assert [choice["value"] for choice in fields["status"]["choices"]] == [
        "Backlog",
        "Doing",
        "Done",
    ]
    assert fields["active"]["is_boolean"] is True
    assert fields["due_on"]["input_type"] == "date"
    assert fields["scheduled_at"]["input_type"] == "datetime-local"
    assert fields["count"]["input_type"] == "number"
    assert fields["count"]["input_step"] == "1"
    assert fields["count"]["input_mode"] == "numeric"
    assert fields["score"]["input_step"] == "any"
    assert fields["budget"]["input_step"] == "any"
    assert fields["contact"]["input_type"] == "email"
    assert fields["website"]["input_type"] == "url"
    assert fields["related_dataset"]["input_type"] == "text"
    assert fields["notes"]["is_textarea"] is True
    assert fields["photo"]["is_image"] is True
    assert 'name="status"' in content
    assert 'value="Doing"' in content
    assert 'name="active"' in content
    assert 'value="false"' in content
    assert 'name="due_on"' in content
    assert 'type="date"' in content
    assert 'name="scheduled_at"' in content
    assert 'type="datetime-local"' in content
    assert 'name="count"' in content
    assert 'step="1"' in content
    assert 'name="score"' in content
    assert 'step="any"' in content
    assert 'name="contact"' in content
    assert 'type="email"' in content
    assert 'name="website"' in content
    assert 'type="url"' in content
    assert "Image assets can be attached after the row is created." in content


def test_dataset_row_create_view_creates_row_from_schema_specific_inputs(
    auth_client,
    profile,
):
    dataset = create_typed_row_dataset(profile)

    response = auth_client.post(
        reverse("dataset_row_create", args=[dataset.key]),
        data=typed_row_post_data(
            row_id="ROW-2",
            status="Doing",
            active="false",
            count="3",
            score="9.75",
            budget="250.50",
            contact="grace@example.com",
            website="https://example.com/grace",
            notes="Follow up\nSend recap",
        ),
    )

    row = dataset.rows.get(index_value="ROW-2")
    assert response.status_code == 302
    assert response.url == row.get_absolute_url()
    assert row.data == {
        "row_id": "ROW-2",
        "status": "Doing",
        "active": "false",
        "due_on": "2026-07-01",
        "scheduled_at": "2026-07-01T09:30",
        "count": "3",
        "score": "9.75",
        "budget": "250.50",
        "contact": "grace@example.com",
        "website": "https://example.com/grace",
        "related_dataset": "",
        "notes": "Follow up\nSend recap",
        "photo": "",
    }


def test_dataset_row_create_view_rerenders_schema_specific_values_on_error(
    auth_client,
    profile,
):
    dataset = create_typed_row_dataset(profile)

    response = auth_client.post(
        reverse("dataset_row_create", args=[dataset.key]),
        data=typed_row_post_data(
            status="Doing",
            active="false",
            count="3",
            score="9.75",
            budget="250.50",
            contact="grace@example.com",
            website="https://example.com/grace",
            notes="Follow up",
        ),
    )
    content = response.content.decode()

    assert response.status_code == 200
    assert "Row with index" in content
    assert '<option value="Doing" selected>Doing</option>' in content
    assert '<option value="false" selected>False</option>' in content
    assert 'value="2026-07-01"' in content
    assert 'value="2026-07-01T09:30"' in content
    assert 'value="9.75"' in content
    assert "Follow up</textarea>" in content
    assert dataset.rows.count() == 1


def test_dataset_row_create_view_rerenders_service_errors(auth_client, profile):
    dataset = create_ready_dataset(profile)

    response = auth_client.post(
        reverse("dataset_row_create", args=[dataset.key]),
        data={"name": "Duplicate Ada", "email": "ada@example.com"},
    )
    content = response.content.decode()

    assert response.status_code == 200
    assert "Row with index" in content
    assert "Duplicate Ada" in content
    assert dataset.rows.count() == 2


def test_dataset_row_create_view_uses_generated_index(auth_client, profile):
    dataset = Dataset.objects.create(
        profile=profile,
        name="Tasks",
        original_filename="Created via API",
        file_type="api",
        status=DatasetStatus.READY,
        headers=["rowset_id", "task"],
        index_column="rowset_id",
        index_generated=True,
        row_count=0,
    )

    response = auth_client.post(
        reverse("dataset_row_create", args=[dataset.key]),
        data={"task": "Ship UI CRUD"},
    )

    row = dataset.rows.get()
    dataset.refresh_from_db()
    assert response.status_code == 302
    assert response.url == row.get_absolute_url()
    assert row.index_value == "1"
    assert row.data == {"rowset_id": "1", "task": "Ship UI CRUD"}
    assert dataset.row_count == 1


def test_dataset_row_detail_updates_opened_fields(auth_client, profile):
    dataset = create_ready_dataset(profile)
    row = dataset.rows.get(row_number=1)

    response = auth_client.post(
        reverse("dataset_row_detail", args=[dataset.key, row.id]),
        data={"name": "Ada Lovelace"},
    )

    assert response.status_code == 302
    row.refresh_from_db()
    assert row.data == {"name": "Ada Lovelace", "email": "ada@example.com"}
    mutation = dataset.mutations.get(mutation_type=DatasetMutationType.ROW_UPDATED)
    assert mutation.metadata["changed_fields"] == ["name"]


def test_dataset_row_detail_rerenders_update_errors(auth_client, profile):
    dataset = create_ready_dataset(profile)
    row = dataset.rows.get(row_number=1)

    response = auth_client.post(
        reverse("dataset_row_detail", args=[dataset.key, row.id]),
        data={"email": "grace@example.com"},
    )
    content = response.content.decode()

    assert response.status_code == 200
    assert "Row with index" in content
    assert "grace@example.com" in content
    row.refresh_from_db()
    assert row.index_value == "ada@example.com"


def test_dataset_rows_bulk_action_deletes_selected_rows(auth_client, profile):
    dataset = create_ready_dataset(profile)
    selected_rows = list(dataset.rows.order_by("row_number"))

    response = auth_client.post(
        reverse("dataset_rows_bulk_action", args=[dataset.key]),
        data={
            "bulk_action": "delete",
            "row_id": [selected_rows[0].id, selected_rows[1].id],
        },
    )

    assert response.status_code == 302
    assert response.url == dataset.get_absolute_url()
    assert not DatasetRow.objects.filter(id__in=[row.id for row in selected_rows]).exists()
    dataset.refresh_from_db()
    assert dataset.row_count == 0
    assert dataset.mutations.filter(mutation_type=DatasetMutationType.ROW_DELETED).count() == 2


def test_dataset_rows_bulk_action_requires_selection(auth_client, profile):
    dataset = create_ready_dataset(profile)

    response = auth_client.post(
        reverse("dataset_rows_bulk_action", args=[dataset.key]),
        data={"bulk_action": "delete"},
    )

    assert response.status_code == 302
    assert dataset.rows.count() == 2


def test_dataset_row_detail_updates_row_fields_inline(auth_client, profile):
    dataset = create_ready_dataset(profile)
    row = dataset.rows.get(row_number=1)

    response = auth_client.post(
        reverse("dataset_row_detail", args=[dataset.key, row.id]),
        data={
            "name": "Ada Lovelace",
            "email": "ada+ui@example.com",
        },
    )

    row.refresh_from_db()
    assert response.status_code == 302
    assert response.url == row.get_absolute_url()
    assert row.index_value == "ada+ui@example.com"
    assert row.data == {
        "name": "Ada Lovelace",
        "email": "ada+ui@example.com",
    }
    assert dataset.mutations.filter(
        mutation_type=DatasetMutationType.ROW_UPDATED,
        target_identifier=row.id,
    ).exists()


def test_dataset_row_detail_rejects_other_users_inline_update(
    client,
    django_user_model,
    profile,
):
    dataset = create_ready_dataset(profile)
    row = dataset.rows.get(row_number=1)
    other_user = django_user_model.objects.create_user(
        username="other-row-editor",
        email="other-row-editor@example.com",
        password="password123",
    )
    client.force_login(other_user)

    response = client.post(
        reverse("dataset_row_detail", args=[dataset.key, row.id]),
        data={
            "name": "Edited elsewhere",
            "email": "edited@example.com",
        },
    )

    row.refresh_from_db()
    assert response.status_code == 404
    assert row.data["name"] == "Ada"
    assert row.index_value == "ada@example.com"


def test_dataset_row_detail_renders_url_cells_as_text(auth_client, profile):
    dataset = create_ready_dataset(profile)
    dataset.headers = ["name", "website", "unsafe"]
    dataset.save(update_fields=["headers"])
    row = dataset.rows.first()
    row.data = {
        "name": "Ada",
        "website": "https://example.com/ada",
        "unsafe": "https://example.com/<script>",
    }
    row.save(update_fields=["data"])

    response = auth_client.get(reverse("dataset_row_detail", args=[dataset.key, row.id]))
    content = response.content.decode()

    assert response.status_code == 200
    assert "https://example.com/ada" in content
    assert 'href="https://example.com/ada"' not in content
    assert 'target="_blank" rel="nofollow ugc noopener noreferrer"' not in content
    assert "https://example.com/&lt;script&gt;" in content
    assert 'href="https://example.com/&lt;script&gt;"' not in content


def test_dataset_row_detail_links_relationship_value_to_target_row(auth_client, profile):
    people, messages = create_crm_datasets(profile)
    relationship = DatasetRelationship.objects.create(
        profile=profile,
        source_dataset=messages,
        target_dataset=people,
        name="Message person",
        source_column="person_id",
        target_index_column="person_id",
        enforce_integrity=True,
    )
    message_row = messages.rows.get(index_value="M-1")
    person_row = people.rows.get(index_value="P-1")

    response = auth_client.get(reverse("dataset_row_detail", args=[messages.key, message_row.id]))
    content = response.content.decode()

    assert response.status_code == 200
    target_url = reverse("dataset_row_detail", args=[people.key, person_row.id])
    assert f'href="{target_url}"' in content
    assert f"View related People row 1 via {relationship.name}" in content
    assert re.search(r"<a[^>]+>\s*P-1\s*</a>", content) is not None


def test_dataset_row_detail_renders_rowset_row_urls_as_text(
    auth_client,
    profile,
):
    source_dataset = create_ready_dataset(profile)
    target_dataset = create_ready_dataset(profile)
    target_dataset.name = "Sprint task board"
    target_dataset.save(update_fields=["name"])
    target_row = target_dataset.rows.first()
    source_row = source_dataset.rows.first()
    raw_url = f"https://rowset.lvtd.dev/datasets/{target_dataset.key}/rows/{target_row.id}/"
    source_row.data["name"] = raw_url
    source_row.save(update_fields=["data"])

    response = auth_client.get(
        reverse("dataset_row_detail", args=[source_dataset.key, source_row.id])
    )
    content = response.content.decode()

    assert response.status_code == 200
    assert raw_url in content
    assert f'href="{target_row.get_absolute_url()}"' not in content
    assert "Sprint task board row 1" not in content


def test_dataset_row_detail_leaves_unresolved_relationship_value_unlinked(auth_client, profile):
    people, messages = create_crm_datasets(profile)
    DatasetRelationship.objects.create(
        profile=profile,
        source_dataset=messages,
        target_dataset=people,
        name="Optional message person",
        source_column="person_id",
        target_index_column="person_id",
        enforce_integrity=False,
    )
    message_row = messages.rows.get(index_value="M-1")
    message_row.data["person_id"] = "P-missing"
    message_row.save(update_fields=["data"])

    response = auth_client.get(reverse("dataset_row_detail", args=[messages.key, message_row.id]))
    content = response.content.decode()

    assert response.status_code == 200
    assert "P-missing" in content
    assert "View related People" not in content
    assert not re.search(r"<a[^>]+>\s*P-missing\s*</a>", content)


def test_dataset_row_detail_rejects_other_users_row(client, django_user_model, profile):
    dataset = create_ready_dataset(profile)
    row = dataset.rows.first()
    other_user = django_user_model.objects.create_user(
        username="other-row-viewer",
        email="other-row-viewer@example.com",
        password="password123",
    )
    client.force_login(other_user)

    response = client.get(reverse("dataset_row_detail", args=[dataset.key, row.id]))

    assert response.status_code == 404


def test_dataset_changes_rejects_other_users_dataset(client, django_user_model, profile):
    dataset = create_ready_dataset(profile)
    other_user = django_user_model.objects.create_user(
        username="other-changes-viewer",
        email="other-changes-viewer@example.com",
        password="password123",
    )
    client.force_login(other_user)

    response = client.get(dataset.get_changes_url())

    assert response.status_code == 404


def test_dataset_changes_paginates_mutation_history(auth_client, profile):
    dataset = create_ready_dataset(profile)
    total_changes = DATASET_CHANGES_PAGE_SIZE + 1
    for number in range(1, total_changes + 1):
        record_dataset_mutation(
            dataset,
            DatasetMutationType.ROW_UPDATED,
            f"Change {number:03}",
        )

    response = auth_client.get(dataset.get_changes_url())
    content = response.content.decode()

    assert response.status_code == 200
    assert "<title>People changes · Rowset</title>" in content
    assert f"Showing 1-{DATASET_CHANGES_PAGE_SIZE} of {total_changes} recorded changes." in content
    assert "Page 1 of 2" in content
    assert 'href="?page=2"' in content
    assert f"Change {total_changes:03}" in content
    assert "Change 001" not in content

    page_two = auth_client.get(f"{dataset.get_changes_url()}?page=2")
    page_two_content = page_two.content.decode()
    assert page_two.status_code == 200
    page_two_summary = (
        f"Showing {total_changes}-{total_changes} of {total_changes} recorded changes."
    )
    assert page_two_summary in page_two_content
    assert "Page 2 of 2" in page_two_content
    assert "Change 001" in page_two_content
    assert f"Change {total_changes:03}" not in page_two_content


def test_dataset_changes_field_details_are_collapsed_by_default(auth_client, profile):
    dataset = create_ready_dataset(profile)
    row = dataset.rows.get(row_number=1)
    mutation = record_dataset_mutation(
        dataset,
        DatasetMutationType.ROW_UPDATED,
        "Row 1 updated.",
        target_type="row",
        target_identifier=row.id,
        metadata={
            "row_id": row.id,
            "row_number": row.row_number,
            "changed_fields": ["email"],
            "field_changes": [
                {
                    "field": "email",
                    "before": "ada@example.com",
                    "after": "ada+updated@example.com",
                }
            ],
            "value_changes_recorded": True,
            "index_changed": True,
        },
    )

    response = auth_client.get(dataset.get_changes_url())
    content = response.content.decode()

    assert response.status_code == 200
    details_match = re.search(
        rf'<details\b[^>]*aria-labelledby="dataset-change-{mutation.id}-summary"[^>]*>',
        content,
    )
    assert details_match is not None
    assert not re.search(r"\sopen(?:[\s=>]|$)", details_match.group(0))
    assert f'id="dataset-change-{mutation.id}-summary"' in content
    assert "Full view" in content
    assert "Collapse" in content
    assert "ada@example.com" in content
    assert "ada+updated@example.com" in content


def test_dataset_detail_uses_export_menu_and_hides_duplicate_schema(auth_client, profile):
    dataset = create_ready_dataset(profile)

    response = auth_client.get(dataset.get_absolute_url())

    content = response.content.decode()
    assert response.status_code == 200
    assert 'id="dataset-rows-heading"' in content
    assert ">Rows</h2>" in content
    assert 'id="schema-heading"' not in content
    assert "Dataset API" not in content
    assert "Export CSV" not in content
    assert "Export Parquet" not in content
    assert "@click.outside" in content
    assert "CSV snapshot" in content
    assert "JSONL snapshot" in content
    assert "XLSX snapshot" in content
    assert "SQLite snapshot" in content
    assert "Parquet snapshot" in content
    assert 'aria-label="Dataset status: Ready"' not in content


def test_dataset_detail_context_is_collapsed_by_default_and_wraps_content(auth_client, profile):
    dataset = create_ready_dataset(profile)
    dataset.description = "A" * 180
    dataset.instructions = "Keep " + ("agent-instruction-token" * 12)
    dataset.metadata = {"long_key": "metadata-value-token" * 12}
    dataset.save(update_fields=["description", "instructions", "metadata"])

    response = auth_client.get(dataset.get_absolute_url())

    content = response.content.decode()
    assert response.status_code == 200
    details_match = re.search(
        r'<details\b[^>]*aria-labelledby="dataset-context-heading"[^>]*>',
        content,
    )
    assert details_match is not None
    details_tag = details_match.group(0)
    assert not re.search(r"\sopen(?:[\s=>]|$)", details_tag)
    assert "fb-card" in details_tag
    assert "overflow-hidden" in details_tag
    assert "Show context" in content
    assert "Hide context" in content
    for class_name in ("max-w-full", "whitespace-pre-wrap", "break-words"):
        assert class_name in content
    for class_name in ("max-h-72", "overflow-auto"):
        assert class_name in content


def test_dataset_detail_shows_archive_action_for_active_dataset(auth_client, profile):
    dataset = create_ready_dataset(profile)

    response = auth_client.get(dataset.get_absolute_url())
    content = response.content.decode()

    assert response.status_code == 200
    assert reverse("dataset_archive", args=[dataset.key]) in content
    assert "Archive" in content
    assert "Dataset archived" not in content


def test_dataset_detail_hides_archive_action_for_non_ready_dataset(auth_client, profile):
    dataset = Dataset.objects.create(
        profile=profile,
        name="Processing import",
        original_filename="processing.csv",
        source_text="name\nAda\n",
        status=DatasetStatus.PROCESSING,
        headers=["name"],
        preview_rows=[{"name": "Ada"}],
        row_count=0,
    )

    response = auth_client.get(dataset.get_absolute_url())
    content = response.content.decode()

    assert response.status_code == 200
    assert reverse("dataset_archive", args=[dataset.key]) not in content
    assert "Archive" not in content


def test_dataset_detail_shows_archived_badge_without_archive_action(auth_client, profile):
    dataset = create_ready_dataset(profile)
    dataset.archived_at = timezone.now()
    dataset.save(update_fields=["archived_at"])

    response = auth_client.get(dataset.get_absolute_url())
    content = response.content.decode()

    assert response.status_code == 200
    assert 'aria-label="Dataset archived"' in content
    assert reverse("dataset_archive", args=[dataset.key]) not in content


def test_dataset_detail_exposes_processing_status_live_region(auth_client, profile):
    dataset = Dataset.objects.create(
        profile=profile,
        name="Processing import",
        original_filename="processing.csv",
        source_text="name\nAda\n",
        status=DatasetStatus.PROCESSING,
        headers=["name"],
        preview_rows=[{"name": "Ada"}],
        row_count=0,
    )

    response = auth_client.get(dataset.get_absolute_url())
    content = response.content.decode()

    assert response.status_code == 200
    assert 'aria-label="Dataset status: Processing"' in content
    assert ">Processing</span>" in content
    assert 'id="dataset-status-panel"' in content
    assert 'hx-get="' in content
    assert 'hx-trigger="every 2.5s"' in content
    assert 'role="status"' in content
    assert 'aria-live="polite"' in content
    assert "Still importing rows" in content


def test_dataset_detail_failed_status_has_accessible_fallback_message(auth_client, profile):
    dataset = Dataset.objects.create(
        profile=profile,
        name="Failed import",
        original_filename="failed.csv",
        source_text="name\nAda\n",
        status=DatasetStatus.FAILED,
        headers=["name"],
        preview_rows=[{"name": "Ada"}],
        row_count=0,
    )

    response = auth_client.get(dataset.get_absolute_url())
    content = response.content.decode()

    assert response.status_code == 200
    assert 'aria-label="Dataset status: Failed"' in content
    assert ">Failed</span>" in content
    assert 'role="alert"' in content
    assert 'aria-live="assertive"' in content
    assert "Import failed. Check the source data and try again." in content


def test_dataset_status_htmx_renders_processing_partial(auth_client, profile):
    dataset = Dataset.objects.create(
        profile=profile,
        name="Processing import",
        original_filename="processing.csv",
        source_text="name\nAda\n",
        status=DatasetStatus.PROCESSING,
        headers=["name"],
        preview_rows=[{"name": "Ada"}],
        row_count=0,
    )

    response = auth_client.get(
        reverse("dataset_status", args=[dataset.key]),
        HTTP_HX_REQUEST="true",
    )
    content = response.content.decode()

    assert response.status_code == 200
    assert 'id="dataset-status-panel"' in content
    assert 'hx-trigger="every 2.5s"' in content
    assert "<html" not in content.lower()
    assert "Still importing rows" in content


def test_dataset_status_htmx_refreshes_when_ready(auth_client, profile):
    dataset = create_ready_dataset(profile)

    response = auth_client.get(
        reverse("dataset_status", args=[dataset.key]),
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    assert response.headers["HX-Refresh"] == "true"


def test_project_detail_dataset_rows_omit_status_and_actions(auth_client, profile):
    project = Project.objects.create(profile=profile, name="Launch")
    dataset = create_ready_dataset(profile)
    dataset.project = project
    dataset.save(update_fields=["project"])

    response = auth_client.get(project.get_absolute_url())

    content = response.content.decode()
    assert response.status_code == 200
    assert "Datasets by section" in content
    assert "People" in content
    assert reverse("dataset_export", args=[dataset.key, "csv"]) not in content
    assert reverse("dataset_export", args=[dataset.key, "parquet"]) not in content
    assert dataset.get_settings_url() not in content
    assert "Dataset status" not in content


def test_project_detail_links_to_settings_and_hides_project_edit_actions(auth_client, profile):
    project = Project.objects.create(
        profile=profile,
        name="Frontier",
        description="Canonical Rowset project for Frontier.",
    )

    response = auth_client.get(project.get_absolute_url())
    content = response.content.decode()

    assert response.status_code == 200
    assert "<title>Frontier · Rowset</title>" in content
    assert "Project details" not in content
    assert ">Frontier</h1>" in content
    assert "Project context" in content
    assert "Canonical Rowset project for Frontier." in content
    assert project.get_settings_url() in content
    assert "View all datasets" in content
    assert 'x-data="projectDetail"' not in content
    assert reverse("project_update", args=[project.key]) not in content
    assert reverse("project_update_metadata", args=[project.key]) not in content
    assert reverse("project_delete", args=[project.key]) not in content


def test_project_context_and_archived_datasets_are_collapsed_on_detail(auth_client, profile):
    project = Project.objects.create(
        profile=profile,
        name="Frontier",
        description="Canonical Rowset project for Frontier.",
        metadata={"owner": "ops"},
    )

    response = auth_client.get(project.get_absolute_url())
    content = response.content.decode()

    assert response.status_code == 200
    assert "<details open" not in content
    assert "Project context" in content
    assert "Archived datasets" in content
    assert response.context["metadata_json"] == '{\n  "owner": "ops"\n}'


def test_project_settings_shows_project_forms_sections_and_delete_warning(auth_client, profile):
    project = Project.objects.create(
        profile=profile,
        name="Frontier",
        description="Canonical Rowset project for Frontier.",
        metadata={"github_repo": "https://github.com/acme/frontier"},
    )
    section = dataset_models.ProjectSection.objects.create(
        profile=profile,
        project=project,
        name="Blog",
        description="Editorial datasets",
    )

    response = auth_client.get(project.get_settings_url())
    content = response.content.decode()

    assert response.status_code == 200
    assert "Project settings" in content
    assert 'aria-labelledby="project-settings-nav-heading"' in content
    assert reverse("project_update", args=[project.key]) in content
    assert reverse("project_update_metadata", args=[project.key]) in content
    assert reverse("project_section_create", args=[project.key]) in content
    assert reverse("project_section_delete", args=[project.key, section.key]) in content
    assert reverse("project_delete", args=[project.key]) in content
    assert "Warning" in content
    assert (
        "return confirm('Delete project Frontier? Assigned datasets will stay in Rowset "
        "and become ungrouped. This cannot be undone.');"
    ) in content
    assert "Canonical Rowset project for Frontier." in content
    assert "https://github.com/acme/frontier" in content
    assert "Blog" in content


def test_home_omits_standalone_project_management(auth_client, profile):
    project = Project.objects.create(profile=profile, name="Frontier")
    dataset = create_ready_dataset(profile)
    dataset.project = project
    dataset.save(update_fields=["project"])

    response = auth_client.get(reverse("home"))
    content = response.content.decode()

    assert response.status_code == 200
    assert "Frontier" in content
    assert "projects-overview" not in content
    assert "New project" not in content
    assert reverse("project_delete", args=[project.key]) not in content


def test_project_delete_removes_owned_project_and_detaches_datasets(auth_client, profile):
    project = Project.objects.create(profile=profile, name="Launch")
    dataset = create_ready_dataset(profile)
    dataset.project = project
    dataset.save(update_fields=["project"])

    response = auth_client.post(reverse("project_delete", args=[project.key]))

    assert response.status_code == 302
    assert response.url == reverse("home")
    assert not Project.objects.filter(id=project.id).exists()
    dataset.refresh_from_db()
    assert dataset.project is None
    flash_messages = list(get_messages(response.wsgi_request))
    assert len(flash_messages) == 1
    assert flash_messages[0].level == message_constants.SUCCESS
    assert str(flash_messages[0]) == "Deleted Launch. Assigned datasets are now ungrouped."


def test_project_delete_requires_post(auth_client, profile):
    project = Project.objects.create(profile=profile, name="Launch")

    response = auth_client.get(reverse("project_delete", args=[project.key]))

    assert response.status_code == 405
    assert Project.objects.filter(id=project.id).exists()


def test_project_delete_rejects_other_users_project(client, django_user_model, profile):
    project = Project.objects.create(profile=profile, name="Launch")
    other_user = django_user_model.objects.create_user(
        username="other-project-delete",
        email="other-project-delete@example.com",
        password="password123",
    )
    client.force_login(other_user)

    response = client.post(reverse("project_delete", args=[project.key]))

    assert response.status_code == 404
    assert Project.objects.filter(id=project.id).exists()


def test_project_delete_rejects_user_without_profile(client, django_user_model, profile):
    project = Project.objects.create(profile=profile, name="Launch")
    user_without_profile = django_user_model.objects.create_user(
        username="missing-profile-project-delete",
        email="missing-profile-project-delete@example.com",
        password="password123",
    )
    user_without_profile.profile.delete()
    client.force_login(user_without_profile)

    response = client.post(reverse("project_delete", args=[project.key]))

    assert response.status_code == 404
    assert Project.objects.filter(id=project.id).exists()


def test_dataset_archive_archives_owned_dataset(auth_client, profile):
    dataset = create_ready_dataset(profile)
    dataset.public_enabled = True
    dataset.save(update_fields=["public_enabled"])

    response = auth_client.post(reverse("dataset_archive", args=[dataset.key]))

    assert response.status_code == 302
    assert response.url == reverse("home")
    dataset.refresh_from_db()
    assert dataset.archived_at is not None
    assert dataset.public_enabled is False


def test_dataset_archive_rejects_non_ready_dataset(auth_client, profile):
    dataset = Dataset.objects.create(
        profile=profile,
        name="Processing import",
        original_filename="processing.csv",
        source_text="name\nAda\n",
        status=DatasetStatus.PROCESSING,
        headers=["name"],
        preview_rows=[{"name": "Ada"}],
        row_count=0,
    )

    response = auth_client.post(reverse("dataset_archive", args=[dataset.key]))

    assert response.status_code == 302
    assert response.url == dataset.get_absolute_url()
    dataset.refresh_from_db()
    assert dataset.archived_at is None
    flash_messages = list(get_messages(response.wsgi_request))
    assert len(flash_messages) == 1
    assert flash_messages[0].level == message_constants.ERROR
    assert str(flash_messages[0]) == "Only ready datasets can be archived from the dataset page."


def test_dataset_archive_requires_post(auth_client, profile):
    dataset = create_ready_dataset(profile)

    response = auth_client.get(reverse("dataset_archive", args=[dataset.key]))

    assert response.status_code == 405


def test_dataset_archive_uses_info_message_for_already_archived_dataset(auth_client, profile):
    dataset = create_ready_dataset(profile)
    dataset.archived_at = timezone.now()
    dataset.save(update_fields=["archived_at"])

    response = auth_client.post(reverse("dataset_archive", args=[dataset.key]))

    assert response.status_code == 302
    assert response.url == reverse("home")
    flash_messages = list(get_messages(response.wsgi_request))
    assert len(flash_messages) == 1
    assert flash_messages[0].level == message_constants.INFO
    assert str(flash_messages[0]) == "Dataset was already archived."


def test_dataset_archive_rejects_other_users_dataset(client, django_user_model, profile):
    dataset = create_ready_dataset(profile)
    other_user = django_user_model.objects.create_user(
        username="other-archive",
        email="other-archive@example.com",
        password="password123",
    )
    client.force_login(other_user)

    response = client.post(reverse("dataset_archive", args=[dataset.key]))

    assert response.status_code == 404
    dataset.refresh_from_db()
    assert dataset.archived_at is None


def test_dataset_delete_removes_owned_dataset(auth_client, profile):
    dataset = create_ready_dataset(profile)

    response = auth_client.post(reverse("dataset_delete", args=[dataset.key]))

    assert response.status_code == 302
    assert not Dataset.objects.filter(id=dataset.id).exists()
    assert not DatasetRow.objects.filter(dataset_id=dataset.id).exists()


def test_dataset_delete_rejects_other_users_dataset(client, django_user_model, profile):
    dataset = create_ready_dataset(profile)
    other_user = django_user_model.objects.create_user(
        username="other-delete",
        email="other-delete@example.com",
        password="password123",
    )
    client.force_login(other_user)

    response = client.post(reverse("dataset_delete", args=[dataset.key]))

    assert response.status_code == 404
    assert Dataset.objects.filter(id=dataset.id).exists()


def test_dataset_export_csv_download(auth_client, profile):
    dataset = create_ready_dataset(profile)

    response = auth_client.get(reverse("dataset_export", args=[dataset.key, "csv"]))

    assert response.status_code == 200
    assert response["Content-Type"] == "text/csv; charset=utf-8"
    assert response["Content-Disposition"].endswith('.csv"')
    exported = list(csv.DictReader(io.StringIO(response.content.decode())))
    assert exported == [
        {"name": "Ada", "email": "ada@example.com"},
        {"name": "Grace", "email": "grace@example.com"},
    ]


def test_dataset_export_escapes_content_disposition_filename(auth_client, profile):
    dataset = create_ready_dataset(profile)
    dataset.name = 'R&D "People"/2026'
    dataset.save(update_fields=["name"])

    response = auth_client.get(reverse("dataset_export", args=[dataset.key, "csv"]))

    assert response.status_code == 200
    assert response["Content-Disposition"] == 'attachment; filename="R&D \\"People\\"-2026.csv"'


def test_dataset_export_parquet_download(auth_client, profile):
    dataset = create_ready_dataset(profile)

    response = auth_client.get(reverse("dataset_export", args=[dataset.key, "parquet"]))

    assert response.status_code == 200
    assert response["Content-Type"] == "application/vnd.apache.parquet"
    dataframe = pl.read_parquet(io.BytesIO(response.content))
    assert dataframe.to_dicts() == [
        {"name": "Ada", "email": "ada@example.com"},
        {"name": "Grace", "email": "grace@example.com"},
    ]


def test_dataset_export_jsonl_download(auth_client, profile):
    dataset = create_ready_dataset(profile)

    response = auth_client.get(reverse("dataset_export", args=[dataset.key, "jsonl"]))

    assert response.status_code == 200
    assert response["Content-Type"] == "application/x-ndjson; charset=utf-8"
    assert response["Content-Disposition"].endswith('.jsonl"')
    exported = [json.loads(line) for line in response.content.decode().splitlines()]
    assert exported == [
        {"name": "Ada", "email": "ada@example.com"},
        {"name": "Grace", "email": "grace@example.com"},
    ]


def test_dataset_export_xlsx_download(auth_client, profile):
    dataset = create_ready_dataset(profile)

    response = auth_client.get(reverse("dataset_export", args=[dataset.key, "xlsx"]))

    assert response.status_code == 200
    assert (
        response["Content-Type"]
        == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert response["Content-Disposition"].endswith('.xlsx"')
    assert xlsx_cell_texts(response.content) == [
        "name",
        "email",
        "Ada",
        "ada@example.com",
        "Grace",
        "grace@example.com",
    ]


def test_dataset_export_xlsx_preserves_cell_whitespace(auth_client, profile):
    dataset = create_ready_dataset(profile)
    row = dataset.rows.get(row_number=1)
    row.data = {"name": " Ada ", "email": "ada@example.com"}
    row.save(update_fields=["data"])

    response = auth_client.get(reverse("dataset_export", args=[dataset.key, "xlsx"]))

    assert response.status_code == 200
    assert '<t xml:space="preserve"> Ada </t>' in xlsx_sheet_xml(response.content)
    assert xlsx_cell_texts(response.content)[2] == " Ada "


def test_dataset_export_sqlite_download(auth_client, profile):
    dataset = create_ready_dataset(profile)

    response = auth_client.get(reverse("dataset_export", args=[dataset.key, "sqlite"]))

    assert response.status_code == 200
    assert response["Content-Type"] == "application/vnd.sqlite3"
    assert response["Content-Disposition"].endswith('.sqlite"')
    assert sqlite_rows(response.content) == [
        {"name": "Ada", "email": "ada@example.com"},
        {"name": "Grace", "email": "grace@example.com"},
    ]


def test_sqlite_export_handles_empty_headers():
    content = rows_to_sqlite_bytes([], [])

    assert sqlite_table_columns(content) == ["_rowset_empty_export"]
    assert sqlite_rows(content) == []


def test_dataset_export_requires_ready_dataset(auth_client, profile):
    dataset = Dataset.objects.create(
        profile=profile,
        name="Preview Only",
        original_filename="preview.csv",
        status=DatasetStatus.PREVIEWED,
        headers=["name"],
        preview_rows=[{"name": "Ada"}],
        row_count=1,
    )

    response = auth_client.get(reverse("dataset_export", args=[dataset.key, "csv"]))

    assert response.status_code == 404


def test_dataset_api_crud_and_export(client, profile):
    dataset = create_ready_dataset(profile)
    api_key = profile.key

    list_response = client.get(f"/api/datasets/{dataset.key}/rows?api_key={api_key}")
    assert list_response.status_code == 200
    assert list_response.json()["count"] == 2

    public_key_list_response = client.get(
        f"/api/datasets/{dataset.public_key}/rows?api_key={api_key}"
    )
    assert public_key_list_response.status_code == 200
    assert public_key_list_response.json()["dataset"] == str(dataset.key)

    create_response = client.post(
        f"/api/datasets/{dataset.public_key}/rows?api_key={api_key}",
        data={"data": {"name": "Katherine", "email": "kat@example.com"}},
        content_type="application/json",
    )
    assert create_response.status_code == 200
    assert create_response.json()["dataset"] == str(dataset.key)
    row_id = create_response.json()["row"]["id"]
    assert create_response.json()["row"]["index_value"] == "kat@example.com"

    missing_index_patch_response = client.patch(
        f"/api/datasets/{dataset.key}/rows/by-index"
        f"?api_key={api_key}&index_value=missing@example.com",
        data={"data": {"name": "Missing"}},
        content_type="application/json",
    )
    assert missing_index_patch_response.status_code == 404

    conflicting_index_patch_response = client.patch(
        f"/api/datasets/{dataset.key}/rows/by-index?api_key={api_key}&index_value=kat@example.com",
        data={"data": {"email": "ada@example.com"}},
        content_type="application/json",
    )
    assert conflicting_index_patch_response.status_code == 409

    get_by_index_response = client.get(
        f"/api/datasets/{dataset.key}/rows/by-index?api_key={api_key}&index_value=kat@example.com"
    )
    assert get_by_index_response.status_code == 200
    assert get_by_index_response.json()["row"]["data"]["name"] == "Katherine"

    patch_by_index_response = client.patch(
        f"/api/datasets/{dataset.key}/rows/by-index?api_key={api_key}&index_value=kat@example.com",
        data={"data": {"name": "Katherine Johnson", "email": "katherine.johnson@example.com"}},
        content_type="application/json",
    )
    assert patch_by_index_response.status_code == 200
    assert patch_by_index_response.json()["row"]["id"] == row_id
    assert patch_by_index_response.json()["row"]["index_value"] == "katherine.johnson@example.com"
    assert patch_by_index_response.json()["row"]["data"]["name"] == "Katherine Johnson"

    get_updated_index_response = client.get(
        f"/api/datasets/{dataset.key}/rows/by-index"
        f"?api_key={api_key}&index_value=katherine.johnson@example.com"
    )
    assert get_updated_index_response.status_code == 200
    assert get_updated_index_response.json()["row"]["id"] == row_id

    patch_response = client.patch(
        f"/api/datasets/{dataset.public_key}/rows/{row_id}?api_key={api_key}",
        data={"data": {"email": "katherine@example.com", "ignored": "nope"}},
        content_type="application/json",
    )
    assert patch_response.status_code == 200
    assert patch_response.json()["dataset"] == str(dataset.key)
    assert patch_response.json()["row"]["data"] == {
        "name": "Katherine Johnson",
        "email": "katherine@example.com",
    }

    export_response = client.get(f"/api/datasets/{dataset.key}/export.csv?api_key={api_key}")
    assert export_response.status_code == 200
    exported = list(csv.DictReader(io.StringIO(export_response.content.decode())))
    assert exported[0] == {"name": "Ada", "email": "ada@example.com"}

    delete_response = client.delete(
        f"/api/datasets/{dataset.public_key}/rows/{row_id}?api_key={api_key}"
    )
    assert delete_response.status_code == 200
    assert delete_response.json()["dataset"] == str(dataset.key)
    assert not DatasetRow.objects.filter(id=row_id).exists()


def test_prepare_dataset_image_rejects_encoded_payload_above_limit(monkeypatch):
    source_bytes = image_bytes()

    monkeypatch.setattr(
        "apps.datasets.services.MAX_DATASET_IMAGE_BYTES",
        len(source_bytes) + 1,
    )
    monkeypatch.setattr(
        "apps.datasets.services._encoded_image_bytes",
        lambda image, image_format: b"x" * (len(source_bytes) + 2),
    )

    with pytest.raises(DatasetImageError):
        prepare_dataset_image(
            image_bytes=source_bytes,
            filename="photo.png",
            content_type="image/png",
        )


def test_prepare_dataset_image_rejects_decoded_payload_above_limit():
    image_base64 = base64.b64encode(b"x" * (MAX_DATASET_IMAGE_BYTES + 1)).decode()

    with pytest.raises(DatasetImageError):
        prepare_dataset_image(
            image_bytes=decode_image_base64(image_base64),
            filename="large.png",
            content_type="image/png",
        )


def test_prepare_dataset_image_rejects_malformed_image_data():
    image_base64 = base64.b64encode(b"not really an image").decode()

    with pytest.raises(DatasetImageError):
        prepare_dataset_image(
            image_bytes=decode_image_base64(image_base64),
            filename="broken.png",
            content_type="image/png",
        )


def test_prepare_dataset_image_rejects_content_type_mismatch():
    with pytest.raises(DatasetImageError):
        prepare_dataset_image(
            image_bytes=image_bytes(),
            filename="photo.jpg",
            content_type="image/jpeg",
        )


def test_prepare_dataset_image_rejects_images_over_pixel_limit(monkeypatch):
    monkeypatch.setattr("apps.datasets.services.MAX_DATASET_IMAGE_PIXELS", 5)

    with pytest.raises(DatasetImageError):
        prepare_dataset_image(
            image_bytes=image_bytes(),
            filename="photo.png",
            content_type="image/png",
        )


def test_prepare_dataset_image_rejects_zero_dimension_image(monkeypatch):
    class FakeImage:
        format = "PNG"
        size = (0, 1)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def load(self):
            return None

    fake_image = FakeImage()
    monkeypatch.setattr("apps.datasets.services.Image.open", lambda data: fake_image)
    monkeypatch.setattr(
        "apps.datasets.services.ImageOps.exif_transpose",
        lambda image: image,
    )

    with pytest.raises(DatasetImageError):
        prepare_dataset_image(
            image_bytes=b"fake",
            filename="zero.png",
            content_type="image/png",
        )


def test_prepare_dataset_image_rejects_exif_transposed_image_over_pixel_limit(monkeypatch):
    class FakeImage:
        format = "PNG"

        def __init__(self, size):
            self.size = size

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def load(self):
            return None

    opened_image = FakeImage((1, 1))
    transposed_image = FakeImage((3, 3))
    monkeypatch.setattr("apps.datasets.services.MAX_DATASET_IMAGE_PIXELS", 5)
    monkeypatch.setattr("apps.datasets.services.Image.open", lambda data: opened_image)
    monkeypatch.setattr(
        "apps.datasets.services.ImageOps.exif_transpose",
        lambda image: transposed_image,
    )

    with pytest.raises(DatasetImageError):
        prepare_dataset_image(
            image_bytes=b"fake",
            filename="rotated.png",
            content_type="image/png",
        )


def test_prepare_dataset_image_accepts_palette_png():
    prepared = prepare_dataset_image(
        image_bytes=palette_image_bytes(),
        filename="palette.png",
        content_type="image/png",
    )

    assert prepared.content_type == "image/png"
    assert prepared.width == 3
    assert prepared.height == 2
    assert prepared.image_bytes.startswith(b"\x89PNG")


def test_prepare_dataset_image_skips_larger_thumbnail_for_tiny_png():
    prepared = prepare_dataset_image(
        image_bytes=image_bytes(),
        filename="tiny.png",
        content_type="image/png",
    )

    assert prepared.thumbnail_bytes is None


def test_image_attach_records_failed_rollback_file_cleanup(profile, monkeypatch):
    dataset = Dataset.objects.create(
        profile=profile,
        name="Image cleanup",
        original_filename="Created via API",
        file_type="api",
        status=DatasetStatus.READY,
        headers=["sku", "photo"],
        column_schema={"photo": {"type": DatasetColumnType.IMAGE}},
        index_column="sku",
        row_count=1,
        confirmed_at=timezone.now(),
        processed_at=timezone.now(),
    )
    DatasetRow.objects.create(
        dataset=dataset,
        row_number=1,
        index_value="A-1",
        data={"sku": "A-1", "photo": ""},
    )
    storage = storages[DATASET_ASSET_STORAGE_ALIAS]
    saved_names = []
    deleted_names = []

    class PreparedImage:
        filename = "photo.png"
        content_type = "image/png"
        image_bytes = b"original"
        thumbnail_bytes = b"thumbnail"
        byte_size = len(image_bytes)
        width = 3
        height = 2
        checksum = "a" * 64

    def fail_thumbnail_save(name: str, content, *args, **kwargs) -> str:
        saved_names.append(name)
        if name.endswith("thumbnail.jpg"):
            raise OSError("thumbnail upload failed")
        return name

    def fail_delete(name: str) -> None:
        deleted_names.append(name)
        raise OSError("delete failed")

    monkeypatch.setattr(
        "apps.api.services.prepare_dataset_image",
        lambda **kwargs: PreparedImage(),
    )
    monkeypatch.setattr(storage, "save", fail_thumbnail_save)
    monkeypatch.setattr(storage, "delete", fail_delete)

    with pytest.raises(DatasetServiceError) as exc_info:
        attach_profile_dataset_image_asset(
            profile,
            str(dataset.key),
            column_name="photo",
            image_base64=image_base64(),
            index_value="A-1",
        )

    assert exc_info.value.status_code == 500
    assert len(saved_names) == 2
    assert deleted_names == [saved_names[0]]
    deletion = DatasetAssetFileDeletion.objects.get(file_name=saved_names[0])
    assert deletion.storage_alias == DATASET_ASSET_STORAGE_ALIAS
    assert deletion.attempts == 1
    assert "delete failed" in deletion.last_error
    assert DatasetAsset.objects.filter(dataset=dataset).count() == 0


def test_dataset_asset_delete_records_failed_file_cleanup(
    profile,
    django_capture_on_commit_callbacks,
    monkeypatch,
):
    dataset = create_ready_dataset(profile)
    row = dataset.rows.first()
    asset = DatasetAsset.objects.create(
        profile=profile,
        dataset=dataset,
        row=row,
        column_name="photo",
        file="dataset-assets/test/original.png",
        thumbnail="dataset-assets/test/thumbnail.jpg",
        original_filename="photo.png",
        content_type="image/png",
        byte_size=10,
        width=3,
        height=2,
        checksum="a" * 64,
    )
    storage = storages[DATASET_ASSET_STORAGE_ALIAS]
    deleted_names = []

    def fail_original_delete(name: str) -> None:
        deleted_names.append(name)
        if name == asset.file.name:
            raise OSError("r2 timeout")

    monkeypatch.setattr(storage, "delete", fail_original_delete)

    with django_capture_on_commit_callbacks(execute=True):
        asset.delete()

    assert deleted_names == [asset.file.name, asset.thumbnail.name]
    deletion = DatasetAssetFileDeletion.objects.get(file_name=asset.file.name)
    assert deletion.storage_alias == DATASET_ASSET_STORAGE_ALIAS
    assert deletion.attempts == 1
    assert deletion.deleted_at is None
    assert "r2 timeout" in deletion.last_error
    assert not DatasetAssetFileDeletion.objects.filter(file_name=asset.thumbnail.name).exists()

    retry_deleted_names = []
    monkeypatch.setattr(storage, "delete", retry_deleted_names.append)

    result = retry_dataset_asset_file_deletions()

    assert result == {"attempted": 1, "deleted": 1, "failed": 0}
    assert retry_deleted_names == [asset.file.name]
    deletion.refresh_from_db()
    assert deletion.deleted_at is not None
    assert deletion.last_error == ""


def test_dataset_api_attaches_image_asset_and_serves_content(client, profile, monkeypatch):
    create_response = client.post(
        f"/api/datasets?api_key={profile.key}",
        data={
            "name": "Product photos",
            "headers": ["sku", "name", "photo"],
            "index_column": "sku",
            "column_types": {
                "photo": {
                    "type": "image",
                    "description": "Primary product photo",
                }
            },
            "rows": [{"sku": "A-1", "name": "Adapter", "photo": ""}],
        },
        content_type="application/json",
    )
    assert create_response.status_code == 201
    assert create_response.json()["dataset"]["public_enabled"] is False
    assert create_response.json()["dataset"]["public_url"] is None
    dataset = Dataset.objects.get(key=create_response.json()["dataset"]["key"], profile=profile)

    attach_response = client.post(
        f"/api/datasets/{dataset.key}/rows/by-index/image?api_key={profile.key}&index_value=A-1",
        data={
            "column_name": "photo",
            "filename": "adapter.png",
            "content_type": "image/png",
            "image_base64": image_base64(),
        },
        content_type="application/json",
    )

    assert attach_response.status_code == 200
    payload = attach_response.json()
    asset_payload = payload["asset"]
    asset = DatasetAsset.objects.get(key=asset_payload["key"], dataset=dataset)
    row = dataset.rows.get(index_value="A-1")
    row.refresh_from_db()
    assert payload["row"]["data"]["photo"] == asset.asset_ref
    assert row.data["photo"] == asset.asset_ref
    assert asset_payload["ref"] == asset.asset_ref
    assert asset_payload["content_type"] == "image/png"
    assert asset_payload["width"] == 3
    assert asset_payload["height"] == 2
    assert asset_payload["has_thumbnail"] is False
    assert asset_payload["thumbnail_url"].endswith(
        f"/api/datasets/{dataset.key}/assets/{asset.key}/content?variant=thumbnail"
    )
    assert asset_payload["content_url_auth_required"] is True
    assert asset_payload["public_enabled"] is False
    assert asset_payload["public_content_url"] is None
    assert asset_payload["public_thumbnail_url"] is None
    assert asset_payload["content_url"].endswith(
        f"/api/datasets/{dataset.key}/assets/{asset.key}/content?variant=original"
    )
    assert asset.file.name.endswith("/original.png")
    assert asset.thumbnail.name == ""
    assert payload["row"]["assets"][0]["ref"] == asset.asset_ref
    assert payload["row"]["assets"][0]["column"] == "photo"

    def fail_head_file_open(*args, **kwargs):
        raise AssertionError("HEAD requests should not read image asset bytes.")

    def fail_public_head_work(*args, **kwargs):
        raise AssertionError("Public preview HEAD should not build row display state.")

    metadata_response = client.get(
        f"/api/datasets/{dataset.key}/assets/{asset.key}?api_key={profile.key}"
    )
    assert metadata_response.status_code == 200
    assert metadata_response.json()["asset"]["ref"] == asset.asset_ref
    assert metadata_response.json()["asset"]["has_thumbnail"] is False
    assert metadata_response.json()["asset"]["thumbnail_url"].endswith(
        f"/api/datasets/{dataset.key}/assets/{asset.key}/content?variant=thumbnail"
    )
    assert metadata_response.json()["asset"]["public_content_url"] is None

    unauthenticated_head_response = client.head(
        f"/api/datasets/{dataset.key}/assets/{asset.key}/content?variant=original"
    )
    assert unauthenticated_head_response.status_code == 401

    with monkeypatch.context() as head_monkeypatch:
        head_monkeypatch.setattr(
            storages[DATASET_ASSET_STORAGE_ALIAS],
            "open",
            fail_head_file_open,
        )
        original_head_response = client.head(
            f"/api/datasets/{dataset.key}/assets/{asset.key}/content"
            f"?api_key={profile.key}&variant=original"
        )
    assert original_head_response.status_code == 200
    assert original_head_response["Content-Type"] == "image/png"

    list_response = client.get(f"/api/datasets/{dataset.key}/rows?api_key={profile.key}")
    assert list_response.status_code == 200
    assert list_response.json()["rows"][0]["assets"][0]["ref"] == asset.asset_ref

    row_response = client.get(
        f"/api/datasets/{dataset.key}/rows/by-index?api_key={profile.key}&index_value=A-1"
    )
    assert row_response.status_code == 200
    assert row_response.json()["row"]["assets"][0]["ref"] == asset.asset_ref

    original_response = client.get(
        f"/api/datasets/{dataset.key}/assets/{asset.key}/content"
        f"?api_key={profile.key}&variant=original"
    )
    assert original_response.status_code == 200
    assert original_response["Content-Type"] == "image/png"
    assert original_response["X-Content-Type-Options"] == "nosniff"
    assert original_response["Cache-Control"] == "private, max-age=86400, immutable"
    assert original_response.content.startswith(b"\x89PNG")

    thumbnail_response = client.get(
        f"/api/datasets/{dataset.key}/assets/{asset.key}/content"
        f"?api_key={profile.key}&variant=thumbnail"
    )
    assert thumbnail_response.status_code == 200
    assert thumbnail_response["Content-Type"] == "image/png"
    assert thumbnail_response["Cache-Control"] == "private, max-age=86400, immutable"
    assert thumbnail_response.content.startswith(b"\x89PNG")

    client.force_login(profile.user)
    dataset_detail = client.get(dataset.get_absolute_url())
    detail_content = dataset_detail.content.decode()
    assert dataset_detail.status_code == 200
    assert "adapter.png" in detail_content
    assert reverse("dataset_asset_content", args=[dataset.key, asset.key]) in detail_content

    dataset.public_enabled = True
    dataset.save(update_fields=["public_enabled"])
    public_metadata_response = client.get(
        f"/api/datasets/{dataset.key}/assets/{asset.key}?api_key={profile.key}"
    )
    public_asset_payload = public_metadata_response.json()["asset"]
    assert public_asset_payload["public_enabled"] is True
    assert public_asset_payload["public_content_url"].endswith(
        f"/share/datasets/{dataset.public_key}/assets/{asset.key}/content/?variant=original"
    )
    assert public_asset_payload["public_thumbnail_url"].endswith(
        f"/share/datasets/{dataset.public_key}/assets/{asset.key}/content/?variant=thumbnail"
    )
    with monkeypatch.context() as head_monkeypatch:
        head_monkeypatch.setattr(
            "apps.datasets.views._dataset_row_query_context",
            fail_public_head_work,
        )
        public_head_response = client.head(dataset.get_public_url())
    assert public_head_response.status_code == 200
    public_response = client.get(dataset.get_public_url())
    public_content = public_response.content.decode()
    assert public_response.status_code == 200
    assert "adapter.png" in public_content
    assert (
        reverse("public_dataset_asset_content", args=[dataset.public_key, asset.key])
        in public_content
    )
    public_asset_response = client.get(
        f"{reverse('public_dataset_asset_content', args=[dataset.public_key, asset.key])}"
        "?variant=thumbnail"
    )
    assert public_asset_response.status_code == 200
    assert public_asset_response["X-Robots-Tag"] == "noindex, nofollow, noarchive"
    with monkeypatch.context() as head_monkeypatch:
        head_monkeypatch.setattr(
            storages[DATASET_ASSET_STORAGE_ALIAS],
            "open",
            fail_head_file_open,
        )
        public_asset_head_response = client.head(
            f"{reverse('public_dataset_asset_content', args=[dataset.public_key, asset.key])}"
            "?variant=thumbnail"
        )
    assert public_asset_head_response.status_code == 200
    assert public_asset_head_response["Content-Type"] == "image/png"

    public_row_response = client.get(
        reverse("public_dataset_row_detail", args=[dataset.public_key, row.id])
    )
    assert public_row_response.status_code == 200
    assert "adapter.png" in public_row_response.content.decode()
    with monkeypatch.context() as head_monkeypatch:
        head_monkeypatch.setattr(
            "apps.datasets.views._row_cells",
            fail_public_head_work,
        )
        public_row_head_response = client.head(
            reverse("public_dataset_row_detail", args=[dataset.public_key, row.id])
        )
    assert public_row_head_response.status_code == 200

    password_response = client.patch(
        f"/api/datasets/{dataset.key}/public-preview?api_key={profile.key}",
        data={"public_enabled": True, "public_password": "secret-table"},
        content_type="application/json",
    )
    assert password_response.status_code == 200
    password_metadata_response = client.get(
        f"/api/datasets/{dataset.key}/assets/{asset.key}?api_key={profile.key}"
    )
    password_asset_payload = password_metadata_response.json()["asset"]
    assert password_asset_payload["public_enabled"] is True
    assert password_asset_payload["public_password_protected"] is True
    assert password_asset_payload["public_content_url"] is None
    assert password_asset_payload["public_thumbnail_url"] is None


def test_dataset_api_rejects_direct_image_values_and_clears_asset(client, profile):
    create_response = client.post(
        f"/api/datasets?api_key={profile.key}",
        data={
            "name": "Receipts",
            "headers": ["receipt_id", "image"],
            "index_column": "receipt_id",
            "column_types": {"image": "image"},
        },
        content_type="application/json",
    )
    assert create_response.status_code == 201
    dataset = Dataset.objects.get(key=create_response.json()["dataset"]["key"], profile=profile)

    invalid_create = client.post(
        f"/api/datasets/{dataset.key}/rows?api_key={profile.key}",
        data={"data": {"receipt_id": "R-1", "image": "https://example.com/receipt.png"}},
        content_type="application/json",
    )
    assert invalid_create.status_code == 400
    assert invalid_create.json()["detail"] == (
        "Column 'image' is an image column. Leave it blank and attach an image asset."
    )

    create_row = client.post(
        f"/api/datasets/{dataset.key}/rows?api_key={profile.key}",
        data={"data": {"receipt_id": "R-1", "image": ""}},
        content_type="application/json",
    )
    assert create_row.status_code == 200
    row_id = create_row.json()["row"]["id"]

    attach_response = client.post(
        f"/api/datasets/{dataset.key}/rows/{row_id}/image?api_key={profile.key}",
        data={
            "column_name": "image",
            "filename": "receipt.png",
            "content_type": "image/png",
            "image_base64": image_base64(),
        },
        content_type="application/json",
    )
    assert attach_response.status_code == 200
    asset = DatasetAsset.objects.get(key=attach_response.json()["asset"]["key"])

    idempotent_patch = client.patch(
        f"/api/datasets/{dataset.key}/rows/{row_id}?api_key={profile.key}",
        data={"data": {"image": asset.asset_ref}},
        content_type="application/json",
    )
    assert idempotent_patch.status_code == 200
    assert idempotent_patch.json()["row"]["data"]["image"] == asset.asset_ref
    assert DatasetAsset.objects.filter(pk=asset.pk).exists()

    invalid_patch = client.patch(
        f"/api/datasets/{dataset.key}/rows/{row_id}?api_key={profile.key}",
        data={"data": {"image": "asset:00000000-0000-0000-0000-000000000000"}},
        content_type="application/json",
    )
    assert invalid_patch.status_code == 400
    assert DatasetAsset.objects.filter(pk=asset.pk).exists()

    invalid_clear = client.patch(
        f"/api/datasets/{dataset.key}/rows/{row_id}?api_key={profile.key}",
        data={"data": {"receipt_id": "", "image": ""}},
        content_type="application/json",
    )
    assert invalid_clear.status_code == 400
    assert DatasetAsset.objects.filter(pk=asset.pk).exists()

    clear_response = client.patch(
        f"/api/datasets/{dataset.key}/rows/{row_id}?api_key={profile.key}",
        data={"data": {"image": ""}},
        content_type="application/json",
    )
    assert clear_response.status_code == 200
    assert clear_response.json()["row"]["data"]["image"] == ""
    assert not DatasetAsset.objects.filter(pk=asset.pk).exists()


def test_dataset_api_renames_and_drops_image_column_assets(client, profile):
    create_response = client.post(
        f"/api/datasets?api_key={profile.key}",
        data={
            "name": "Catalog images",
            "headers": ["sku", "photo"],
            "index_column": "sku",
            "column_types": {"photo": "image"},
            "rows": [{"sku": "A-1", "photo": ""}],
        },
        content_type="application/json",
    )
    assert create_response.status_code == 201
    dataset = Dataset.objects.get(key=create_response.json()["dataset"]["key"], profile=profile)
    row = dataset.rows.get(index_value="A-1")

    attach_response = client.post(
        f"/api/datasets/{dataset.key}/rows/{row.id}/image?api_key={profile.key}",
        data={
            "column_name": "photo",
            "filename": "adapter.png",
            "content_type": "image/png",
            "image_base64": image_base64(),
        },
        content_type="application/json",
    )
    assert attach_response.status_code == 200
    asset = DatasetAsset.objects.get(key=attach_response.json()["asset"]["key"])

    rename_response = client.post(
        f"/api/datasets/{dataset.key}/columns/rename?api_key={profile.key}",
        data={"old_name": "photo", "new_name": "hero_image"},
        content_type="application/json",
    )
    assert rename_response.status_code == 200
    asset.refresh_from_db()
    row.refresh_from_db()
    assert asset.column_name == "hero_image"
    assert row.data["hero_image"] == asset.asset_ref
    assert "photo" not in row.data

    drop_response = client.post(
        f"/api/datasets/{dataset.key}/columns/drop?api_key={profile.key}",
        data={"name": "hero_image"},
        content_type="application/json",
    )
    assert drop_response.status_code == 200
    assert not DatasetAsset.objects.filter(pk=asset.pk).exists()


def test_dataset_api_rejects_image_index_and_nonblank_image_defaults(client, profile):
    image_index_response = client.post(
        f"/api/datasets?api_key={profile.key}",
        data={
            "name": "Invalid image index",
            "headers": ["photo", "name"],
            "index_column": "photo",
            "column_types": {"photo": "image"},
        },
        content_type="application/json",
    )
    assert image_index_response.status_code == 400
    assert image_index_response.json()["detail"] == (
        "Image columns cannot be used as the dataset index."
    )

    dataset = create_ready_dataset(profile)
    invalid_default_response = client.post(
        f"/api/datasets/{dataset.key}/columns?api_key={profile.key}",
        data={
            "name": "photo",
            "default_value": "https://example.com/photo.png",
            "column_type": "image",
        },
        content_type="application/json",
    )
    assert invalid_default_response.status_code == 400
    assert invalid_default_response.json()["detail"] == (
        "Column 'photo' is an image column. Leave it blank and attach an image asset."
    )


def test_dataset_api_filters_and_sorts_rows(client, profile):
    dataset = configure_filterable_dataset(create_ready_dataset(profile))
    api_key = profile.key

    filtered_response = client.get(
        f"/api/datasets/{dataset.key}/rows",
        {
            "api_key": api_key,
            "filters": json.dumps({"active": "true"}),
            "sort": "name",
            "direction": "desc",
        },
    )

    assert filtered_response.status_code == 200
    payload = filtered_response.json()
    assert payload["count"] == 2
    assert payload["total_count"] == 3
    assert payload["filters"] == {"active": "true"}
    assert payload["sort"] == "name"
    assert payload["direction"] == "desc"
    assert [row["data"]["name"] for row in payload["rows"]] == [
        "Katherine Johnson",
        "Ada Lovelace",
    ]

    search_response = client.get(
        f"/api/datasets/{dataset.key}/rows",
        {
            "api_key": api_key,
            "query": "grace",
            "sort": "score",
        },
    )

    assert search_response.status_code == 200
    assert search_response.json()["count"] == 1
    assert search_response.json()["rows"][0]["data"]["name"] == "Grace Hopper"

    invalid_sort_response = client.get(
        f"/api/datasets/{dataset.key}/rows",
        {"api_key": api_key, "sort": "missing"},
    )
    assert invalid_sort_response.status_code == 400
    assert "Row sort" in invalid_sort_response.json()["detail"]

    invalid_filter_response = client.get(
        f"/api/datasets/{dataset.key}/rows",
        {
            "api_key": api_key,
            "filters": json.dumps({"missing": "value"}),
        },
    )
    assert invalid_filter_response.status_code == 400
    assert "not in this dataset" in invalid_filter_response.json()["detail"]

    malformed_filters_response = client.get(
        f"/api/datasets/{dataset.key}/rows",
        {"api_key": api_key, "filters": "not-json"},
    )
    assert malformed_filters_response.status_code == 400
    assert "filters must be a JSON object" in malformed_filters_response.json()["detail"]


def test_dataset_row_service_preserves_native_falsy_filter_values(profile):
    dataset = configure_filterable_dataset(create_ready_dataset(profile))

    payload = list_profile_dataset_rows(
        profile,
        str(dataset.key),
        filters={"active": False},
    )

    assert payload["count"] == 1
    assert payload["filters"] == {"active": "False"}
    assert [row["data"]["name"] for row in payload["rows"]] == ["Grace Hopper"]


def test_dataset_row_service_sorts_datetime_columns_chronologically(profile):
    dataset = configure_datetime_dataset(create_ready_dataset(profile))

    payload = list_profile_dataset_rows(
        profile,
        str(dataset.key),
        sort="event_at",
    )

    assert [row["data"]["event_name"] for row in payload["rows"]] == [
        "Offset early",
        "UTC later",
        "Next day",
    ]


def test_dataset_row_service_sorts_invalid_datetime_cells_last(profile):
    dataset = configure_datetime_dataset(create_ready_dataset(profile))
    add_invalid_datetime_row(dataset)

    payload = list_profile_dataset_rows(
        profile,
        str(dataset.key),
        sort="event_at",
    )

    assert [row["data"]["event_name"] for row in payload["rows"]] == [
        "Offset early",
        "UTC later",
        "Next day",
        "Invalid date",
        "Invalid time",
        "Invalid year",
    ]


def test_dataset_row_service_handles_supported_non_iso_datetime_formats(profile):
    dataset = configure_datetime_dataset(create_ready_dataset(profile))
    add_supported_datetime_format_rows(dataset)

    sorted_payload = list_profile_dataset_rows(
        profile,
        str(dataset.key),
        sort="event_at",
    )

    assert [row["data"]["event_name"] for row in sorted_payload["rows"]] == [
        "Century leap",
        "Century slash leap",
        "YMD slash",
        "YMD slash datetime",
        "MDY slash date",
        "Offset early",
        "MDY slash compact time",
        "MDY slash",
        "UTC later",
        "Next day",
    ]

    recent_filtered_queryset, row_query = apply_dataset_row_query(
        dataset.rows.all(),
        dataset,
        filters={"event_at": "2026-05-14T08:30"},
        filter_operators={"event_at": "above"},
        sort="event_at",
        strict=True,
    )

    assert row_query["filter_operators"] == {"event_at": "above"}
    assert [row.data["event_name"] for row in recent_filtered_queryset] == [
        "MDY slash",
        "UTC later",
        "Next day",
    ]

    ymd_slash_filtered_queryset, row_query = apply_dataset_row_query(
        dataset.rows.all(),
        dataset,
        filters={"event_at": "2026/5/13 8:45"},
        filter_operators={"event_at": "above"},
        sort="event_at",
        strict=True,
    )

    assert row_query["filter_operators"] == {"event_at": "above"}
    assert [row.data["event_name"] for row in ymd_slash_filtered_queryset] == [
        "MDY slash date",
        "Offset early",
        "MDY slash compact time",
        "MDY slash",
        "UTC later",
        "Next day",
    ]

    century_filtered_queryset, row_query = apply_dataset_row_query(
        dataset.rows.all(),
        dataset,
        filters={"event_at": "2001-01-01"},
        filter_operators={"event_at": "below"},
        sort="event_at",
        strict=True,
    )

    assert row_query["filter_operators"] == {"event_at": "below"}
    assert [row.data["event_name"] for row in century_filtered_queryset] == [
        "Century leap",
        "Century slash leap",
    ]


def test_dataset_api_exports_jsonl_xlsx_and_sqlite(client, profile):
    dataset = create_ready_dataset(profile)
    api_key = profile.key

    jsonl_response = client.get(f"/api/datasets/{dataset.key}/export.jsonl?api_key={api_key}")
    assert jsonl_response.status_code == 200
    assert jsonl_response["Content-Type"] == "application/x-ndjson; charset=utf-8"
    assert [json.loads(line) for line in jsonl_response.content.decode().splitlines()] == [
        {"name": "Ada", "email": "ada@example.com"},
        {"name": "Grace", "email": "grace@example.com"},
    ]

    xlsx_response = client.get(f"/api/datasets/{dataset.key}/export.xlsx?api_key={api_key}")
    assert xlsx_response.status_code == 200
    assert (
        xlsx_response["Content-Type"]
        == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert xlsx_cell_texts(xlsx_response.content)[:4] == [
        "name",
        "email",
        "Ada",
        "ada@example.com",
    ]

    sqlite_response = client.get(f"/api/datasets/{dataset.key}/export.sqlite?api_key={api_key}")
    assert sqlite_response.status_code == 200
    assert sqlite_response["Content-Type"] == "application/vnd.sqlite3"
    assert sqlite_rows(sqlite_response.content)[0] == {
        "name": "Ada",
        "email": "ada@example.com",
    }


def test_dataset_api_archives_and_restores_dataset(client, profile):
    project = Project.objects.create(profile=profile, name="Cleanup")
    dataset = create_ready_dataset(profile)
    dataset.project = project
    dataset.public_enabled = True
    dataset.save(update_fields=["project", "public_enabled"])
    public_url = reverse("public_dataset", args=[dataset.public_key])

    archive_response = client.delete(f"/api/datasets/{dataset.key}?api_key={profile.key}")

    assert archive_response.status_code == 200
    assert archive_response.json()["message"] == "Dataset archived."
    dataset.refresh_from_db()
    assert dataset.archived_at is not None
    assert dataset.public_enabled is False
    assert DatasetRow.objects.filter(dataset=dataset).count() == 2

    list_response = client.get(f"/api/datasets?api_key={profile.key}")
    assert list_response.status_code == 200
    assert list_response.json()["datasets"] == []

    project_response = client.get(f"/api/projects/{project.key}?api_key={profile.key}")
    assert project_response.status_code == 200
    assert project_response.json()["project"]["dataset_count"] == 0
    assert project_response.json()["datasets"]["datasets"] == []

    public_response = client.get(public_url)
    assert public_response.status_code == 404

    already_archived_response = client.delete(f"/api/datasets/{dataset.key}?api_key={profile.key}")
    assert already_archived_response.status_code == 200
    assert already_archived_response.json()["message"] == "Dataset was already archived."

    restore_response = client.post(f"/api/datasets/{dataset.key}/restore?api_key={profile.key}")

    assert restore_response.status_code == 200
    assert restore_response.json()["message"] == "Dataset restored."
    dataset.refresh_from_db()
    assert dataset.archived_at is None
    assert dataset.public_enabled is False

    already_restored_response = client.post(
        f"/api/datasets/{dataset.key}/restore?api_key={profile.key}"
    )
    assert already_restored_response.status_code == 200
    assert already_restored_response.json()["message"] == "Dataset was not archived."

    restored_list_response = client.get(f"/api/datasets?api_key={profile.key}")
    assert restored_list_response.status_code == 200
    assert [item["key"] for item in restored_list_response.json()["datasets"]] == [str(dataset.key)]
    assert list(dataset.mutations.values_list("mutation_type", flat=True)) == [
        DatasetMutationType.DATASET_RESTORED,
        DatasetMutationType.DATASET_ARCHIVED,
    ]


def test_archiving_already_archived_dataset_records_public_preview_disable(client, profile):
    dataset = create_ready_dataset(profile)
    dataset.archived_at = timezone.now()
    dataset.public_enabled = True
    dataset.save(update_fields=["archived_at", "public_enabled"])

    response = client.delete(f"/api/datasets/{dataset.key}?api_key={profile.key}")

    assert response.status_code == 200
    assert response.json()["message"] == "Dataset archived."
    dataset.refresh_from_db()
    assert dataset.archived_at is not None
    assert dataset.public_enabled is False
    mutation = dataset.mutations.get()
    assert mutation.mutation_type == DatasetMutationType.PUBLIC_PREVIEW_UPDATED
    assert mutation.summary == "Public preview disabled."
    assert mutation.metadata == {
        "previous_public_enabled": True,
        "public_enabled": False,
    }


def test_dataset_api_lists_archived_datasets_separately(client, profile):
    active_dataset = create_ready_dataset(profile)
    archived_dataset = create_ready_dataset(profile)
    archived_dataset.name = "Archived people"
    archived_dataset.archived_at = timezone.now()
    archived_dataset.save(update_fields=["name", "archived_at"])
    preview_archived_dataset = create_ready_dataset(profile)
    preview_archived_dataset.name = "Archived draft"
    preview_archived_dataset.status = DatasetStatus.PREVIEWED
    preview_archived_dataset.archived_at = timezone.now()
    preview_archived_dataset.save(update_fields=["name", "status", "archived_at"])

    archived_response = client.get(f"/api/datasets/archived?api_key={profile.key}")

    assert archived_response.status_code == 200
    assert archived_response.json()["total_count"] == 1
    assert [item["key"] for item in archived_response.json()["datasets"]] == [
        str(archived_dataset.key)
    ]
    assert archived_response.json()["datasets"][0]["name"] == "Archived people"
    assert archived_response.json()["datasets"][0]["archived_at"] is not None
    assert "Archived draft" not in {item["name"] for item in archived_response.json()["datasets"]}

    active_response = client.get(f"/api/datasets?api_key={profile.key}")
    assert active_response.status_code == 200
    assert [item["key"] for item in active_response.json()["datasets"]] == [str(active_dataset.key)]


def test_named_agent_api_key_attribution_is_visible_in_dataset_ui(client, profile):
    codex = create_agent_api_key(profile, "Codex")
    openclaw = create_agent_api_key(profile, "OpenClaw")
    project = Project.objects.create(profile=profile, name="Agent work")

    create_dataset_response = client.post(
        "/api/datasets",
        data={
            "name": "Agent leads",
            "project_key": str(project.key),
            "headers": ["email", "name"],
            "index_column": "email",
        },
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {codex.raw_key}",
    )
    assert create_dataset_response.status_code == 201

    dataset = Dataset.objects.get(key=create_dataset_response.json()["dataset"]["key"])
    create_row_response = client.post(
        f"/api/datasets/{dataset.key}/rows",
        data={"data": {"email": "ada@example.com", "name": "Ada"}},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {openclaw.raw_key}",
    )
    assert create_row_response.status_code == 200

    dataset.refresh_from_db()
    row = dataset.rows.get()
    assert dataset.created_by_agent_api_key == codex.agent_api_key
    assert dataset.updated_by_agent_api_key == openclaw.agent_api_key
    assert row.created_by_agent_api_key == openclaw.agent_api_key
    assert row.updated_by_agent_api_key == openclaw.agent_api_key
    assert dataset.created_by_actor_label == "Codex"
    assert dataset.updated_by_actor_label == "OpenClaw"
    assert row.created_by_actor_label == "OpenClaw"
    assert row.updated_by_actor_label == "OpenClaw"

    mutations = list(dataset.mutations.order_by("created_at", "id"))
    assert [mutation.mutation_type for mutation in mutations] == [
        DatasetMutationType.DATASET_CREATED,
        DatasetMutationType.ROW_CREATED,
    ]
    assert [mutation.actor_label for mutation in mutations] == ["Codex", "OpenClaw"]

    client.force_login(profile.user)
    list_content = client.get(reverse("home")).content.decode()
    detail_content = client.get(dataset.get_absolute_url()).content.decode()
    changes_response = client.get(dataset.get_changes_url())
    changes_content = changes_response.content.decode()
    settings_content = client.get(dataset.get_settings_url()).content.decode()
    project_content = client.get(project.get_absolute_url()).content.decode()
    home_content = client.get(reverse("home")).content.decode()

    assert changes_response.status_code == 200
    assert "Created by Codex · Last updated by OpenClaw" in list_content
    assert "Codex" in detail_content
    assert "OpenClaw" in settings_content
    assert "Touched by" in detail_content
    assert f'href="{row.get_absolute_url()}"' in detail_content
    assert ">OpenClaw</a>" in detail_content
    assert f'href="{dataset.get_changes_url()}"' in detail_content
    assert "Dataset created with 0 rows and 2 columns." not in detail_content
    assert "Row 1 added." not in detail_content
    assert "Recent changes" in changes_content
    assert "Dataset created with 0 rows and 2 columns." in changes_content
    assert "Row 1 added." in changes_content
    assert "Created by Codex · Last updated by OpenClaw" in project_content
    assert "Last updated by OpenClaw" in home_content


def test_row_update_mutation_records_field_diffs_and_renders_history(client, profile):
    dataset = create_ready_dataset(profile)
    row = dataset.rows.get(row_number=1)

    patch_response = client.patch(
        f"/api/datasets/{dataset.key}/rows/{row.id}?api_key={profile.key}",
        data={
            "data": {
                "email": "ada+updated@example.com",
                "name": "Ada Lovelace",
            }
        },
        content_type="application/json",
    )

    assert patch_response.status_code == 200
    mutation = dataset.mutations.get(mutation_type=DatasetMutationType.ROW_UPDATED)
    assert mutation.metadata == {
        "row_id": row.id,
        "row_number": 1,
        "changed_fields": ["email", "name"],
        "field_changes": [
            {
                "field": "email",
                "before": "ada@example.com",
                "after": "ada+updated@example.com",
            },
            {
                "field": "name",
                "before": "Ada",
                "after": "Ada Lovelace",
            },
        ],
        "value_changes_recorded": True,
        "index_changed": True,
    }

    client.force_login(profile.user)
    detail_content = client.get(dataset.get_absolute_url()).content.decode()
    changes_content = client.get(dataset.get_changes_url()).content.decode()

    assert "Row 1 updated." not in detail_content
    assert "Row 1 updated." in changes_content
    assert "email" in changes_content
    assert "ada@example.com" in changes_content
    assert "ada+updated@example.com" in changes_content
    assert "Previous value" not in changes_content
    assert "New value" not in changes_content
    assert "name" in changes_content
    assert "Ada" in changes_content
    assert "Ada Lovelace" in changes_content


def test_dataset_changes_hides_legacy_placeholder_diff_labels(auth_client, profile):
    dataset = create_ready_dataset(profile)
    row = dataset.rows.get(row_number=1)
    second_row = dataset.rows.get(row_number=2)
    record_dataset_mutation(
        dataset,
        DatasetMutationType.ROW_UPDATED,
        "Row 1 updated.",
        target_type="row",
        target_identifier=row.id,
        metadata={
            "row_id": row.id,
            "row_number": row.row_number,
            "changed_fields": ["name"],
            "field_changes": [
                {
                    "field": "name",
                    "before": "Previous value",
                    "after": "New value",
                }
            ],
            "index_changed": False,
        },
    )
    record_dataset_mutation(
        dataset,
        DatasetMutationType.ROW_UPDATED,
        "Row 2 updated.",
        target_type="row",
        target_identifier=second_row.id,
        metadata={
            "row_id": second_row.id,
            "row_number": second_row.row_number,
            "changed_fields": ["name"],
            "field_changes": [
                {
                    "field": "name",
                    "before": "",
                    "after": "Filled",
                }
            ],
            "index_changed": False,
        },
    )

    changes_content = auth_client.get(dataset.get_changes_url()).content.decode()

    assert "Row 1 updated." in changes_content
    assert "Row 2 updated." in changes_content
    assert "Not recorded" in changes_content
    assert "Blank" in changes_content
    assert "Filled" not in changes_content
    assert "Previous value" not in changes_content
    assert "New value" not in changes_content


def test_row_update_mutation_omits_noop_fields(client, profile):
    dataset = create_ready_dataset(profile)
    row = dataset.rows.get(row_number=1)

    patch_response = client.patch(
        f"/api/datasets/{dataset.key}/rows/{row.id}?api_key={profile.key}",
        data={"data": {"email": "ada@example.com", "name": "Ada"}},
        content_type="application/json",
    )

    assert patch_response.status_code == 200
    mutation = dataset.mutations.get(mutation_type=DatasetMutationType.ROW_UPDATED)
    assert mutation.metadata == {
        "row_id": row.id,
        "row_number": 1,
        "changed_fields": [],
        "field_changes": [],
        "value_changes_recorded": True,
        "index_changed": False,
    }


def test_row_update_service_null_patch_clears_cell(profile):
    dataset = create_ready_dataset(profile)
    row = dataset.rows.get(row_number=1)

    result = patch_profile_dataset_row(profile, str(dataset.key), row.id, {"name": None})

    assert result["row"]["data"]["name"] == ""
    row.refresh_from_db()
    assert row.data["name"] == ""

    mutation = dataset.mutations.get(mutation_type=DatasetMutationType.ROW_UPDATED)
    assert mutation.metadata == {
        "row_id": row.id,
        "row_number": 1,
        "changed_fields": ["name"],
        "field_changes": [
            {
                "field": "name",
                "before": "Ada",
                "after": "",
            }
        ],
        "value_changes_recorded": True,
        "index_changed": False,
    }


def test_dataset_relationship_api_creates_lists_resolves_and_enforces_rows(client, profile):
    people, messages = create_crm_datasets(profile)

    create_response = client.post(
        f"/api/datasets/{messages.key}/relationships?api_key={profile.key}",
        data={
            "name": "Message person",
            "source_column": "person_id",
            "target_dataset_key": str(people.key),
            "enforce_integrity": True,
        },
        content_type="application/json",
    )

    assert create_response.status_code == 201
    relationship_payload = create_response.json()["relationship"]
    relationship_key = relationship_payload["key"]
    assert relationship_payload["source_column"] == "person_id"
    assert relationship_payload["target_dataset"]["key"] == str(people.key)
    assert relationship_payload["target_index_column"] == "person_id"
    assert relationship_payload["enforce_integrity"] is True
    relationship = DatasetRelationship.objects.get(key=relationship_key)
    assert relationship.source_dataset == messages
    assert relationship.target_dataset == people

    list_response = client.get(f"/api/datasets/{messages.key}/relationships?api_key={profile.key}")
    assert list_response.status_code == 200
    assert [item["key"] for item in list_response.json()["relationships"]] == [relationship_key]

    resolve_response = client.get(
        f"/api/datasets/{messages.key}/relationships/{relationship_key}/resolve"
        f"?api_key={profile.key}&source_index_value=M-1"
    )
    assert resolve_response.status_code == 200
    assert resolve_response.json()["target_index_value"] == "P-1"
    assert resolve_response.json()["target_row"]["data"]["name"] == "Ada Lovelace"

    invalid_key_response = client.get(
        f"/api/datasets/{messages.key}/relationships/not-a-key/resolve"
        f"?api_key={profile.key}&source_index_value=M-1"
    )
    assert invalid_key_response.status_code == 400
    assert invalid_key_response.json()["detail"] == "Invalid relationship key."

    invalid_row_response = client.post(
        f"/api/datasets/{messages.key}/rows?api_key={profile.key}",
        data={
            "data": {
                "message_id": "M-2",
                "person_id": "P-404",
                "body": "Missing person.",
            }
        },
        content_type="application/json",
    )
    assert invalid_row_response.status_code == 400
    assert "references a missing row" in invalid_row_response.json()["detail"]
    assert messages.rows.filter(index_value="M-2").exists() is False

    blank_row_response = client.post(
        f"/api/datasets/{messages.key}/rows?api_key={profile.key}",
        data={
            "data": {
                "message_id": "M-2",
                "person_id": "",
                "body": "Unmatched message.",
            }
        },
        content_type="application/json",
    )
    assert blank_row_response.status_code == 200

    delete_response = client.delete(
        f"/api/datasets/{messages.key}/relationships/{relationship_key}?api_key={profile.key}"
    )
    assert delete_response.status_code == 200
    assert not DatasetRelationship.objects.filter(key=relationship_key).exists()
    delete_mutation = messages.mutations.get(mutation_type=DatasetMutationType.RELATIONSHIP_DELETED)
    assert delete_mutation.metadata["enforce_integrity"] is True


def test_dataset_relationship_api_rejects_existing_unmatched_values(client, profile):
    people, messages = create_crm_datasets(profile)
    messages.rows.create(
        row_number=2,
        index_value="M-2",
        data={
            "message_id": "M-2",
            "person_id": "P-404",
            "body": "Unmatched.",
        },
    )
    messages.row_count = 2
    messages.save(update_fields=["row_count"])

    response = client.post(
        f"/api/datasets/{messages.key}/relationships?api_key={profile.key}",
        data={
            "source_column": "person_id",
            "target_dataset_key": str(people.key),
            "enforce_integrity": True,
        },
        content_type="application/json",
    )

    assert response.status_code == 400
    assert "without a matching row" in response.json()["detail"]
    assert not DatasetRelationship.objects.filter(source_dataset=messages).exists()


def test_dataset_relationship_api_resolves_unenforced_orphan_as_null(client, profile):
    people, messages = create_crm_datasets(profile)
    messages.rows.create(
        row_number=2,
        index_value="M-2",
        data={
            "message_id": "M-2",
            "person_id": "P-404",
            "body": "Unmatched.",
        },
    )
    messages.row_count = 2
    messages.save(update_fields=["row_count"])
    create_response = client.post(
        f"/api/datasets/{messages.key}/relationships?api_key={profile.key}",
        data={
            "source_column": "person_id",
            "target_dataset_key": str(people.key),
            "enforce_integrity": False,
        },
        content_type="application/json",
    )
    assert create_response.status_code == 201
    relationship_key = create_response.json()["relationship"]["key"]

    resolve_response = client.get(
        f"/api/datasets/{messages.key}/relationships/{relationship_key}/resolve"
        f"?api_key={profile.key}&source_index_value=M-2"
    )

    assert resolve_response.status_code == 200
    assert resolve_response.json()["target_index_value"] == "P-404"
    assert resolve_response.json()["target_row"] is None


def test_dataset_relationship_api_blocks_target_row_delete_when_enforced(client, profile):
    people, messages = create_crm_datasets(profile)
    messages.rows.filter(index_value="M-1").update(
        data={
            "message_id": "M-1",
            "person_id": " P-1 ",
            "body": "Intro call completed.",
        }
    )
    create_response = client.post(
        f"/api/datasets/{messages.key}/relationships?api_key={profile.key}",
        data={
            "source_column": "person_id",
            "target_dataset_key": str(people.key),
            "enforce_integrity": True,
        },
        content_type="application/json",
    )
    assert create_response.status_code == 201
    person_row = people.rows.get(index_value="P-1")

    delete_response = client.delete(
        f"/api/datasets/{people.key}/rows/{person_row.id}?api_key={profile.key}"
    )

    assert delete_response.status_code == 409
    assert "referenced by relationship" in delete_response.json()["detail"]
    assert people.rows.filter(index_value="P-1").exists()


def test_dataset_relationship_api_blocks_target_index_change_when_enforced(client, profile):
    people, messages = create_crm_datasets(profile)
    create_response = client.post(
        f"/api/datasets/{messages.key}/relationships?api_key={profile.key}",
        data={
            "source_column": "person_id",
            "target_dataset_key": str(people.key),
            "enforce_integrity": True,
        },
        content_type="application/json",
    )
    assert create_response.status_code == 201
    person_row = people.rows.get(index_value="P-1")

    patch_response = client.patch(
        f"/api/datasets/{people.key}/rows/{person_row.id}?api_key={profile.key}",
        data={
            "data": {
                "person_id": "P-2",
                "name": "Ada Lovelace",
                "email": "ada@example.com",
            }
        },
        content_type="application/json",
    )

    assert patch_response.status_code == 409
    assert "referenced by relationship" in patch_response.json()["detail"]
    person_row.refresh_from_db()
    assert person_row.index_value == "P-1"


def test_dataset_relationship_settings_form_creates_and_detail_shows_relationship(
    auth_client,
    profile,
):
    people, messages = create_crm_datasets(profile)

    response = auth_client.post(
        reverse("dataset_create_relationship", args=[messages.key]),
        data={
            "name": "Message person",
            "source_column": "person_id",
            "target_dataset_key": str(people.key),
            "enforce_integrity": "on",
        },
        follow=True,
    )

    assert response.status_code == 200
    assert DatasetRelationship.objects.filter(
        source_dataset=messages,
        target_dataset=people,
        source_column="person_id",
    ).exists()

    detail_response = auth_client.get(reverse("dataset_detail", args=[messages.key]))
    assert detail_response.status_code == 200
    content = detail_response.content.decode()
    details_match = re.search(
        r'<details\b[^>]*aria-labelledby="dataset-relationships-heading"[^>]*>',
        content,
    )
    assert details_match is not None
    assert not re.search(r"\sopen(?:[\s=>]|$)", details_match.group(0))
    assert "Show relationships" in content
    assert "Hide relationships" in content
    assert "Message person" in content
    assert f'href="{people.get_absolute_url()}"' in content
    assert "People</a>.person_id" in content
    assert "No incoming relationships." not in content

    incoming_response = auth_client.get(reverse("dataset_detail", args=[people.key]))
    incoming_content = incoming_response.content.decode()
    assert incoming_response.status_code == 200
    assert f'href="{messages.get_absolute_url()}"' in incoming_content
    assert "CRM Messages</a>.person_id" in incoming_content
    assert "No outgoing relationships." not in incoming_content


def test_normalize_column_schema_accepts_choice_metadata():
    schema = normalize_column_schema(
        ["status"],
        {
            "status": {
                "type": "choice",
                "choices": ["Ready to do", "Doing", "Done"],
            }
        },
        reject_unknown=True,
    )

    assert schema == {
        "status": {
            "type": "choice",
            "choices": ["Ready to do", "Doing", "Done"],
        }
    }


def test_normalize_column_schema_accepts_description_metadata():
    schema = normalize_column_schema(
        ["email", "price"],
        {
            "email": {
                "type": "email",
                "description": " Primary customer contact address. ",
            },
            "price": {"description": " Current retail price in USD. "},
        },
        fallback_schema={
            "email": {"type": "text"},
            "price": {"type": "currency"},
        },
        reject_unknown=True,
    )

    assert schema == {
        "email": {
            "type": "email",
            "description": "Primary customer contact address.",
        },
        "price": {
            "type": "currency",
            "description": "Current retail price in USD.",
        },
    }


def test_normalize_column_schema_accepts_dataset_reference_metadata():
    schema = normalize_column_schema(
        ["task_dataset"],
        {
            "task_dataset": {
                "type": "reference",
                "target": "dataset",
                "description": "Detailed task dataset for this sprint.",
            }
        },
        reject_unknown=True,
    )

    assert schema == {
        "task_dataset": {
            "type": "reference",
            "target": "dataset",
            "description": "Detailed task dataset for this sprint.",
        }
    }


def test_normalize_column_schema_accepts_project_reference_metadata():
    schema = normalize_column_schema(
        ["owning_project"],
        {
            "owning_project": {
                "type": "reference",
                "target": "project",
                "description": "Project responsible for this row.",
            }
        },
        reject_unknown=True,
    )

    assert schema == {
        "owning_project": {
            "type": "reference",
            "target": "project",
            "description": "Project responsible for this row.",
        }
    }


def test_normalize_column_schema_infers_project_reference_alias_target():
    schema = normalize_column_schema(
        ["owning_project", "fallback_project"],
        {
            "owning_project": "project_reference",
            "fallback_project": {"type": "rowset_project"},
        },
        reject_unknown=True,
    )

    assert schema == {
        "owning_project": {
            "type": "reference",
            "target": "project",
        },
        "fallback_project": {
            "type": "reference",
            "target": "project",
        },
    }


def test_choice_constraints_from_normalized_schema_allows_none():
    assert choice_constraints_from_schema(["status"], None, normalized=True) == {}


def test_dataset_api_dataset_reference_columns_accept_archived_datasets(client, profile):
    target = create_ready_dataset(profile)
    target.name = "Review Gate First Implementation Tasks"
    target.archived_at = timezone.now()
    target.save(update_fields=["name", "archived_at"])

    response = client.post(
        f"/api/datasets?api_key={profile.key}",
        data={
            "name": "Review Gate Sprint History",
            "headers": ["sprint_id", "task_dataset"],
            "index_column": "sprint_id",
            "column_types": {
                "task_dataset": {
                    "type": "reference",
                    "target": "dataset",
                }
            },
            "rows": [
                {
                    "sprint_id": "RG-SPRINT-001",
                    "task_dataset": str(target.key),
                }
            ],
        },
        content_type="application/json",
    )

    assert response.status_code == 201
    dataset = Dataset.objects.get(key=response.json()["dataset"]["key"], profile=profile)
    row = dataset.rows.get(index_value="RG-SPRINT-001")
    assert row.data["task_dataset"] == str(target.key)

    payload = serialize_dataset_detail(dataset)
    reference = payload["dataset_references"]["task_dataset"][str(target.key)]
    assert reference["name"] == "Review Gate First Implementation Tasks"
    assert reference["archived_at"] == target.archived_at
    assert reference["row_count"] == 2


def test_dataset_api_dataset_reference_columns_reject_missing_datasets(client, profile):
    missing_key = "38698383-f515-4b60-b426-4f4ae3bc94ce"

    response = client.post(
        f"/api/datasets?api_key={profile.key}",
        data={
            "name": "Review Gate Sprint History",
            "headers": ["sprint_id", "task_dataset"],
            "index_column": "sprint_id",
            "column_types": {
                "task_dataset": {
                    "type": "reference",
                    "target": "dataset",
                }
            },
            "rows": [
                {
                    "sprint_id": "RG-SPRINT-001",
                    "task_dataset": missing_key,
                }
            ],
        },
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "Column 'task_dataset' references a dataset that does not exist or is not owned "
        "by this profile."
    )


def test_dataset_api_project_reference_columns_accept_archived_projects(client, profile):
    target = Project.objects.create(profile=profile, name="Review Gate")
    target.archived_at = timezone.now()
    target.save(update_fields=["archived_at"])

    response = client.post(
        f"/api/datasets?api_key={profile.key}",
        data={
            "name": "Review Gate Sprint History",
            "headers": ["sprint_id", "owning_project"],
            "index_column": "sprint_id",
            "column_types": {
                "owning_project": {
                    "type": "reference",
                    "target": "project",
                }
            },
            "rows": [
                {
                    "sprint_id": "RG-SPRINT-001",
                    "owning_project": str(target.key),
                }
            ],
        },
        content_type="application/json",
    )

    assert response.status_code == 201
    dataset = Dataset.objects.get(key=response.json()["dataset"]["key"], profile=profile)
    row = dataset.rows.get(index_value="RG-SPRINT-001")
    assert row.data["owning_project"] == str(target.key)

    payload = serialize_dataset_detail(dataset)
    reference = payload["project_references"]["owning_project"][str(target.key)]
    assert reference["name"] == "Review Gate"
    assert reference["archived_at"] == target.archived_at
    assert reference["dataset_count"] == 0


def test_dataset_api_project_reference_columns_reject_missing_projects(client, profile):
    missing_key = "38698383-f515-4b60-b426-4f4ae3bc94ce"

    response = client.post(
        f"/api/datasets?api_key={profile.key}",
        data={
            "name": "Review Gate Sprint History",
            "headers": ["sprint_id", "owning_project"],
            "index_column": "sprint_id",
            "column_types": {
                "owning_project": {
                    "type": "reference",
                    "target": "project",
                }
            },
            "rows": [
                {
                    "sprint_id": "RG-SPRINT-001",
                    "owning_project": missing_key,
                }
            ],
        },
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "Column 'owning_project' references a project that does not exist or is not owned "
        "by this profile."
    )


def test_dataset_api_project_reference_columns_reject_other_profile_projects(
    client,
    profile,
    django_user_model,
):
    other_user = django_user_model.objects.create_user(
        username="projectreferenceother",
        email="projectreferenceother@example.com",
        password="password123",
    )
    other_project = Project.objects.create(profile=other_user.profile, name="Other launch")
    source = Dataset.objects.create(
        profile=profile,
        name="Sprint history",
        original_filename="Created via API",
        file_type="api",
        status=DatasetStatus.READY,
        headers=["sprint_id", "owning_project"],
        column_schema={
            "sprint_id": {"type": DatasetColumnType.TEXT},
            "owning_project": {
                "type": DatasetColumnType.REFERENCE,
                "target": "project",
            },
        },
        index_column="sprint_id",
        row_count=0,
        confirmed_at=timezone.now(),
        processed_at=timezone.now(),
    )

    response = client.post(
        f"/api/datasets/{source.key}/rows?api_key={profile.key}",
        data={
            "data": {
                "sprint_id": "RG-SPRINT-001",
                "owning_project": str(other_project.key),
            }
        },
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "Column 'owning_project' references a project that does not exist or is not owned "
        "by this profile."
    )
    assert not source.rows.exists()


def test_dataset_api_dataset_reference_columns_canonicalize_row_writes(client, profile):
    target = create_ready_dataset(profile)
    source = Dataset.objects.create(
        profile=profile,
        name="Sprint history",
        original_filename="Created via API",
        file_type="api",
        status=DatasetStatus.READY,
        headers=["sprint_id", "task_dataset"],
        column_schema={
            "sprint_id": {"type": DatasetColumnType.TEXT},
            "task_dataset": {
                "type": DatasetColumnType.REFERENCE,
                "target": "dataset",
            },
        },
        index_column="sprint_id",
        row_count=0,
        confirmed_at=timezone.now(),
        processed_at=timezone.now(),
    )

    create_response = client.post(
        f"/api/datasets/{source.key}/rows?api_key={profile.key}",
        data={
            "data": {
                "sprint_id": "RG-SPRINT-001",
                "task_dataset": target.get_public_url(),
            }
        },
        content_type="application/json",
    )

    assert create_response.status_code == 200
    row = source.rows.get(index_value="RG-SPRINT-001")
    assert row.data["task_dataset"] == str(target.key)

    invalid_patch = client.patch(
        f"/api/datasets/{source.key}/rows/{row.id}?api_key={profile.key}",
        data={"data": {"task_dataset": "38698383-f515-4b60-b426-4f4ae3bc94ce"}},
        content_type="application/json",
    )

    assert invalid_patch.status_code == 400
    assert invalid_patch.json()["detail"] == (
        "Column 'task_dataset' references a dataset that does not exist or is not owned "
        "by this profile."
    )
    row.refresh_from_db()
    assert row.data["task_dataset"] == str(target.key)


def test_dataset_api_project_reference_columns_canonicalize_row_writes(client, profile):
    target = Project.objects.create(profile=profile, name="Launch")
    source = Dataset.objects.create(
        profile=profile,
        name="Sprint history",
        original_filename="Created via API",
        file_type="api",
        status=DatasetStatus.READY,
        headers=["sprint_id", "owning_project"],
        column_schema={
            "sprint_id": {"type": DatasetColumnType.TEXT},
            "owning_project": {
                "type": DatasetColumnType.REFERENCE,
                "target": "project",
            },
        },
        index_column="sprint_id",
        row_count=0,
        confirmed_at=timezone.now(),
        processed_at=timezone.now(),
    )

    create_response = client.post(
        f"/api/datasets/{source.key}/rows?api_key={profile.key}",
        data={
            "data": {
                "sprint_id": "RG-SPRINT-001",
                "owning_project": target.get_absolute_url(),
            }
        },
        content_type="application/json",
    )

    assert create_response.status_code == 200
    row = source.rows.get(index_value="RG-SPRINT-001")
    assert row.data["owning_project"] == str(target.key)

    invalid_patch = client.patch(
        f"/api/datasets/{source.key}/rows/{row.id}?api_key={profile.key}",
        data={"data": {"owning_project": "38698383-f515-4b60-b426-4f4ae3bc94ce"}},
        content_type="application/json",
    )

    assert invalid_patch.status_code == 400
    assert invalid_patch.json()["detail"] == (
        "Column 'owning_project' references a project that does not exist or is not owned "
        "by this profile."
    )
    row.refresh_from_db()
    assert row.data["owning_project"] == str(target.key)


def test_dataset_api_project_reference_index_canonicalizes_row_writes(client, profile):
    target = Project.objects.create(profile=profile, name="Launch")
    source = Dataset.objects.create(
        profile=profile,
        name="Sprint history",
        original_filename="Created via API",
        file_type="api",
        status=DatasetStatus.READY,
        headers=["owning_project", "sprint_id"],
        column_schema={
            "owning_project": {
                "type": DatasetColumnType.REFERENCE,
                "target": "project",
            },
            "sprint_id": {"type": DatasetColumnType.TEXT},
        },
        index_column="owning_project",
        row_count=0,
        confirmed_at=timezone.now(),
        processed_at=timezone.now(),
    )

    response = client.post(
        f"/api/datasets/{source.key}/rows?api_key={profile.key}",
        data={
            "data": {
                "owning_project": target.get_absolute_url(),
                "sprint_id": "RG-SPRINT-001",
            }
        },
        content_type="application/json",
    )

    assert response.status_code == 200
    row = source.rows.get()
    assert row.index_value == str(target.key)
    assert row.data["owning_project"] == str(target.key)


def test_dataset_api_enforces_choice_values(client, profile):
    create_response = client.post(
        f"/api/datasets?api_key={profile.key}",
        data={
            "name": "Task board",
            "headers": ["task_id", "status", "title"],
            "index_column": "task_id",
            "column_types": {
                "status": {
                    "type": "choice",
                    "choices": ["Ready to do", "Doing", "Done"],
                }
            },
            "rows": [
                {
                    "task_id": "T-1",
                    "status": "Ready to do",
                    "title": "Draft API docs",
                }
            ],
        },
        content_type="application/json",
    )

    assert create_response.status_code == 201
    dataset = Dataset.objects.get(key=create_response.json()["dataset"]["key"], profile=profile)
    assert create_response.json()["dataset"]["column_schema"]["status"] == {
        "type": "choice",
        "choices": ["Ready to do", "Doing", "Done"],
    }
    assert dataset.column_schema["status"] == {
        "type": "choice",
        "choices": ["Ready to do", "Doing", "Done"],
    }

    invalid_create = client.post(
        f"/api/datasets/{dataset.key}/rows?api_key={profile.key}",
        data={
            "data": {
                "task_id": "T-2",
                "status": "Blocked",
                "title": "Ship choice columns",
            }
        },
        content_type="application/json",
    )

    assert invalid_create.status_code == 400
    assert invalid_create.json()["detail"] == (
        "Column 'status' must be blank or one of: Ready to do, Doing, Done."
    )
    assert dataset.rows.filter(index_value="T-2").exists() is False

    valid_create = client.post(
        f"/api/datasets/{dataset.key}/rows?api_key={profile.key}",
        data={
            "data": {
                "task_id": "T-2",
                "status": "doing",
                "title": "Ship choice columns",
            }
        },
        content_type="application/json",
    )

    assert valid_create.status_code == 200
    assert valid_create.json()["row"]["data"]["status"] == "Doing"

    row = dataset.rows.get(index_value="T-1")
    invalid_patch = client.patch(
        f"/api/datasets/{dataset.key}/rows/{row.id}?api_key={profile.key}",
        data={"data": {"status": "Blocked"}},
        content_type="application/json",
    )

    assert invalid_patch.status_code == 400
    assert invalid_patch.json()["detail"] == (
        "Column 'status' must be blank or one of: Ready to do, Doing, Done."
    )
    row.refresh_from_db()
    assert row.data["status"] == "Ready to do"

    valid_patch = client.patch(
        f"/api/datasets/{dataset.key}/rows/{row.id}?api_key={profile.key}",
        data={"data": {"status": " done "}},
        content_type="application/json",
    )

    assert valid_patch.status_code == 200
    assert valid_patch.json()["row"]["data"]["status"] == "Done"

    enum_style_patch = client.patch(
        f"/api/datasets/{dataset.key}/rows/{row.id}?api_key={profile.key}",
        data={"data": {"status": "_ready_to_do-"}},
        content_type="application/json",
    )

    assert enum_style_patch.status_code == 200
    assert enum_style_patch.json()["row"]["data"]["status"] == "Ready to do"


def test_dataset_api_rejects_choice_column_without_choices(client, profile):
    response = client.post(
        f"/api/datasets?api_key={profile.key}",
        data={
            "name": "Task board",
            "headers": ["task_id", "status"],
            "index_column": "task_id",
            "column_types": {"status": {"type": "choice", "choices": []}},
            "rows": [{"task_id": "T-1", "status": "Ready to do"}],
        },
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Choice column 'status' requires at least one choice."


def test_dataset_api_rejects_existing_values_when_setting_choice_schema(client, profile):
    dataset = create_ready_dataset(profile)

    response = client.patch(
        f"/api/datasets/{dataset.key}/column-types?api_key={profile.key}",
        data={
            "column_types": {
                "name": {
                    "type": "choice",
                    "choices": ["Ada"],
                }
            }
        },
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "Column 'name' has existing values outside the allowed choices: Grace."
    )


def test_dataset_api_choice_schema_ignores_stale_preview_rows(client, profile):
    dataset = create_ready_dataset(profile)
    row = dataset.rows.get(index_value="ada@example.com")

    patch_response = client.patch(
        f"/api/datasets/{dataset.key}/rows/{row.id}?api_key={profile.key}",
        data={"data": {"name": "Ada Lovelace"}},
        content_type="application/json",
    )
    assert patch_response.status_code == 200

    dataset.refresh_from_db()
    assert dataset.preview_rows == [{"name": "Ada", "email": "ada@example.com"}]
    assert dataset.rows.get(index_value="ada@example.com").data["name"] == "Ada Lovelace"

    response = client.patch(
        f"/api/datasets/{dataset.key}/column-types?api_key={profile.key}",
        data={
            "column_types": {
                "name": {
                    "type": "choice",
                    "choices": ["Ada Lovelace", "Grace"],
                }
            }
        },
        content_type="application/json",
    )

    assert response.status_code == 200
    assert response.json()["dataset"]["column_schema"]["name"] == {
        "type": "choice",
        "choices": ["Ada Lovelace", "Grace"],
    }


def test_dataset_api_adds_choice_column_and_validates_default(client, profile):
    dataset = create_ready_dataset(profile)

    response = client.post(
        f"/api/datasets/{dataset.key}/columns?api_key={profile.key}",
        data={
            "name": "visibility_level",
            "default_value": " shared ",
            "column_type": {
                "type": "choice",
                "choices": ["internal", "shared"],
            },
        },
        content_type="application/json",
    )

    assert response.status_code == 200
    assert response.json()["dataset"]["column_schema"]["visibility_level"] == {
        "type": "choice",
        "choices": ["internal", "shared"],
    }
    dataset.refresh_from_db()
    assert dataset.column_schema["visibility_level"] == {
        "type": "choice",
        "choices": ["internal", "shared"],
    }
    assert list(dataset.rows.values_list("data", flat=True)) == [
        {"name": "Ada", "email": "ada@example.com", "visibility_level": "shared"},
        {"name": "Grace", "email": "grace@example.com", "visibility_level": "shared"},
    ]

    invalid_response = client.post(
        f"/api/datasets/{dataset.key}/columns?api_key={profile.key}",
        data={
            "name": "workflow_state",
            "default_value": "blocked",
            "column_type": {
                "type": "choice",
                "choices": ["ready", "done"],
            },
        },
        content_type="application/json",
    )

    assert invalid_response.status_code == 400
    assert invalid_response.json()["detail"] == (
        "Column 'workflow_state' must be blank or one of: ready, done."
    )


def test_project_api_creates_lists_and_returns_project_datasets(client, profile):
    create_project_response = client.post(
        f"/api/projects?api_key={profile.key}",
        data={
            "name": "Launch",
            "description": "Launch datasets",
            "metadata": {
                "github_repo": "https://github.com/acme/launch",
                "source_thread": {
                    "url": "https://acme.slack.com/archives/C123/p456",
                },
            },
        },
        content_type="application/json",
    )

    assert create_project_response.status_code == 201
    project_key = create_project_response.json()["project"]["key"]
    assert create_project_response.json()["project"]["metadata"] == {
        "github_repo": "https://github.com/acme/launch",
        "source_thread": {
            "url": "https://acme.slack.com/archives/C123/p456",
        },
    }

    create_dataset_response = client.post(
        f"/api/datasets?api_key={profile.key}",
        data={
            "name": "Launch contacts",
            "project_key": project_key,
            "headers": ["email", "name"],
            "index_column": "email",
            "rows": [{"email": "ada@example.com", "name": "Ada"}],
        },
        content_type="application/json",
    )

    assert create_dataset_response.status_code == 201
    assert create_dataset_response.json()["dataset"]["project"]["key"] == project_key
    project = Project.objects.get(key=project_key, profile=profile)
    Dataset.objects.create(
        profile=profile,
        project=project,
        name="Draft upload",
        original_filename="draft.csv",
        status=DatasetStatus.PREVIEWED,
        headers=["email", "name"],
        index_column="email",
    )

    list_response = client.get(f"/api/projects?api_key={profile.key}")
    assert list_response.status_code == 200
    assert list_response.json()["projects"][0]["dataset_count"] == 1
    assert list_response.json()["projects"][0]["metadata"]["github_repo"] == (
        "https://github.com/acme/launch"
    )

    detail_response = client.get(f"/api/projects/{project_key}?api_key={profile.key}")
    assert detail_response.status_code == 200
    assert detail_response.json()["project"]["name"] == "Launch"
    assert detail_response.json()["project"]["metadata"]["source_thread"]["url"] == (
        "https://acme.slack.com/archives/C123/p456"
    )
    assert detail_response.json()["datasets"]["count"] == 1
    assert detail_response.json()["datasets"]["total_count"] == 1
    assert detail_response.json()["datasets"]["datasets"][0]["name"] == "Launch contacts"
    assert [dataset["name"] for dataset in detail_response.json()["datasets"]["datasets"]] == [
        "Launch contacts"
    ]


def test_project_api_updates_project_details(client, profile):
    project = Project.objects.create(
        profile=profile,
        name="Launch",
        description="Launch datasets",
    )

    response = client.patch(
        f"/api/projects/{project.key}?api_key={profile.key}",
        data={"name": "Launch operations", "description": ""},
        content_type="application/json",
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["message"] == "Project updated."
    assert payload["project"]["name"] == "Launch operations"
    assert payload["project"]["description"] == ""
    project.refresh_from_db()
    assert project.name == "Launch operations"
    assert project.description == ""


def test_project_api_archives_project_and_hides_it_from_project_endpoints(client, profile):
    project = Project.objects.create(
        profile=profile,
        name="Launch",
        description="Launch datasets",
    )
    dataset = Dataset.objects.create(
        profile=profile,
        project=project,
        name="Launch contacts",
        original_filename="launch.csv",
        status=DatasetStatus.READY,
        headers=["email", "name"],
        index_column="email",
    )

    response = client.delete(f"/api/projects/{project.key}?api_key={profile.key}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["message"] == "Project archived."
    assert payload["project"]["key"] == str(project.key)
    assert payload["project"]["archived_at"] is not None
    project.refresh_from_db()
    assert project.archived_at is not None
    dataset.refresh_from_db()
    assert dataset.archived_at is None
    assert dataset.project == project

    list_response = client.get(f"/api/projects?api_key={profile.key}")
    assert list_response.status_code == 200
    assert list_response.json()["projects"] == []

    search_response = client.get(f"/api/projects?query=Launch&api_key={profile.key}")
    assert search_response.status_code == 200
    assert search_response.json()["projects"] == []

    detail_response = client.get(f"/api/projects/{project.key}?api_key={profile.key}")
    assert detail_response.status_code == 404
    assert detail_response.json()["detail"] == "Project not found."

    dataset_list_response = client.get(f"/api/datasets?api_key={profile.key}")
    assert dataset_list_response.status_code == 200
    assert dataset_list_response.json()["datasets"][0]["key"] == str(dataset.key)
    assert dataset_list_response.json()["datasets"][0]["project"] is None

    duplicate_name_response = client.post(
        f"/api/projects?api_key={profile.key}",
        data={"name": "Launch"},
        content_type="application/json",
    )
    assert duplicate_name_response.status_code == 201


def test_project_api_rejects_null_project_name(client, profile):
    project = Project.objects.create(
        profile=profile,
        name="Launch",
        description="Launch datasets",
    )

    response = client.patch(
        f"/api/projects/{project.key}?api_key={profile.key}",
        data={"name": None},
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "Project name cannot be null. Omit it to leave the current value unchanged."
    )
    project.refresh_from_db()
    assert project.name == "Launch"


def test_project_api_rejects_blank_project_name_at_schema_boundary(client, profile):
    project = Project.objects.create(
        profile=profile,
        name="Launch",
        description="Launch datasets",
    )

    response = client.patch(
        f"/api/projects/{project.key}?api_key={profile.key}",
        data={"name": ""},
        content_type="application/json",
    )

    assert response.status_code == 422
    project.refresh_from_db()
    assert project.name == "Launch"


def test_project_api_rejects_case_insensitive_duplicate_names(client, profile):
    Project.objects.create(profile=profile, name="Launch")

    response = client.post(
        f"/api/projects?api_key={profile.key}",
        data={"name": "launch"},
        content_type="application/json",
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Project name already exists."
    assert Project.objects.filter(profile=profile).count() == 1


def test_project_api_updates_project_metadata(client, profile):
    project = Project.objects.create(
        profile=profile,
        name="Launch",
        metadata={"github_repo": "https://github.com/acme/old"},
    )

    response = client.patch(
        f"/api/projects/{project.key}/metadata?api_key={profile.key}",
        data={
            "metadata": {
                "github_repo": "https://github.com/acme/launch",
                "notion_doc": "https://notion.so/acme/launch",
            }
        },
        content_type="application/json",
    )

    assert response.status_code == 200
    assert response.json()["message"] == "Project metadata updated."
    assert response.json()["project"]["metadata"] == {
        "github_repo": "https://github.com/acme/launch",
        "notion_doc": "https://notion.so/acme/launch",
    }
    project.refresh_from_db()
    assert project.metadata == {
        "github_repo": "https://github.com/acme/launch",
        "notion_doc": "https://notion.so/acme/launch",
    }


def test_project_api_rejects_non_object_project_metadata(client, profile):
    project = Project.objects.create(profile=profile, name="Launch")

    response = client.patch(
        f"/api/projects/{project.key}/metadata?api_key={profile.key}",
        data={"metadata": ["not", "an", "object"]},
        content_type="application/json",
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "payload", "metadata"]
    project.refresh_from_db()
    assert project.metadata == {}


def test_project_api_rejects_null_project_metadata(client, profile):
    project = Project.objects.create(profile=profile, name="Launch")

    response = client.patch(
        f"/api/projects/{project.key}/metadata?api_key={profile.key}",
        data={"metadata": None},
        content_type="application/json",
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "payload", "metadata"]
    project.refresh_from_db()
    assert project.metadata == {}


def test_dataset_api_updates_project_assignment(client, profile):
    project = Project.objects.create(profile=profile, name="Customers")
    dataset = create_ready_dataset(profile)

    attach_response = client.patch(
        f"/api/datasets/{dataset.key}/project?api_key={profile.key}",
        data={"project_key": str(project.key)},
        content_type="application/json",
    )

    assert attach_response.status_code == 200
    assert attach_response.json()["dataset"]["project"]["key"] == str(project.key)
    dataset.refresh_from_db()
    assert dataset.project == project

    detach_response = client.patch(
        f"/api/datasets/{dataset.key}/project?api_key={profile.key}",
        data={"project_key": None},
        content_type="application/json",
    )

    assert detach_response.status_code == 200
    assert detach_response.json()["dataset"]["project"] is None
    dataset.refresh_from_db()
    assert dataset.project is None


def test_project_section_api_creates_section_and_assigns_dataset(client, profile):
    assert hasattr(dataset_models, "ProjectSection")
    project = Project.objects.create(profile=profile, name="Rowset")

    section_response = client.post(
        f"/api/projects/{project.key}/sections?api_key={profile.key}",
        data={
            "name": "Blog",
            "description": "Content operations datasets.",
            "metadata": {"goal": "content-led growth"},
        },
        content_type="application/json",
    )

    assert section_response.status_code == 201
    section_payload = section_response.json()["section"]
    assert section_payload["name"] == "Blog"
    assert section_payload["description"] == "Content operations datasets."
    assert section_payload["metadata"] == {"goal": "content-led growth"}
    assert section_payload["dataset_count"] == 0

    dataset_response = client.post(
        f"/api/datasets?api_key={profile.key}",
        data={
            "name": "Content ledger",
            "headers": ["slug", "status"],
            "rows": [{"slug": "launch-post", "status": "draft"}],
            "index_column": "slug",
            "project_key": str(project.key),
            "section_key": section_payload["key"],
        },
        content_type="application/json",
    )

    assert dataset_response.status_code == 201
    dataset_payload = dataset_response.json()["dataset"]
    assert dataset_payload["project"]["key"] == str(project.key)
    assert dataset_payload["section"]["key"] == section_payload["key"]
    assert dataset_payload["section"]["name"] == "Blog"

    detail_response = client.get(f"/api/projects/{project.key}?api_key={profile.key}")

    assert detail_response.status_code == 200
    detail_payload = detail_response.json()
    assert detail_payload["sections"][0]["key"] == section_payload["key"]
    assert detail_payload["sections"][0]["dataset_count"] == 1
    assert detail_payload["dataset_groups"][0]["label"] == "Blog"
    assert detail_payload["dataset_groups"][0]["section"]["key"] == section_payload["key"]
    assert detail_payload["dataset_groups"][0]["datasets"]["count"] == 1
    assert detail_payload["dataset_groups"][0]["datasets"]["total_count"] == 1
    assert "limit" not in detail_payload["dataset_groups"][0]["datasets"]
    assert "offset" not in detail_payload["dataset_groups"][0]["datasets"]
    assert "has_more" not in detail_payload["dataset_groups"][0]["datasets"]
    assert (
        detail_payload["dataset_groups"][0]["datasets"]["datasets"][0]["key"]
        == (dataset_payload["key"])
    )


def test_dataset_api_rejects_section_from_another_project(client, profile):
    assert hasattr(dataset_models, "ProjectSection")
    ProjectSection = dataset_models.ProjectSection
    project = Project.objects.create(profile=profile, name="Rowset")
    other_project = Project.objects.create(profile=profile, name="Other")
    section = ProjectSection.objects.create(
        profile=profile,
        project=other_project,
        name="Blog",
    )
    dataset = create_ready_dataset(profile)

    response = client.patch(
        f"/api/datasets/{dataset.key}/project?api_key={profile.key}",
        data={"project_key": str(project.key), "section_key": str(section.key)},
        content_type="application/json",
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Project section not found."
    dataset.refresh_from_db()
    assert dataset.project is None
    assert dataset.section is None


def test_project_section_api_archives_section_and_unsections_datasets(client, profile):
    assert hasattr(dataset_models, "ProjectSection")
    ProjectSection = dataset_models.ProjectSection
    project = Project.objects.create(profile=profile, name="Rowset")
    section = ProjectSection.objects.create(profile=profile, project=project, name="Blog")
    dataset = create_ready_dataset(profile)
    dataset.project = project
    dataset.section = section
    dataset.save(update_fields=["project", "section"])

    response = client.delete(
        f"/api/projects/{project.key}/sections/{section.key}?api_key={profile.key}"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["message"] == "Project section archived."
    assert payload["section"]["key"] == str(section.key)
    assert payload["section"]["archived_at"] is not None
    section.refresh_from_db()
    assert section.archived_at is not None
    dataset.refresh_from_db()
    assert dataset.project == project
    assert dataset.section is None

    list_response = client.get(f"/api/projects/{project.key}/sections?api_key={profile.key}")

    assert list_response.status_code == 200
    assert list_response.json()["sections"] == []


def test_project_detail_api_reports_unsectioned_total_count_on_paginated_page(client, profile):
    project = Project.objects.create(profile=profile, name="Rowset")
    first = create_ready_dataset(profile)
    first.name = "Signals"
    first.project = project
    first.save(update_fields=["name", "project"])
    second = create_ready_dataset(profile)
    second.name = "Inventory"
    second.project = project
    second.save(update_fields=["name", "project"])

    response = client.get(f"/api/projects/{project.key}?api_key={profile.key}&limit=1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["datasets"]["count"] == 1
    assert payload["datasets"]["total_count"] == 2
    assert payload["dataset_groups"][0]["label"] == "Unsectioned"
    assert payload["dataset_groups"][0]["dataset_count"] == 2
    assert payload["dataset_groups"][0]["datasets"]["count"] == 1
    assert payload["dataset_groups"][0]["datasets"]["total_count"] == 2
    assert payload["dataset_groups"][0]["datasets"]["datasets"][0]["key"] == str(second.key)


def test_project_detail_api_includes_empty_page_unsectioned_group(client, profile):
    assert hasattr(dataset_models, "ProjectSection")
    ProjectSection = dataset_models.ProjectSection
    project = Project.objects.create(profile=profile, name="Rowset")
    blog = ProjectSection.objects.create(profile=profile, project=project, name="Blog")
    first = create_ready_dataset(profile)
    first.name = "Signals"
    first.project = project
    first.save(update_fields=["name", "project"])
    second = create_ready_dataset(profile)
    second.name = "Inventory"
    second.project = project
    second.save(update_fields=["name", "project"])
    sectioned = create_ready_dataset(profile)
    sectioned.name = "Content ledger"
    sectioned.project = project
    sectioned.section = blog
    sectioned.save(update_fields=["name", "project", "section"])

    response = client.get(f"/api/projects/{project.key}?api_key={profile.key}&limit=1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["datasets"]["count"] == 1
    assert payload["datasets"]["datasets"][0]["key"] == str(sectioned.key)
    assert payload["dataset_groups"][0]["label"] == "Blog"
    assert payload["dataset_groups"][0]["dataset_count"] == 1
    assert payload["dataset_groups"][0]["datasets"]["count"] == 1
    assert payload["dataset_groups"][1]["label"] == "Unsectioned"
    assert payload["dataset_groups"][1]["dataset_count"] == 2
    assert payload["dataset_groups"][1]["datasets"]["count"] == 0
    assert payload["dataset_groups"][1]["datasets"]["total_count"] == 2
    assert payload["dataset_groups"][1]["datasets"]["datasets"] == []


def test_dataset_api_rejects_invalid_project_assignment_dataset_key(client, profile):
    project = Project.objects.create(profile=profile, name="Customers")

    response = client.patch(
        f"/api/datasets/not-a-uuid/project?api_key={profile.key}",
        data={"project_key": str(project.key)},
        content_type="application/json",
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Dataset not found."


def test_dataset_api_rejects_other_users_project_assignment(client, django_user_model, profile):
    dataset = create_ready_dataset(profile)
    other_user = django_user_model.objects.create_user(
        username="project-owner",
        email="project-owner@example.com",
        password="password123",
    )
    other_project = Project.objects.create(profile=other_user.profile, name="Other")

    response = client.patch(
        f"/api/datasets/{dataset.key}/project?api_key={profile.key}",
        data={"project_key": str(other_project.key)},
        content_type="application/json",
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Project not found."
    dataset.refresh_from_db()
    assert dataset.project is None


def test_dataset_api_updates_dataset_metadata(client, profile):
    dataset = create_ready_dataset(profile)
    dataset.description = "Initial task board."
    dataset.instructions = "Use todo, doing, and done."
    dataset.metadata = {"status_order": ["todo", "doing", "done"]}
    dataset.save(update_fields=["description", "instructions", "metadata"])

    response = client.patch(
        f"/api/datasets/{dataset.key}/metadata?api_key={profile.key}",
        data={
            "description": "Agent task board for launch work.",
            "instructions": (
                "Keep the priority field stable. Move blocked tasks back to todo "
                "after the blocker is removed."
            ),
            "metadata": {
                "status_order": ["todo", "blocked", "doing", "done"],
                "default_assignee": "agent",
            },
        },
        content_type="application/json",
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["message"] == "Dataset metadata updated."
    assert payload["dataset"]["description"] == "Agent task board for launch work."
    assert payload["dataset"]["instructions"] == (
        "Keep the priority field stable. Move blocked tasks back to todo "
        "after the blocker is removed."
    )
    assert payload["dataset"]["metadata"] == {
        "status_order": ["todo", "blocked", "doing", "done"],
        "default_assignee": "agent",
    }
    dataset.refresh_from_db()
    assert dataset.description == "Agent task board for launch work."
    assert dataset.instructions == (
        "Keep the priority field stable. Move blocked tasks back to todo "
        "after the blocker is removed."
    )
    assert dataset.metadata == {
        "status_order": ["todo", "blocked", "doing", "done"],
        "default_assignee": "agent",
    }
    mutation = dataset.mutations.get(mutation_type=DatasetMutationType.DATASET_METADATA_UPDATED)
    assert mutation.metadata["previous"] == {
        "description": "Initial task board.",
        "instructions": "Use todo, doing, and done.",
        "metadata": {"status_order": ["todo", "doing", "done"]},
    }
    assert mutation.metadata["current"] == {
        "description": "Agent task board for launch work.",
        "instructions": (
            "Keep the priority field stable. Move blocked tasks back to todo "
            "after the blocker is removed."
        ),
        "metadata": {
            "status_order": ["todo", "blocked", "doing", "done"],
            "default_assignee": "agent",
        },
    }
    assert mutation.metadata["changed_fields"] == [
        "description",
        "instructions",
        "metadata",
    ]


def test_dataset_api_rejects_non_object_dataset_metadata(client, profile):
    dataset = create_ready_dataset(profile)

    response = client.patch(
        f"/api/datasets/{dataset.key}/metadata?api_key={profile.key}",
        data={"metadata": ["not", "an", "object"]},
        content_type="application/json",
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "payload", "metadata"]
    dataset.refresh_from_db()
    assert dataset.metadata == {}


def test_dataset_api_treats_null_dataset_metadata_fields_as_omitted(client, profile):
    dataset = create_ready_dataset(profile)
    dataset.description = "Initial task board."
    dataset.instructions = "Use todo, doing, and done."
    dataset.metadata = {"status_order": ["todo", "doing", "done"]}
    dataset.save(update_fields=["description", "instructions", "metadata"])

    response = client.patch(
        f"/api/datasets/{dataset.key}/metadata?api_key={profile.key}",
        data={
            "description": None,
            "instructions": "Keep status transitions explicit.",
            "metadata": None,
        },
        content_type="application/json",
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["dataset"]["description"] == "Initial task board."
    assert payload["dataset"]["instructions"] == "Keep status transitions explicit."
    assert payload["dataset"]["metadata"] == {"status_order": ["todo", "doing", "done"]}
    dataset.refresh_from_db()
    assert dataset.description == "Initial task board."
    assert dataset.instructions == "Keep status transitions explicit."
    assert dataset.metadata == {"status_order": ["todo", "doing", "done"]}
    mutation = dataset.mutations.get(mutation_type=DatasetMutationType.DATASET_METADATA_UPDATED)
    assert mutation.metadata["changed_fields"] == ["instructions"]


def test_dataset_api_reports_no_dataset_metadata_changes(client, profile):
    dataset = create_ready_dataset(profile)
    dataset.description = "Initial task board."
    dataset.instructions = "Use todo, doing, and done."
    dataset.metadata = {"status_order": ["todo", "doing", "done"]}
    dataset.save(update_fields=["description", "instructions", "metadata"])

    response = client.patch(
        f"/api/datasets/{dataset.key}/metadata?api_key={profile.key}",
        data={
            "description": "Initial task board.",
            "instructions": "Use todo, doing, and done.",
            "metadata": {"status_order": ["todo", "doing", "done"]},
        },
        content_type="application/json",
    )

    assert response.status_code == 200
    assert response.json()["message"] == "No dataset metadata changes detected."
    assert not dataset.mutations.filter(
        mutation_type=DatasetMutationType.DATASET_METADATA_UPDATED
    ).exists()


def test_dataset_api_updates_column_types(client, profile):
    dataset = create_ready_dataset(profile)

    response = client.patch(
        f"/api/datasets/{dataset.key}/column-types?api_key={profile.key}",
        data={
            "column_types": {
                "email": {
                    "type": "text",
                    "description": "Primary contact email for row lookup.",
                },
                "name": {"description": "Human-readable full name."},
            }
        },
        content_type="application/json",
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["dataset"]["column_schema"] == {
        "name": {
            "type": "text",
            "description": "Human-readable full name.",
        },
        "email": {
            "type": "text",
            "description": "Primary contact email for row lookup.",
        },
    }
    dataset.refresh_from_db()
    assert dataset.column_schema == {
        "name": {
            "type": "text",
            "description": "Human-readable full name.",
        },
        "email": {
            "type": "text",
            "description": "Primary contact email for row lookup.",
        },
    }


def test_dataset_api_updates_column_types_to_project_reference(client, profile):
    target = Project.objects.create(profile=profile, name="Launch")
    dataset = Dataset.objects.create(
        profile=profile,
        name="Sprint history",
        original_filename="Created via API",
        file_type="api",
        status=DatasetStatus.READY,
        headers=["sprint_id", "owning_project"],
        column_schema={
            "sprint_id": {"type": DatasetColumnType.TEXT},
            "owning_project": {"type": DatasetColumnType.TEXT},
        },
        index_column="sprint_id",
        row_count=1,
        confirmed_at=timezone.now(),
        processed_at=timezone.now(),
    )
    DatasetRow.objects.create(
        dataset=dataset,
        row_number=1,
        index_value="RG-SPRINT-001",
        data={
            "sprint_id": "RG-SPRINT-001",
            "owning_project": str(target.key),
        },
    )

    response = client.patch(
        f"/api/datasets/{dataset.key}/column-types?api_key={profile.key}",
        data={
            "column_types": {
                "owning_project": {
                    "type": "reference",
                    "target": "project",
                }
            }
        },
        content_type="application/json",
    )

    assert response.status_code == 200
    assert response.json()["dataset"]["column_schema"]["owning_project"] == {
        "type": "reference",
        "target": "project",
    }
    dataset.refresh_from_db()
    assert dataset.column_schema["owning_project"] == {
        "type": "reference",
        "target": "project",
    }


def test_dataset_api_rejects_project_reference_column_type_for_other_profile_value(
    client,
    profile,
    django_user_model,
):
    other_user = django_user_model.objects.create_user(
        username="projecttypeother",
        email="projecttypeother@example.com",
        password="password123",
    )
    other_project = Project.objects.create(profile=other_user.profile, name="Other launch")
    dataset = Dataset.objects.create(
        profile=profile,
        name="Sprint history",
        original_filename="Created via API",
        file_type="api",
        status=DatasetStatus.READY,
        headers=["sprint_id", "owning_project"],
        column_schema={
            "sprint_id": {"type": DatasetColumnType.TEXT},
            "owning_project": {"type": DatasetColumnType.TEXT},
        },
        index_column="sprint_id",
        row_count=1,
        confirmed_at=timezone.now(),
        processed_at=timezone.now(),
    )
    DatasetRow.objects.create(
        dataset=dataset,
        row_number=1,
        index_value="RG-SPRINT-001",
        data={
            "sprint_id": "RG-SPRINT-001",
            "owning_project": str(other_project.key),
        },
    )

    response = client.patch(
        f"/api/datasets/{dataset.key}/column-types?api_key={profile.key}",
        data={
            "column_types": {
                "owning_project": {
                    "type": "reference",
                    "target": "project",
                }
            }
        },
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "Column 'owning_project' references a project that does not exist or is not owned "
        "by this profile."
    )
    dataset.refresh_from_db()
    assert dataset.column_schema["owning_project"] == {"type": DatasetColumnType.TEXT}


def test_dataset_api_rejects_image_type_for_unowned_existing_asset_ref(client, profile):
    dataset = create_ready_dataset(profile)
    dataset.headers = ["name", "email", "photo"]
    dataset.save(update_fields=["headers", "updated_at"])
    row = dataset.rows.get(index_value="ada@example.com")
    row.data = {
        **row.data,
        "photo": "asset:00000000-0000-0000-0000-000000000000",
    }
    row.save(update_fields=["data", "updated_at"])

    response = client.patch(
        f"/api/datasets/{dataset.key}/column-types?api_key={profile.key}",
        data={"column_types": {"photo": "image"}},
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "Column 'photo' references an image asset that does not exist."
    )


def test_dataset_api_adds_column_and_backfills_existing_rows(client, profile):
    dataset = create_ready_dataset(profile)

    response = client.post(
        f"/api/datasets/{dataset.key}/columns?api_key={profile.key}",
        data={
            "name": "visibility_level",
            "default_value": "internal",
            "column_type": "text",
        },
        content_type="application/json",
    )

    assert response.status_code == 200
    assert response.json()["dataset"]["headers"] == ["name", "email", "visibility_level"]
    assert response.json()["dataset"]["column_schema"]["visibility_level"] == {"type": "text"}
    dataset.refresh_from_db()
    assert dataset.headers == ["name", "email", "visibility_level"]
    assert dataset.preview_rows == [
        {"name": "Ada", "email": "ada@example.com", "visibility_level": "internal"},
        {"name": "Grace", "email": "grace@example.com", "visibility_level": "internal"},
    ]
    assert list(dataset.rows.values_list("data", flat=True)) == [
        {"name": "Ada", "email": "ada@example.com", "visibility_level": "internal"},
        {"name": "Grace", "email": "grace@example.com", "visibility_level": "internal"},
    ]


def test_dataset_api_add_column_backfills_rows_across_bulk_update_chunks(client, profile):
    dataset = Dataset.objects.create(
        profile=profile,
        name="Large People",
        original_filename="large.csv",
        status=DatasetStatus.READY,
        headers=["email"],
        index_column="email",
        row_count=1001,
    )
    DatasetRow.objects.bulk_create(
        [
            DatasetRow(
                dataset=dataset,
                row_number=row_number,
                index_value=f"user-{row_number}@example.com",
                data={"email": f"user-{row_number}@example.com"},
            )
            for row_number in range(1, 1002)
        ]
    )

    response = client.post(
        f"/api/datasets/{dataset.key}/columns?api_key={profile.key}",
        data={"name": "verification_ref", "default_value": "pending"},
        content_type="application/json",
    )

    assert response.status_code == 200
    dataset.refresh_from_db()
    assert dataset.headers == ["email", "verification_ref"]
    assert dataset.preview_rows == [
        {"email": f"user-{row_number}@example.com", "verification_ref": "pending"}
        for row_number in range(1, 6)
    ]
    assert dataset.rows.get(row_number=1001).data == {
        "email": "user-1001@example.com",
        "verification_ref": "pending",
    }


def test_dataset_api_renames_column_and_preserves_values(client, profile):
    dataset = create_ready_dataset(profile)

    response = client.post(
        f"/api/datasets/{dataset.key}/columns/rename?api_key={profile.key}",
        data={"old_name": "name", "new_name": "full_name"},
        content_type="application/json",
    )

    assert response.status_code == 200
    assert response.json()["dataset"]["headers"] == ["full_name", "email"]
    dataset.refresh_from_db()
    assert dataset.headers == ["full_name", "email"]
    assert dataset.column_schema == {
        "full_name": {"type": "text"},
        "email": {"type": "text"},
    }
    assert dataset.rows.first().data == {
        "full_name": "Ada",
        "email": "ada@example.com",
    }


def test_dataset_api_schema_mutations_preserve_column_descriptions(client, profile):
    dataset = create_ready_dataset(profile)
    dataset.column_schema = {
        "name": {
            "type": "text",
            "description": "Person name used in greetings.",
        },
        "email": {
            "type": "email",
            "description": "Stable contact address and index value.",
        },
    }
    dataset.save(update_fields=["column_schema"])

    rename_response = client.post(
        f"/api/datasets/{dataset.key}/columns/rename?api_key={profile.key}",
        data={"old_name": "name", "new_name": "full_name"},
        content_type="application/json",
    )

    assert rename_response.status_code == 200
    assert rename_response.json()["dataset"]["column_schema"]["full_name"] == {
        "type": "text",
        "description": "Person name used in greetings.",
    }
    dataset.refresh_from_db()
    assert dataset.column_schema["full_name"] == {
        "type": "text",
        "description": "Person name used in greetings.",
    }

    reorder_response = client.post(
        f"/api/datasets/{dataset.key}/columns/reorder?api_key={profile.key}",
        data={"headers": ["email", "full_name"]},
        content_type="application/json",
    )

    assert reorder_response.status_code == 200
    dataset.refresh_from_db()
    assert dataset.column_schema == {
        "email": {
            "type": "email",
            "description": "Stable contact address and index value.",
        },
        "full_name": {
            "type": "text",
            "description": "Person name used in greetings.",
        },
    }

    drop_response = client.post(
        f"/api/datasets/{dataset.key}/columns/drop?api_key={profile.key}",
        data={"name": "full_name"},
        content_type="application/json",
    )

    assert drop_response.status_code == 200
    dataset.refresh_from_db()
    assert dataset.column_schema == {
        "email": {
            "type": "email",
            "description": "Stable contact address and index value.",
        }
    }


def test_dataset_api_rename_only_stringifies_renamed_value(client, profile):
    dataset = Dataset.objects.create(
        profile=profile,
        name="Mixed",
        original_filename="mixed.csv",
        status=DatasetStatus.READY,
        headers=["name", "email", "score"],
        index_column="email",
        row_count=1,
    )
    row = DatasetRow.objects.create(
        dataset=dataset,
        row_number=1,
        index_value="ada@example.com",
        data={"name": 10, "email": "ada@example.com", "score": 99},
    )

    response = client.post(
        f"/api/datasets/{dataset.key}/columns/rename?api_key={profile.key}",
        data={"old_name": "name", "new_name": "full_name"},
        content_type="application/json",
    )

    assert response.status_code == 200
    row.refresh_from_db()
    assert row.data == {
        "email": "ada@example.com",
        "score": 99,
        "full_name": "10",
    }


def test_dataset_api_drops_non_index_column(client, profile):
    dataset = create_ready_dataset(profile)

    response = client.post(
        f"/api/datasets/{dataset.key}/columns/drop?api_key={profile.key}",
        data={"name": "name"},
        content_type="application/json",
    )

    assert response.status_code == 200
    assert response.json()["dataset"]["headers"] == ["email"]
    dataset.refresh_from_db()
    assert dataset.headers == ["email"]
    assert dataset.column_schema == {"email": {"type": "text"}}
    assert dataset.rows.first().data == {"email": "ada@example.com"}


def test_dataset_api_rejects_dropping_index_column(client, profile):
    dataset = create_ready_dataset(profile)

    response = client.post(
        f"/api/datasets/{dataset.key}/columns/drop?api_key={profile.key}",
        data={"name": "email"},
        content_type="application/json",
    )

    assert response.status_code == 400
    assert "Index column" in response.json()["detail"]
    dataset.refresh_from_db()
    assert dataset.headers == ["name", "email"]


def test_dataset_api_reorders_columns(client, profile):
    dataset = create_ready_dataset(profile)

    response = client.post(
        f"/api/datasets/{dataset.key}/columns/reorder?api_key={profile.key}",
        data={"headers": ["email", "name"]},
        content_type="application/json",
    )

    assert response.status_code == 200
    assert response.json()["dataset"]["headers"] == ["email", "name"]
    dataset.refresh_from_db()
    assert dataset.headers == ["email", "name"]
    assert dataset.rows.first().data == {
        "name": "Ada",
        "email": "ada@example.com",
    }


def test_dataset_mutation_history_records_row_update_diffs_without_schema_backfill_values(
    client,
    profile,
):
    create_response = client.post(
        f"/api/datasets?api_key={profile.key}",
        data={
            "name": "Sensitive contacts",
            "headers": ["email", "name"],
            "index_column": "email",
            "rows": [{"email": "ada@example.com", "name": "Ada Private"}],
        },
        content_type="application/json",
    )
    assert create_response.status_code == 201
    dataset = Dataset.objects.get(key=create_response.json()["dataset"]["key"])
    row = dataset.rows.get()

    add_column_response = client.post(
        f"/api/datasets/{dataset.key}/columns?api_key={profile.key}",
        data={"name": "private_note", "default_value": "secret-default"},
        content_type="application/json",
    )
    assert add_column_response.status_code == 200

    patch_row_response = client.patch(
        f"/api/datasets/{dataset.key}/rows/{row.id}?api_key={profile.key}",
        data={"data": {"name": "New Private"}},
        content_type="application/json",
    )
    assert patch_row_response.status_code == 200

    delete_row_response = client.delete(
        f"/api/datasets/{dataset.key}/rows/{row.id}?api_key={profile.key}"
    )
    assert delete_row_response.status_code == 200

    mutations = DatasetMutation.objects.filter(dataset=dataset)
    assert set(mutations.values_list("mutation_type", flat=True)) == {
        DatasetMutationType.DATASET_CREATED,
        DatasetMutationType.COLUMN_ADDED,
        DatasetMutationType.ROW_UPDATED,
        DatasetMutationType.ROW_DELETED,
    }

    column_mutation = mutations.get(mutation_type=DatasetMutationType.COLUMN_ADDED)
    assert column_mutation.metadata == {
        "column": "private_note",
        "column_type": "text",
        "default_value_provided": True,
    }

    row_update_mutation = mutations.get(mutation_type=DatasetMutationType.ROW_UPDATED)
    assert row_update_mutation.metadata == {
        "row_id": row.id,
        "row_number": 1,
        "changed_fields": ["name"],
        "field_changes": [
            {
                "field": "name",
                "before": "Ada Private",
                "after": "New Private",
            }
        ],
        "value_changes_recorded": True,
        "index_changed": False,
    }

    serialized_metadata = "\n".join(str(mutation.metadata) for mutation in mutations)
    assert "Ada Private" in serialized_metadata
    assert "New Private" in serialized_metadata
    assert "secret-default" not in serialized_metadata
    assert "ada@example.com" not in serialized_metadata


def test_dataset_mutation_history_preserves_zero_target_identifier(profile):
    dataset = create_ready_dataset(profile)

    mutation = record_dataset_mutation(
        dataset,
        DatasetMutationType.ROW_UPDATED,
        "Row updated.",
        target_identifier=0,
    )

    assert mutation.target_identifier == "0"


def test_dataset_api_rejects_unknown_column_type_header(client, profile):
    dataset = create_ready_dataset(profile)

    response = client.patch(
        f"/api/datasets/{dataset.key}/column-types?api_key={profile.key}",
        data={"column_types": {"missing": "text"}},
        content_type="application/json",
    )

    assert response.status_code == 400
    assert "unknown headers" in response.json()["detail"]


def test_create_profile_dataset_row_tracks_first_row_mutation(profile, monkeypatch):
    calls = []

    def track_activation_event(profile, event_name, properties, source_function=None):
        calls.append((profile.id, event_name, properties, source_function))

    monkeypatch.setattr("apps.api.services.track_activation_event", track_activation_event)
    result = create_profile_dataset(profile, name="Tasks", headers=["task"])
    calls.clear()

    create_profile_dataset_row(profile, result["dataset"]["key"], {"task": "Ship"})

    dataset = Dataset.objects.get(key=result["dataset"]["key"])
    assert calls == [
        (
            profile.id,
            ROWSET_DATASET_ROW_MUTATED,
            {
                "mutation_type": DatasetMutationType.ROW_CREATED,
                "dataset_id": dataset.id,
                "row_count_after": 1,
                "changed_field_count": 2,
                "deleted_count": 0,
                "index_changed": False,
                "image_asset_attached": False,
                "is_first_row_mutation": True,
                "agent_api_key_present": False,
                "agent_api_key_id": None,
                "agent_api_key_access_level": "",
            },
            "apps.api.services.dataset_row_mutation",
        )
    ]
    assert "Ship" not in str(calls)


def test_free_account_rejects_51st_dataset_row(profile):
    result = create_profile_dataset(
        profile,
        name="Free row capped dataset",
        headers=["name"],
        rows=[{"name": str(index)} for index in range(50)],
    )

    with pytest.raises(DatasetServiceError, match="at most 50 rows per dataset") as exc_info:
        create_profile_dataset_row(
            profile,
            result["dataset"]["key"],
            {"name": "51"},
        )

    dataset = Dataset.objects.get(key=result["dataset"]["key"])
    assert exc_info.value.status_code == 403
    assert dataset.row_count == 50


def test_paid_account_can_create_51st_dataset_row(profile):
    profile.state = ProfileStates.SUBSCRIBED
    profile.save(update_fields=["state"])
    result = create_profile_dataset(
        profile,
        name="Paid row uncapped dataset",
        headers=["name"],
        rows=[{"name": str(index)} for index in range(50)],
    )

    row_result = create_profile_dataset_row(
        profile,
        result["dataset"]["key"],
        {"name": "51"},
    )

    dataset = Dataset.objects.get(key=result["dataset"]["key"])
    assert row_result["message"] == "Row created."
    assert dataset.row_count == 51


def test_dataset_api_rejects_patch_to_generated_index(client, profile):
    dataset = create_ready_dataset(profile)
    dataset.index_column = "rowset_id"
    dataset.index_generated = True
    dataset.headers = ["rowset_id", "name", "email"]
    dataset.save(update_fields=["index_column", "index_generated", "headers"])
    row = dataset.rows.first()
    row.index_value = "1"
    row.data = {"rowset_id": "1", **row.data}
    row.save(update_fields=["index_value", "data"])

    response = client.patch(
        f"/api/datasets/{dataset.key}/rows/{row.id}?api_key={profile.key}",
        data={"data": {"rowset_id": "custom"}},
        content_type="application/json",
    )

    assert response.status_code == 400
    assert "managed by Rowset" in response.json()["detail"]

    by_index_response = client.patch(
        f"/api/datasets/{dataset.key}/rows/by-index?api_key={profile.key}&index_value=1",
        data={"data": {"rowset_id": "custom"}},
        content_type="application/json",
    )

    assert by_index_response.status_code == 400
    assert "managed by Rowset" in by_index_response.json()["detail"]

    idempotent_response = client.patch(
        f"/api/datasets/{dataset.key}/rows/{row.id}?api_key={profile.key}",
        data={"data": {"rowset_id": "1", "name": "Ada Updated"}},
        content_type="application/json",
    )

    assert idempotent_response.status_code == 200
    assert idempotent_response.json()["row"]["index_value"] == "1"
    assert idempotent_response.json()["row"]["data"]["name"] == "Ada Updated"

    idempotent_by_index_response = client.patch(
        f"/api/datasets/{dataset.key}/rows/by-index?api_key={profile.key}&index_value=1",
        data={"data": {"rowset_id": "1", "name": "Ada By Index"}},
        content_type="application/json",
    )

    assert idempotent_by_index_response.status_code == 200
    assert idempotent_by_index_response.json()["row"]["index_value"] == "1"
    assert idempotent_by_index_response.json()["row"]["data"]["name"] == "Ada By Index"


def test_dataset_api_rejects_other_users_dataset(client, django_user_model, profile):
    dataset = create_ready_dataset(profile)
    other_user = django_user_model.objects.create_user(
        username="other",
        email="other@example.com",
        password="password123",
    )

    response = client.get(f"/api/datasets/{dataset.key}/rows?api_key={other_user.profile.key}")

    assert response.status_code == 404

    public_key_response = client.get(
        f"/api/datasets/{dataset.public_key}/rows?api_key={other_user.profile.key}"
    )

    assert public_key_response.status_code == 404


def test_dataset_owner_can_create_project(auth_client, profile):
    response = auth_client.post(
        reverse("project_create"),
        {
            "name": "Launch",
            "description": "Launch datasets",
            "metadata": json.dumps({"github_repo": "https://github.com/acme/launch"}),
        },
    )

    project = Project.objects.get(profile=profile, name="Launch")
    assert response.status_code == 302
    assert response.url == project.get_absolute_url()
    assert project.description == "Launch datasets"
    assert project.metadata == {"github_repo": "https://github.com/acme/launch"}


def test_project_owner_can_update_metadata_from_settings(auth_client, profile):
    project = Project.objects.create(
        profile=profile,
        name="Launch",
        metadata={"github_repo": "https://github.com/acme/old"},
    )

    response = auth_client.post(
        reverse("project_update_metadata", args=[project.key]),
        {
            "metadata": json.dumps(
                {
                    "github_repo": "https://github.com/acme/launch",
                    "slack_thread": "https://acme.slack.com/archives/C123/p456",
                }
            )
        },
    )

    assert response.status_code == 302
    assert response.url == project.get_settings_url()
    project.refresh_from_db()
    assert project.metadata == {
        "github_repo": "https://github.com/acme/launch",
        "slack_thread": "https://acme.slack.com/archives/C123/p456",
    }


def test_dataset_owner_can_update_project_details(auth_client, profile):
    project = Project.objects.create(
        profile=profile,
        name="Launch",
        description="Launch datasets",
    )

    response = auth_client.post(
        reverse("project_update", args=[project.key]),
        {"name": "Launch operations", "description": ""},
    )

    assert response.status_code == 302
    assert response.url == project.get_settings_url()
    project.refresh_from_db()
    assert project.name == "Launch operations"
    assert project.description == ""


def test_project_update_preserves_description_when_post_omits_field(auth_client, profile):
    project = Project.objects.create(
        profile=profile,
        name="Launch",
        description="Launch datasets",
    )

    response = auth_client.post(
        reverse("project_update", args=[project.key]),
        {"name": "Launch operations"},
    )

    assert response.status_code == 302
    assert response.url == project.get_settings_url()
    project.refresh_from_db()
    assert project.name == "Launch operations"
    assert project.description == "Launch datasets"


def test_project_update_rejects_other_users_project(client, django_user_model, profile):
    other_user = django_user_model.objects.create_user(
        username="other-project-owner",
        email="other-project-owner@example.com",
        password="password123",
    )
    project = Project.objects.create(profile=other_user.profile, name="Other")
    client.force_login(profile.user)

    response = client.post(
        reverse("project_update", args=[project.key]),
        {"name": "Stolen", "description": "Nope"},
    )

    assert response.status_code == 404
    project.refresh_from_db()
    assert project.name == "Other"


def test_project_detail_rejects_project_update_post(auth_client, profile):
    project = Project.objects.create(
        profile=profile,
        name="Launch",
        description="Launch datasets",
    )

    response = auth_client.post(
        project.get_absolute_url(),
        {"name": " Frontier ", "description": " Updated plan "},
    )

    assert response.status_code == 405
    project.refresh_from_db()
    assert project.name == "Launch"
    assert project.description == "Launch datasets"


def test_project_update_rejects_duplicate_project_name_from_settings(auth_client, profile):
    project = Project.objects.create(
        profile=profile,
        name="Launch",
        description="Launch datasets",
    )
    Project.objects.create(profile=profile, name="Frontier")

    response = auth_client.post(
        reverse("project_update", args=[project.key]),
        {"name": "frontier", "description": "Updated plan"},
    )

    assert response.status_code == 302
    assert response.url == project.get_settings_url()
    flash_messages = list(get_messages(response.wsgi_request))
    assert len(flash_messages) == 1
    assert flash_messages[0].level == message_constants.ERROR
    assert str(flash_messages[0]) == "Project name already exists."
    project.refresh_from_db()
    assert project.name == "Launch"
    assert project.description == "Launch datasets"


def test_project_detail_update_post_does_not_expose_other_users_project(
    client,
    django_user_model,
    profile,
):
    project = Project.objects.create(
        profile=profile,
        name="Launch",
        description="Launch datasets",
    )
    other_user = django_user_model.objects.create_user(
        username="projectother",
        email="projectother@example.com",
        password="password123",
    )
    client.force_login(other_user)

    response = client.post(
        project.get_absolute_url(),
        {"name": "Frontier", "description": "Updated plan"},
    )

    assert response.status_code == 405
    project.refresh_from_db()
    assert project.name == "Launch"
    assert project.description == "Launch datasets"


def test_project_update_raises_not_found_for_service_404(
    auth_client,
    monkeypatch,
    profile,
):
    from apps.api.services import DatasetServiceError

    project = Project.objects.create(
        profile=profile,
        name="Launch",
        description="Launch datasets",
    )

    def raise_not_found(*args, **kwargs):
        raise DatasetServiceError(404, "Project not found.")

    monkeypatch.setattr("apps.datasets.views.update_profile_project", raise_not_found)

    response = auth_client.post(
        reverse("project_update", args=[project.key]),
        {"name": "Launch operations", "description": "Updated plan"},
    )

    assert response.status_code == 404
    project.refresh_from_db()
    assert project.name == "Launch"
    assert project.description == "Launch datasets"


def test_project_detail_paginates_assigned_datasets(auth_client, profile):
    project = Project.objects.create(profile=profile, name="Large project")
    for index in range(101):
        Dataset.objects.create(
            profile=profile,
            project=project,
            name=f"Project dataset {index:03}",
            original_filename="Created via API",
            file_type="api",
            status=DatasetStatus.READY,
            headers=["email"],
            index_column="email",
            row_count=0,
        )
    Dataset.objects.create(
        profile=profile,
        project=project,
        name="Draft upload",
        original_filename="draft.csv",
        status=DatasetStatus.PREVIEWED,
        headers=["email"],
        index_column="email",
    )

    response = auth_client.get(f"{project.get_absolute_url()}?archived_page=2")
    content = response.content.decode()

    assert response.status_code == 200
    assert len(response.context["datasets"]) == 100
    assert "101 datasets" in content
    assert "Draft upload" not in content
    assert "Page 1 of 2" in content
    assert "archived_page=2&amp;page=2" in content

    page_two = auth_client.get(f"{project.get_absolute_url()}?page=2")

    assert page_two.status_code == 200
    assert len(page_two.context["datasets"]) == 1
    assert "Page 2 of 2" in page_two.content.decode()


def test_project_detail_groups_datasets_by_section(auth_client, profile):
    assert hasattr(dataset_models, "ProjectSection")
    ProjectSection = dataset_models.ProjectSection
    project = Project.objects.create(profile=profile, name="Rowset")
    blog = ProjectSection.objects.create(profile=profile, project=project, name="Blog")
    Dataset.objects.create(
        profile=profile,
        project=project,
        section=blog,
        name="Content ledger",
        original_filename="Created via API",
        file_type="api",
        status=DatasetStatus.READY,
        headers=["slug"],
        index_column="slug",
    )
    Dataset.objects.create(
        profile=profile,
        project=project,
        name="Backlog",
        original_filename="Created via API",
        file_type="api",
        status=DatasetStatus.READY,
        headers=["signal"],
        index_column="signal",
    )
    Dataset.objects.create(
        profile=profile,
        project=project,
        name="Signals",
        original_filename="Created via API",
        file_type="api",
        status=DatasetStatus.READY,
        headers=["signal"],
        index_column="signal",
    )

    response = auth_client.get(project.get_absolute_url())
    content = response.content.decode()

    assert response.status_code == 200
    assert response.context["section_groups"][0]["label"] == "Blog"
    assert response.context["section_groups"][0]["datasets"][0].name == "Content ledger"
    assert response.context["section_groups"][1]["label"] == "Unsectioned"
    assert response.context["section_groups"][1]["dataset_count"] == 2
    assert len(response.context["section_groups"][1]["datasets"]) == 2
    assert response.context["section_groups"][1]["datasets"][0].name == "Signals"
    assert "Blog" in content
    assert "Unsectioned" in content


def test_project_detail_groups_archived_datasets_by_section_in_collapsed_block(
    auth_client,
    profile,
):
    assert hasattr(dataset_models, "ProjectSection")
    ProjectSection = dataset_models.ProjectSection
    project = Project.objects.create(profile=profile, name="Rowset")
    blog = ProjectSection.objects.create(profile=profile, project=project, name="Blog")
    sectioned = create_ready_dataset(profile)
    sectioned.name = "Archived content ledger"
    sectioned.project = project
    sectioned.section = blog
    sectioned.archived_at = timezone.now()
    sectioned.save(update_fields=["name", "project", "section", "archived_at"])
    unsectioned = create_ready_dataset(profile)
    unsectioned.name = "Archived backlog"
    unsectioned.project = project
    unsectioned.archived_at = timezone.now()
    unsectioned.save(update_fields=["name", "project", "archived_at"])

    response = auth_client.get(project.get_absolute_url())
    content = response.content.decode()

    assert response.status_code == 200
    assert "<details open" not in content
    assert response.context["archived_section_groups"][0]["label"] == "Blog"
    assert response.context["archived_section_groups"][0]["datasets"][0].name == (
        "Archived content ledger"
    )
    assert response.context["archived_section_groups"][1]["label"] == "Unsectioned"
    assert response.context["archived_section_groups"][1]["datasets"][0].name == (
        "Archived backlog"
    )
    assert "Archived datasets" in content
    assert "Archived content ledger" in content
    assert "Archived backlog" in content


def test_project_detail_paginates_archived_datasets(auth_client, profile):
    project = Project.objects.create(profile=profile, name="Rowset")
    archived_at = timezone.now()
    total_archived = PROJECT_DETAIL_DATASET_PAGE_SIZE + 1
    for index in range(total_archived):
        Dataset.objects.create(
            profile=profile,
            project=project,
            name=f"Archived dataset {index:03d}",
            original_filename="Created via API",
            file_type="api",
            status=DatasetStatus.READY,
            headers=["slug"],
            index_column="slug",
            archived_at=archived_at - timedelta(minutes=index),
        )

    response = auth_client.get(project.get_absolute_url())
    content = response.content.decode()

    assert response.status_code == 200
    assert response.context["archived_page_obj"].paginator.count == total_archived
    assert len(response.context["archived_datasets"]) == PROJECT_DETAIL_DATASET_PAGE_SIZE
    assert "Archived dataset 000" in content
    assert "Archived dataset 099" in content
    assert "Archived dataset 100" not in content
    assert "archived_page=2#archived-datasets" in content

    second_page_response = auth_client.get(f"{project.get_absolute_url()}?archived_page=2")
    second_page_content = second_page_response.content.decode()

    assert second_page_response.status_code == 200
    assert len(second_page_response.context["archived_datasets"]) == 1
    assert "Archived dataset 100" in second_page_content
    assert '<details id="archived-datasets"' in second_page_content
    assert "open" in second_page_content


def test_dataset_settings_page_has_section_navigation(auth_client, profile):
    dataset = create_ready_dataset(profile)

    response = auth_client.get(dataset.get_settings_url())

    assert response.status_code == 200
    content = response.content.decode()
    assert "<title>People settings · Rowset</title>" in content
    assert 'aria-labelledby="dataset-settings-nav-heading"' in content
    for section_id in [
        "dataset-context",
        "project",
        "relationships",
        "column-types",
        "public-preview",
        "danger-zone",
    ]:
        assert f'href="#{section_id}"' in content
        assert f'id="{section_id}"' in content


def test_dataset_owner_can_assign_project_from_settings(auth_client, profile):
    dataset = create_ready_dataset(profile)
    project = Project.objects.create(profile=profile, name="Customer work")

    response = auth_client.post(
        reverse("dataset_update_project", args=[dataset.key]),
        {"project_key": str(project.key)},
    )

    assert response.status_code == 302
    dataset.refresh_from_db()
    assert dataset.project == project
    mutation = dataset.mutations.get(mutation_type=DatasetMutationType.DATASET_PROJECT_UPDATED)
    assert mutation.actor_label == "Account"
    assert mutation.metadata["project_name"] == "Customer work"

    detach_response = auth_client.post(
        reverse("dataset_update_project", args=[dataset.key]),
        {"project_key": ""},
    )

    assert detach_response.status_code == 302
    dataset.refresh_from_db()
    assert dataset.project is None


def test_dataset_owner_can_assign_project_section_from_settings(auth_client, profile):
    assert hasattr(dataset_models, "ProjectSection")
    ProjectSection = dataset_models.ProjectSection
    dataset = create_ready_dataset(profile)
    project = Project.objects.create(profile=profile, name="Rowset")
    section = ProjectSection.objects.create(profile=profile, project=project, name="Blog")

    response = auth_client.post(
        reverse("dataset_update_project", args=[dataset.key]),
        {"project_key": str(project.key), "section_key": str(section.key)},
    )

    assert response.status_code == 302
    dataset.refresh_from_db()
    assert dataset.project == project
    assert dataset.section == section
    mutation = dataset.mutations.get(mutation_type=DatasetMutationType.DATASET_PROJECT_UPDATED)
    assert mutation.metadata["section_name"] == "Blog"


def test_dataset_project_settings_rejects_mismatched_section_with_message(auth_client, profile):
    assert hasattr(dataset_models, "ProjectSection")
    ProjectSection = dataset_models.ProjectSection
    dataset = create_ready_dataset(profile)
    project = Project.objects.create(profile=profile, name="Rowset")
    other_project = Project.objects.create(profile=profile, name="Other")
    section = ProjectSection.objects.create(profile=profile, project=other_project, name="Blog")

    response = auth_client.post(
        reverse("dataset_update_project", args=[dataset.key]),
        {"project_key": str(project.key), "section_key": str(section.key)},
    )

    assert response.status_code == 302
    assert response.url == dataset.get_settings_url()
    dataset.refresh_from_db()
    assert dataset.project is None
    assert dataset.section is None
    flash_messages = list(get_messages(response.wsgi_request))
    assert len(flash_messages) == 1
    assert flash_messages[0].level == message_constants.ERROR
    assert str(flash_messages[0]) == "Project section not found."


def test_dataset_project_settings_marks_section_options_by_project(auth_client, profile):
    assert hasattr(dataset_models, "ProjectSection")
    ProjectSection = dataset_models.ProjectSection
    dataset = create_ready_dataset(profile)
    rowset_project = Project.objects.create(profile=profile, name="Rowset")
    other_project = Project.objects.create(profile=profile, name="Other")
    rowset_section = ProjectSection.objects.create(
        profile=profile,
        project=rowset_project,
        name="Blog",
    )
    other_section = ProjectSection.objects.create(
        profile=profile,
        project=other_project,
        name="Sales",
    )

    response = auth_client.get(dataset.get_settings_url())
    content = response.content.decode()

    assert response.status_code == 200
    assert 'x-data="datasetProject"' in content
    assert 'x-ref="projectSelect"' in content
    assert '@change="syncSections()"' in content
    assert 'x-ref="sectionSelect"' in content
    assert f'value="{rowset_section.key}"' in content
    assert f'data-project-key="{rowset_project.key}"' in content
    assert "Rowset / Blog" in content
    assert f'value="{other_section.key}"' in content
    assert f'data-project-key="{other_project.key}"' in content
    assert "Other / Sales" in content


def test_dataset_owner_can_update_metadata_from_settings(auth_client, profile):
    dataset = create_ready_dataset(profile)

    response = auth_client.post(
        reverse("dataset_update_metadata", args=[dataset.key]),
        {
            "description": "Human-visible task board.",
            "instructions": "Keep acceptance criteria in notes before moving to done.",
            "metadata": json.dumps({"status_order": ["todo", "doing", "done"]}),
        },
    )

    assert response.status_code == 302
    dataset.refresh_from_db()
    assert dataset.description == "Human-visible task board."
    assert dataset.instructions == "Keep acceptance criteria in notes before moving to done."
    assert dataset.metadata == {"status_order": ["todo", "doing", "done"]}
    mutation = dataset.mutations.get(mutation_type=DatasetMutationType.DATASET_METADATA_UPDATED)
    assert mutation.actor_label == "Account"
    assert mutation.metadata["changed_fields"] == ["description", "instructions", "metadata"]


def test_dataset_owner_can_update_column_types_from_settings(auth_client, profile):
    dataset = create_ready_dataset(profile)

    response = auth_client.post(
        reverse("dataset_update_column_settings", args=[dataset.key]),
        {
            "column_name": ["name", "email"],
            "column_type": ["text", "text"],
            "column_description": [
                "Human-readable full name.",
                "Primary contact email for row lookup.",
            ],
        },
    )

    assert response.status_code == 302
    dataset.refresh_from_db()
    assert dataset.column_schema == {
        "name": {
            "type": "text",
            "description": "Human-readable full name.",
        },
        "email": {
            "type": "text",
            "description": "Primary contact email for row lookup.",
        },
    }
    mutation = dataset.mutations.get(mutation_type=DatasetMutationType.COLUMN_TYPES_UPDATED)
    assert mutation.actor_label == "Account"
    assert mutation.metadata["updated_columns"] == ["email", "name"]


def test_dataset_detail_shows_column_descriptions_on_header_hover(
    auth_client,
    profile,
):
    dataset = create_ready_dataset(profile)
    dataset.column_schema = {
        "name": {
            "type": "text",
            "description": "Human-readable full name.",
        },
        "email": {"type": "email"},
    }
    dataset.save(update_fields=["column_schema"])

    response = auth_client.get(dataset.get_absolute_url())

    assert response.status_code == 200
    content = response.content.decode()
    assert 'x-data="rowColumnMenu"' in content
    assert 'title="Human-readable full name."' in content
    assert '@click="open($event)"' in content
    assert '@contextmenu="open($event)"' in content
    assert "<dialog" in content
    assert 'aria-describedby="row-column-menu-description-0"' in content
    assert 'id="row-column-menu-description-0"' in content
    assert 'name="row_sort" value="col_0"' in content
    assert "Contains text" in content


def test_dataset_owner_cannot_update_column_types_while_processing(auth_client, profile):
    dataset = create_ready_dataset(profile)
    dataset.status = DatasetStatus.PROCESSING
    dataset.column_schema = {"name": {"type": "text"}, "email": {"type": "email"}}
    dataset.save(update_fields=["status", "column_schema"])

    response = auth_client.post(
        reverse("dataset_update_column_settings", args=[dataset.key]),
        {
            "column_name": ["name", "email"],
            "column_type": ["text", "text"],
        },
    )

    assert response.status_code == 302
    dataset.refresh_from_db()
    assert dataset.column_schema == {
        "name": {"type": "text"},
        "email": {"type": "email"},
    }
