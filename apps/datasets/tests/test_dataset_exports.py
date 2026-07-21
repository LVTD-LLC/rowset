import csv
import io
import json

import polars as pl
import pytest
from django.urls import reverse
from django.utils import timezone

from apps.datasets.models import Dataset
from apps.datasets.services import rows_to_sqlite_bytes
from apps.datasets.tests.dataset_test_helpers import (
    create_ready_dataset,
    sqlite_rows,
    sqlite_table_columns,
    xlsx_cell_texts,
    xlsx_sheet_xml,
)

pytestmark = pytest.mark.django_db


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


def test_dataset_export_allows_active_dataset(auth_client, profile):
    dataset = Dataset.objects.create(
        profile=profile,
        name="Preview Only",
        headers=["name"],
        preview_rows=[{"name": "Ada"}],
        row_count=1,
    )

    response = auth_client.get(reverse("dataset_export", args=[dataset.key, "csv"]))

    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/csv")


def test_dataset_api_exports_archived_dataset(api_client, profile):
    dataset = create_ready_dataset(profile)
    dataset.archived_at = timezone.now()
    dataset.save(update_fields=["archived_at", "updated_at"])

    response = api_client.get(f"/api/datasets/{dataset.key}/export.csv")

    assert response.status_code == 200
    exported = list(csv.DictReader(io.StringIO(response.content.decode())))
    assert exported[0] == {"name": "Ada", "email": "ada@example.com"}


def test_dataset_api_exports_jsonl_xlsx_and_sqlite(api_client, profile):
    dataset = create_ready_dataset(profile)

    jsonl_response = api_client.get(f"/api/datasets/{dataset.key}/export.jsonl")
    assert jsonl_response.status_code == 200
    assert jsonl_response["Content-Type"] == "application/x-ndjson; charset=utf-8"
    assert [json.loads(line) for line in jsonl_response.content.decode().splitlines()] == [
        {"name": "Ada", "email": "ada@example.com"},
        {"name": "Grace", "email": "grace@example.com"},
    ]

    xlsx_response = api_client.get(f"/api/datasets/{dataset.key}/export.xlsx")
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

    sqlite_response = api_client.get(f"/api/datasets/{dataset.key}/export.sqlite")
    assert sqlite_response.status_code == 200
    assert sqlite_response["Content-Type"] == "application/vnd.sqlite3"
    assert sqlite_rows(sqlite_response.content)[0] == {
        "name": "Ada",
        "email": "ada@example.com",
    }
