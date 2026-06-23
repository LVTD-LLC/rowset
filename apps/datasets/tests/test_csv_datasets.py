import csv
import io
import json
import sqlite3
import xml.etree.ElementTree as ET
import zipfile

import polars as pl
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from apps.core.services import create_agent_api_key
from apps.datasets.choices import DatasetMutationType, DatasetStatus
from apps.datasets.history import record_dataset_mutation
from apps.datasets.models import Dataset, DatasetMutation, DatasetRow, Project
from apps.datasets.services import (
    CSVParseError,
    infer_column_type,
    preview_csv_file,
    preview_uploaded_table,
    rows_to_sqlite_bytes,
)
from apps.datasets.tasks import import_dataset_rows
from apps.datasets.views import DATASET_DETAIL_ROW_PAGE_SIZE

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user(
        username="csvuser",
        email="csvuser@example.com",
        password="password123",
    )


@pytest.fixture
def auth_client(client, user):
    client.force_login(user)
    return client


@pytest.fixture
def profile(user):
    return user.profile


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


def xlsx_cell_texts(content: bytes) -> list[str]:
    with zipfile.ZipFile(io.BytesIO(content)) as workbook:
        sheet_xml = workbook.read("xl/worksheets/sheet1.xml")
    root = ET.fromstring(sheet_xml)
    namespace = {"xlsx": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    return [element.text or "" for element in root.findall(".//xlsx:t", namespace)]


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

    response = auth_client.get(reverse("dataset_list"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "People" in content
    assert "Preview Only" not in content


def test_dataset_list_does_not_show_agent_prompt_cta(auth_client):
    response = auth_client.get(reverse("dataset_list"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Copy agent prompt" not in content
    assert "Copy the agent prompt" not in content


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

    response = auth_client.get(reverse("dataset_list"), {"q": "people", "sort": "rows"})

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
    assert "Search datasets" in content
    assert "People" in content
    assert "Research" in content
    assert "Invoices" not in content
    assert reverse("dataset_export", args=[dataset.key, "csv"]) not in content
    assert reverse("dataset_export", args=[dataset.key, "parquet"]) not in content
    assert reverse("dataset_delete", args=[dataset.key]) not in content
    assert "Dataset status" not in content


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
    assert "Row 1" in content
    assert "notes" in content
    assert full_value in content
    assert "extra_field" in content
    assert "Stored outside declared headers" in content
    assert "Back to dataset" in content


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
    assert 'data-controller="export-menu"' in content
    assert "CSV snapshot" in content
    assert "JSONL snapshot" in content
    assert "XLSX snapshot" in content
    assert "SQLite snapshot" in content
    assert "Parquet snapshot" in content
    assert 'aria-label="Dataset status: Ready"' not in content


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
    assert 'data-dataset-status-target="message"' in content
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


def test_project_detail_dataset_rows_omit_status_and_actions(auth_client, profile):
    project = Project.objects.create(profile=profile, name="Launch")
    dataset = create_ready_dataset(profile)
    dataset.project = project
    dataset.save(update_fields=["project"])

    response = auth_client.get(project.get_absolute_url())

    content = response.content.decode()
    assert response.status_code == 200
    assert "All datasets" in content
    assert "People" in content
    assert reverse("dataset_export", args=[dataset.key, "csv"]) not in content
    assert reverse("dataset_export", args=[dataset.key, "parquet"]) not in content
    assert dataset.get_settings_url() not in content
    assert "Dataset status" not in content


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

    create_response = client.post(
        f"/api/datasets/{dataset.key}/rows?api_key={api_key}",
        data={"data": {"name": "Katherine", "email": "kat@example.com"}},
        content_type="application/json",
    )
    assert create_response.status_code == 200
    row_id = create_response.json()["row"]["id"]
    assert create_response.json()["row"]["index_value"] == "kat@example.com"

    get_by_index_response = client.get(
        f"/api/datasets/{dataset.key}/rows/by-index?api_key={api_key}&index_value=kat@example.com"
    )
    assert get_by_index_response.status_code == 200
    assert get_by_index_response.json()["row"]["data"]["name"] == "Katherine"

    patch_response = client.patch(
        f"/api/datasets/{dataset.key}/rows/{row_id}?api_key={api_key}",
        data={"data": {"email": "katherine@example.com", "ignored": "nope"}},
        content_type="application/json",
    )
    assert patch_response.status_code == 200
    assert patch_response.json()["row"]["data"] == {
        "name": "Katherine",
        "email": "katherine@example.com",
    }

    export_response = client.get(f"/api/datasets/{dataset.key}/export.csv?api_key={api_key}")
    assert export_response.status_code == 200
    exported = list(csv.DictReader(io.StringIO(export_response.content.decode())))
    assert exported[0] == {"name": "Ada", "email": "ada@example.com"}

    delete_response = client.delete(f"/api/datasets/{dataset.key}/rows/{row_id}?api_key={api_key}")
    assert delete_response.status_code == 200
    assert not DatasetRow.objects.filter(id=row_id).exists()


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


def test_dataset_api_creates_ready_dataset_with_explicit_index(client, profile):
    project = Project.objects.create(profile=profile, name="Catalogs")

    response = client.post(
        "/api/datasets",
        data={
            "name": "Products",
            "project_key": str(project.key),
            "headers": ["sku", "name", "price"],
            "index_column": "sku",
            "rows": [
                {"sku": "A-1", "name": "Adapter", "price": 19.99},
                {"sku": "B-2", "name": "Bridge", "price": 29},
            ],
        },
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {profile.key}",
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["dataset"]["name"] == "Products"
    assert payload["dataset"]["project"] == {
        "key": str(project.key),
        "name": "Catalogs",
        "description": "",
    }
    assert payload["dataset"]["file_type"] == "api"
    assert payload["dataset"]["status"] == DatasetStatus.READY
    assert payload["dataset"]["index_column"] == "sku"
    assert payload["dataset"]["column_schema"] == {
        "sku": {"type": "text"},
        "name": {"type": "text"},
        "price": {"type": "currency"},
    }
    assert payload["dataset"]["row_count"] == 2

    dataset = Dataset.objects.get(key=payload["dataset"]["key"], profile=profile)
    assert dataset.project == project
    assert dataset.headers == ["sku", "name", "price"]
    assert dataset.column_schema == {
        "sku": {"type": "text"},
        "name": {"type": "text"},
        "price": {"type": "currency"},
    }
    assert dataset.original_filename == "Created via API"
    assert dataset.confirmed_at is not None
    assert dataset.processed_at is not None
    assert list(dataset.rows.values_list("index_value", flat=True)) == ["A-1", "B-2"]
    assert dataset.rows.first().data == {
        "sku": "A-1",
        "name": "Adapter",
        "price": "19.99",
    }


def test_dataset_api_creates_ready_dataset_with_generated_index(client, profile):
    response = client.post(
        f"/api/datasets?api_key={profile.key}",
        data={
            "name": "Scratch tasks",
            "rows": [
                {"task": "Draft"},
            ],
        },
        content_type="application/json",
    )

    assert response.status_code == 201
    dataset_key = response.json()["dataset"]["key"]
    dataset = Dataset.objects.get(key=dataset_key, profile=profile)
    assert response.json()["dataset"]["project"] is None
    assert dataset.project is None
    assert dataset.headers == ["rowset_id", "task"]
    assert dataset.column_schema == {
        "rowset_id": {"type": "integer"},
        "task": {"type": "text"},
    }
    assert dataset.index_column == "rowset_id"
    assert dataset.index_generated is True
    assert dataset.rows.first().data == {"rowset_id": "1", "task": "Draft"}

    create_response = client.post(
        f"/api/datasets/{dataset.key}/rows?api_key={profile.key}",
        data={"data": {"rowset_id": "custom", "task": "Ship"}},
        content_type="application/json",
    )

    assert create_response.status_code == 200
    assert create_response.json()["row"]["index_value"] == "2"
    assert create_response.json()["row"]["data"] == {"rowset_id": "2", "task": "Ship"}


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
    list_content = client.get(reverse("dataset_list")).content.decode()
    detail_content = client.get(dataset.get_absolute_url()).content.decode()
    settings_content = client.get(dataset.get_settings_url()).content.decode()
    project_content = client.get(project.get_absolute_url()).content.decode()
    home_content = client.get(reverse("home")).content.decode()

    assert "Created by Codex · Last updated by OpenClaw" in list_content
    assert "Codex" in detail_content
    assert "OpenClaw" in settings_content
    assert "Touched by" in detail_content
    assert f'href="{row.get_absolute_url()}"' in detail_content
    assert ">OpenClaw</a>" in detail_content
    assert "Recent changes" in detail_content
    assert "Dataset created with 0 rows and 2 columns." in detail_content
    assert "Row 1 added." in detail_content
    assert "Created by Codex · Last updated by OpenClaw" in project_content
    assert "Updated by OpenClaw" in home_content


def test_dataset_api_accepts_explicit_column_types_on_create(client, profile):
    response = client.post(
        f"/api/datasets?api_key={profile.key}",
        data={
            "name": "Products",
            "headers": ["sku", "price"],
            "index_column": "sku",
            "column_types": {"sku": "text", "price": "number"},
            "rows": [{"sku": "A-1", "price": "19.99"}],
        },
        content_type="application/json",
    )

    assert response.status_code == 201
    dataset = Dataset.objects.get(key=response.json()["dataset"]["key"], profile=profile)
    assert dataset.column_schema == {
        "sku": {"type": "text"},
        "price": {"type": "number"},
    }


def test_project_api_creates_lists_and_returns_project_datasets(client, profile):
    create_project_response = client.post(
        f"/api/projects?api_key={profile.key}",
        data={"name": "Launch", "description": "Launch datasets"},
        content_type="application/json",
    )

    assert create_project_response.status_code == 201
    project_key = create_project_response.json()["project"]["key"]

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

    detail_response = client.get(f"/api/projects/{project_key}?api_key={profile.key}")
    assert detail_response.status_code == 200
    assert detail_response.json()["project"]["name"] == "Launch"
    assert detail_response.json()["datasets"]["count"] == 1
    assert detail_response.json()["datasets"]["total_count"] == 1
    assert detail_response.json()["datasets"]["datasets"][0]["name"] == "Launch contacts"
    assert [dataset["name"] for dataset in detail_response.json()["datasets"]["datasets"]] == [
        "Launch contacts"
    ]


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


def test_dataset_api_updates_column_types(client, profile):
    dataset = create_ready_dataset(profile)

    response = client.patch(
        f"/api/datasets/{dataset.key}/column-types?api_key={profile.key}",
        data={"column_types": {"email": "text"}},
        content_type="application/json",
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["dataset"]["column_schema"] == {
        "name": {"type": "text"},
        "email": {"type": "text"},
    }
    dataset.refresh_from_db()
    assert dataset.column_schema == {
        "name": {"type": "text"},
        "email": {"type": "text"},
    }


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


def test_dataset_mutation_history_does_not_copy_private_row_values(client, profile):
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
        "index_changed": False,
    }

    serialized_metadata = "\n".join(str(mutation.metadata) for mutation in mutations)
    assert "Ada Private" not in serialized_metadata
    assert "New Private" not in serialized_metadata
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


def test_dataset_api_rejects_duplicate_index_on_create(client, profile):
    response = client.post(
        f"/api/datasets?api_key={profile.key}",
        data={
            "name": "Duplicate products",
            "headers": ["sku", "name"],
            "index_column": "sku",
            "rows": [
                {"sku": "A-1", "name": "Adapter"},
                {"sku": "A-1", "name": "Another adapter"},
            ],
        },
        content_type="application/json",
    )

    assert response.status_code == 409
    assert "Duplicate value: A-1" in response.json()["detail"]
    assert not Dataset.objects.filter(profile=profile, name="Duplicate products").exists()


def test_dataset_api_rejects_too_many_initial_rows(client, profile):
    response = client.post(
        f"/api/datasets?api_key={profile.key}",
        data={
            "name": "Too many rows",
            "headers": ["name"],
            "rows": [{"name": str(index)} for index in range(1001)],
        },
        content_type="application/json",
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "payload", "rows"]
    assert not Dataset.objects.filter(profile=profile, name="Too many rows").exists()


def test_create_profile_dataset_enforces_initial_row_limit(profile):
    from apps.api.services import DatasetServiceError, create_profile_dataset

    with pytest.raises(DatasetServiceError, match="at most 1000 initial rows") as exc_info:
        create_profile_dataset(
            profile,
            name="Too many rows",
            headers=["name"],
            rows=[{"name": str(index)} for index in range(1001)],
        )

    assert exc_info.value.status_code == 400
    assert not Dataset.objects.filter(profile=profile, name="Too many rows").exists()


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


def test_dataset_api_rejects_other_users_dataset(client, django_user_model, profile):
    dataset = create_ready_dataset(profile)
    other_user = django_user_model.objects.create_user(
        username="other",
        email="other@example.com",
        password="password123",
    )

    response = client.get(f"/api/datasets/{dataset.key}/rows?api_key={other_user.profile.key}")

    assert response.status_code == 404


def test_dataset_owner_can_create_project(auth_client, profile):
    response = auth_client.post(
        reverse("project_create"),
        {"name": "Launch", "description": "Launch datasets"},
    )

    project = Project.objects.get(profile=profile, name="Launch")
    assert response.status_code == 302
    assert response.url == project.get_absolute_url()
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

    response = auth_client.get(project.get_absolute_url())
    content = response.content.decode()

    assert response.status_code == 200
    assert len(response.context["datasets"]) == 100
    assert "101 datasets" in content
    assert "Draft upload" not in content
    assert "Page 1 of 2" in content

    page_two = auth_client.get(f"{project.get_absolute_url()}?page=2")

    assert page_two.status_code == 200
    assert len(page_two.context["datasets"]) == 1
    assert "Page 2 of 2" in page_two.content.decode()


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


def test_dataset_owner_can_update_column_types_from_settings(auth_client, profile):
    dataset = create_ready_dataset(profile)

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
        "email": {"type": "text"},
    }
    mutation = dataset.mutations.get(mutation_type=DatasetMutationType.COLUMN_TYPES_UPDATED)
    assert mutation.actor_label == "Account"
    assert mutation.metadata["updated_columns"] == ["email", "name"]


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


def test_dataset_public_sharing_is_off_by_default(client, profile):
    dataset = create_ready_dataset(profile)

    response = client.get(dataset.get_public_url())

    assert response.status_code == 404


def test_dataset_owner_can_enable_public_sharing(auth_client, profile):
    dataset = create_ready_dataset(profile)

    response = auth_client.post(
        reverse("dataset_update_public_settings", args=[dataset.key]),
        {
            "public_enabled": "on",
            "public_page_size": "1",
        },
    )

    assert response.status_code == 302
    dataset.refresh_from_db()
    assert dataset.public_enabled is True
    assert dataset.public_page_size == 1
    mutation = dataset.mutations.get(mutation_type=DatasetMutationType.PUBLIC_PREVIEW_UPDATED)
    assert mutation.actor_label == "Account"
    assert mutation.metadata["previous_public_enabled"] is False
    assert mutation.metadata["public_enabled"] is True

    duplicate_response = auth_client.post(
        reverse("dataset_update_public_settings", args=[dataset.key]),
        {
            "public_enabled": "on",
            "public_page_size": "1",
        },
    )

    assert duplicate_response.status_code == 302
    assert (
        dataset.mutations.filter(mutation_type=DatasetMutationType.PUBLIC_PREVIEW_UPDATED).count()
        == 1
    )


def test_public_dataset_view_paginates_rows(client, profile):
    dataset = create_ready_dataset(profile)
    dataset.public_enabled = True
    dataset.public_page_size = 1
    dataset.save(update_fields=["public_enabled", "public_page_size"])

    response = client.get(dataset.get_public_url())

    content = response.content.decode()

    assert response.status_code == 200
    assert "Ada" in content
    assert "Grace" not in content
    assert "Page 1 of 2" in content

    page_two = client.get(f"{dataset.get_public_url()}?page=2")
    page_two_content = page_two.content.decode()
    assert "Grace" in page_two_content


def test_public_dataset_links_rows_and_truncates_cells(client, profile):
    dataset = create_ready_dataset(profile)
    dataset.public_enabled = True
    dataset.save(update_fields=["public_enabled"])
    row = dataset.rows.first()
    row.data["email"] = None
    row.save(update_fields=["data"])

    response = client.get(dataset.get_public_url())
    content = response.content.decode()

    assert response.status_code == 200
    assert reverse("public_dataset_row_detail", args=[dataset.public_key, row.id]) in content
    assert 'class="fb-focus block max-w-64 truncate' in content
    assert 'aria-label="View row 1 details"' in content
    assert content.count('aria-label="View row 1 details"') == 1
    assert 'aria-hidden="true" tabindex="-1"' in content
    assert 'title="None"' not in content
    assert 'title=""' in content


def test_public_dataset_row_detail_displays_full_row_data(client, profile):
    dataset = create_ready_dataset(profile)
    dataset.public_enabled = True
    dataset.headers = ["name", "email", "notes"]
    dataset.save(update_fields=["public_enabled", "headers"])
    row = dataset.rows.first()
    full_value = "Line one\n" + "Full untruncated value " * 12
    row.data = {
        "name": "Ada",
        "email": "ada@example.com",
        "notes": full_value,
        "extra_field": "Stored outside declared headers",
    }
    row.save(update_fields=["data"])

    response = client.get(reverse("public_dataset_row_detail", args=[dataset.public_key, row.id]))
    content = response.content.decode()

    assert response.status_code == 200
    assert "Shared Rowset row" in content
    assert "Row 1" in content
    assert "notes" in content
    assert full_value in content
    assert "extra_field" in content
    assert "Stored outside declared headers" in content
    assert "Back to preview" in content
    assert "Created by" not in content


def test_public_dataset_row_detail_requires_public_preview(client, profile):
    dataset = create_ready_dataset(profile)
    row = dataset.rows.first()

    response = client.get(reverse("public_dataset_row_detail", args=[dataset.public_key, row.id]))

    assert response.status_code == 404


def test_public_dataset_orders_cells_by_headers(client, profile):
    dataset = Dataset.objects.create(
        profile=profile,
        name="Customers",
        original_filename="customers.csv",
        source_text="customer_id,name,plan\nC-1001,Ada Lovelace,Scale\n",
        status=DatasetStatus.READY,
        headers=["customer_id", "name", "plan"],
        index_column="customer_id",
        public_enabled=True,
        row_count=1,
    )
    DatasetRow.objects.create(
        dataset=dataset,
        row_number=1,
        index_value="C-1001",
        data={"name": "Ada Lovelace", "plan": "Scale", "customer_id": "C-1001"},
    )

    response = client.get(dataset.get_public_url())
    content = response.content.decode()

    assert response.status_code == 200
    customer_id_position = content.index('title="C-1001"')
    name_position = content.index('title="Ada Lovelace"')
    plan_position = content.index('title="Scale"')
    assert customer_id_position < name_position < plan_position


def test_public_dataset_row_detail_password_protection(auth_client, client, profile):
    dataset = create_ready_dataset(profile)
    row = dataset.rows.first()
    auth_client.post(
        reverse("dataset_update_public_settings", args=[dataset.key]),
        {
            "public_enabled": "on",
            "public_page_size": "10",
            "public_password": "secret-table",
        },
    )
    dataset.refresh_from_db()
    row_url = reverse("public_dataset_row_detail", args=[dataset.public_key, row.id])

    locked_response = client.get(row_url)
    locked_content = locked_response.content.decode()
    assert locked_response.status_code == 200
    assert "Password required" in locked_content
    assert "Public preview" in locked_content
    assert dataset.get_public_url() in locked_content
    assert dataset.name not in locked_content
    assert "Ada" not in locked_content

    wrong_response = client.post(row_url, {"password": "wrong"})
    assert "That password did not work" in wrong_response.content.decode()

    unlock_response = client.post(row_url, {"password": "secret-table"})
    assert unlock_response.status_code == 302
    assert unlock_response.url == row_url

    unlocked_response = client.get(row_url)
    assert "Ada" in unlocked_response.content.decode()
    assert "Row data" in unlocked_response.content.decode()


def test_public_dataset_password_protection(auth_client, client, profile):
    dataset = create_ready_dataset(profile)
    auth_client.post(
        reverse("dataset_update_public_settings", args=[dataset.key]),
        {
            "public_enabled": "on",
            "public_page_size": "10",
            "public_password": "secret-table",
        },
    )
    dataset.refresh_from_db()

    locked_response = client.get(dataset.get_public_url())
    assert locked_response.status_code == 200
    assert "Password required" in locked_response.content.decode()
    assert "Ada" not in locked_response.content.decode()

    wrong_response = client.post(dataset.get_public_url(), {"password": "wrong"})
    assert "That password did not work" in wrong_response.content.decode()

    unlock_response = client.post(dataset.get_public_url(), {"password": "secret-table"})
    assert unlock_response.status_code == 302

    unlocked_response = client.get(dataset.get_public_url())
    assert "Ada" in unlocked_response.content.decode()


def test_public_dataset_password_change_revokes_existing_unlock(auth_client, client, profile):
    dataset = create_ready_dataset(profile)
    auth_client.post(
        reverse("dataset_update_public_settings", args=[dataset.key]),
        {
            "public_enabled": "on",
            "public_page_size": "10",
            "public_password": "old-secret",
        },
    )
    dataset.refresh_from_db()

    unlock_response = client.post(dataset.get_public_url(), {"password": "old-secret"})
    assert unlock_response.status_code == 302
    assert "Ada" in client.get(dataset.get_public_url()).content.decode()

    auth_client.post(
        reverse("dataset_update_public_settings", args=[dataset.key]),
        {
            "public_enabled": "on",
            "public_page_size": "10",
            "public_password": "new-secret",
        },
    )

    locked_again = client.get(dataset.get_public_url())
    content = locked_again.content.decode()
    assert "Password required" in content
    assert "Ada" not in content
    assert dataset.name not in content
