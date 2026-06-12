import csv
import io
from urllib.request import Request

import polars as pl
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.datasets.choices import DatasetStatus
from apps.datasets.models import Dataset, DatasetRow
from apps.datasets.services import (
    GENERATED_INDEX_CHOICE,
    GOOGLE_SHEETS_FILE_TYPE,
    CSVParseError,
    TabularPreview,
    _GoogleSheetsRedirectHandler,
    fetch_google_sheet_csv,
    google_sheets_export_url,
    infer_column_type,
    preview_csv_file,
    preview_google_sheet_url,
    preview_uploaded_table,
)
from apps.datasets.tasks import import_dataset_rows

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


def test_google_sheets_export_url_accepts_share_links():
    export_url, sheet_id = google_sheets_export_url(
        "https://docs.google.com/spreadsheets/d/abc123/edit#gid=456"
    )

    assert sheet_id == "abc123"
    assert export_url == "https://docs.google.com/spreadsheets/d/abc123/export?format=csv&gid=456"


def test_google_sheets_export_url_rejects_non_google_hosts():
    with pytest.raises(CSVParseError, match="docs.google.com"):
        google_sheets_export_url("https://example.com/spreadsheets/d/abc123/edit")


def test_google_sheets_export_url_rejects_http_links():
    with pytest.raises(CSVParseError, match="docs.google.com"):
        google_sheets_export_url("http://docs.google.com/spreadsheets/d/abc123/edit")


def test_fetch_google_sheet_csv_allows_google_csv_redirects():
    handler = _GoogleSheetsRedirectHandler()

    request = handler.redirect_request(
        Request("https://docs.google.com/spreadsheets/d/abc123/export?format=csv"),
        fp=None,
        code=302,
        msg="Found",
        headers={},
        newurl="https://doc-0g-bs-sheets.googleusercontent.com/export/abc123?format=csv",
    )

    assert request.full_url == "https://doc-0g-bs-sheets.googleusercontent.com/export/abc123?format=csv"


def test_fetch_google_sheet_csv_rejects_untrusted_redirects():
    handler = _GoogleSheetsRedirectHandler()

    with pytest.raises(CSVParseError, match="download"):
        handler.redirect_request(
            Request("https://docs.google.com/spreadsheets/d/abc123/export?format=csv"),
            fp=None,
            code=302,
            msg="Found",
            headers={},
            newurl="https://evil.example/export/abc123?format=csv",
        )


def test_fetch_google_sheet_csv_rejects_http_google_csv_redirects():
    handler = _GoogleSheetsRedirectHandler()

    with pytest.raises(CSVParseError, match="download"):
        handler.redirect_request(
            Request("https://docs.google.com/spreadsheets/d/abc123/export?format=csv"),
            fp=None,
            code=302,
            msg="Found",
            headers={},
            newurl="http://doc-0g-bs-sheets.googleusercontent.com/export/abc123?format=csv",
        )


def test_fetch_google_sheet_csv_rejects_html_without_content_type(monkeypatch):
    class FakeResponse:
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self, size):
            return b"<html><body>sign in</body></html>"

    class FakeOpener:
        def open(self, request, timeout):
            return FakeResponse()

    monkeypatch.setattr("apps.datasets.services.build_opener", lambda handler: FakeOpener())

    with pytest.raises(CSVParseError, match="publicly accessible"):
        fetch_google_sheet_csv("https://docs.google.com/spreadsheets/d/abc123/export?format=csv")


def test_preview_google_sheet_url_fetches_and_parses_csv(monkeypatch):
    monkeypatch.setattr(
        "apps.datasets.services.fetch_google_sheet_csv",
        lambda export_url: "name,email\nAda,ada@example.com\nGrace,grace@example.com\n",
    )

    preview = preview_google_sheet_url("https://docs.google.com/spreadsheets/d/abc123/edit")

    assert preview.file_type == GOOGLE_SHEETS_FILE_TYPE
    assert preview.headers == ["name", "email"]
    assert preview.row_count == 2
    assert preview.preview_rows == [
        {"name": "Ada", "email": "ada@example.com"},
        {"name": "Grace", "email": "grace@example.com"},
    ]


def test_upload_preview_creates_preview_dataset(auth_client, profile):
    response = auth_client.post(
        reverse("dataset_upload_preview"),
        {"file": csv_upload()},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["dataset"]["headers"] == ["name", "email"]
    assert payload["dataset"]["column_schema"] == {
        "name": {"type": "text"},
        "email": {"type": "email"},
    }
    assert payload["dataset"]["row_count"] == 2
    assert payload["dataset"]["generated_index_choice"] == GENERATED_INDEX_CHOICE

    dataset = Dataset.objects.get(profile=profile)
    assert dataset.status == DatasetStatus.PREVIEWED
    assert dataset.column_schema == {
        "name": {"type": "text"},
        "email": {"type": "email"},
    }
    assert dataset.source_text == "name,email\nAda,ada@example.com\nGrace,grace@example.com\n"
    assert dataset.rows.count() == 0


def test_upload_preview_replaces_unconfirmed_preview_dataset(auth_client, profile):
    old_preview = Dataset.objects.create(
        profile=profile,
        name="Old preview",
        original_filename="old.csv",
        status=DatasetStatus.PREVIEWED,
        headers=["name"],
        preview_rows=[{"name": "Old"}],
        row_count=1,
    )

    response = auth_client.post(
        reverse("dataset_upload_preview"),
        {"file": csv_upload()},
    )

    assert response.status_code == 200
    assert not Dataset.objects.filter(id=old_preview.id).exists()
    assert Dataset.objects.filter(profile=profile, status=DatasetStatus.PREVIEWED).count() == 1


def test_upload_preview_keeps_existing_preview_when_new_upload_is_invalid(auth_client, profile):
    old_preview = Dataset.objects.create(
        profile=profile,
        name="Old preview",
        original_filename="old.csv",
        status=DatasetStatus.PREVIEWED,
        headers=["name"],
        preview_rows=[{"name": "Old"}],
        row_count=1,
    )

    response = auth_client.post(reverse("dataset_upload_preview"), {})

    assert response.status_code == 400
    assert Dataset.objects.filter(id=old_preview.id).exists()


def test_upload_preview_keeps_existing_preview_when_new_google_sheet_is_invalid(
    auth_client,
    profile,
    monkeypatch,
):
    old_preview = Dataset.objects.create(
        profile=profile,
        name="Old preview",
        original_filename="old.csv",
        status=DatasetStatus.PREVIEWED,
        headers=["name"],
        preview_rows=[{"name": "Old"}],
        row_count=1,
    )
    monkeypatch.setattr(
        "apps.datasets.views.preview_google_sheet_url",
        lambda url: (_ for _ in ()).throw(CSVParseError("Bad sheet")),
    )

    response = auth_client.post(
        reverse("dataset_upload_preview"),
        {"google_sheets_url": "https://docs.google.com/spreadsheets/d/abc123/edit"},
    )

    assert response.status_code == 400
    assert Dataset.objects.filter(id=old_preview.id).exists()


def test_upload_preview_creates_preview_dataset_for_parquet(auth_client, profile):
    response = auth_client.post(
        reverse("dataset_upload_preview"),
        {"file": parquet_upload()},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["dataset"]["headers"] == ["name", "email", "score"]
    assert payload["dataset"]["row_count"] == 2

    dataset = Dataset.objects.get(profile=profile)
    assert dataset.file_type == "parquet"
    assert dataset.original_filename == "people.parquet"
    assert (
        dataset.source_text
        == 'name,email,score\nAda,ada@example.com,10\nGrace,grace@example.com,""\n'
    )


def test_upload_preview_creates_preview_dataset_for_google_sheet(auth_client, profile, monkeypatch):
    monkeypatch.setattr(
        "apps.datasets.views.preview_google_sheet_url",
        lambda url: TabularPreview(
            headers=["name", "email"],
            preview_rows=[{"name": "Ada", "email": "ada@example.com"}],
            row_count=1,
            source_text="name,email\nAda,ada@example.com\n",
            file_type=GOOGLE_SHEETS_FILE_TYPE,
        ),
    )

    response = auth_client.post(
        reverse("dataset_upload_preview"),
        {"google_sheets_url": "https://docs.google.com/spreadsheets/d/abc123/edit"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["dataset"]["headers"] == ["name", "email"]

    dataset = Dataset.objects.get(profile=profile)
    assert dataset.file_type == GOOGLE_SHEETS_FILE_TYPE
    assert dataset.source_file.name == ""
    assert dataset.source_url == "https://docs.google.com/spreadsheets/d/abc123/edit"
    assert dataset.source_text == "name,email\nAda,ada@example.com\n"


def test_upload_preview_rejects_expanded_dataset_content_over_limit(auth_client, monkeypatch):
    def oversized_preview(uploaded_file, filename):
        return TabularPreview(
            headers=["name"],
            preview_rows=[{"name": "Ada"}],
            row_count=1,
            source_text="name\n" + ("Ada\n" * 3_000_000),
            file_type="parquet",
        )

    monkeypatch.setattr("apps.datasets.views.preview_uploaded_table", oversized_preview)

    response = auth_client.post(
        reverse("dataset_upload_preview"),
        {"file": parquet_upload()},
    )

    assert response.status_code == 400
    assert response.json() == {
        "ok": False,
        "error": "Parsed dataset content must be 10 MB or smaller for now.",
    }


def test_upload_preview_rejects_oversized_csv(auth_client):
    upload = csv_upload("name,email\n" + ("Ada,ada@example.com\n" * 600_000))

    response = auth_client.post(
        reverse("dataset_upload_preview"),
        {"file": upload},
    )

    assert response.status_code == 400
    assert response.json() == {
        "ok": False,
        "error": "Dataset files must be 10 MB or smaller for now.",
    }


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


def test_confirm_import_enqueues_and_imports_rows(auth_client, profile, monkeypatch):
    dataset = Dataset.objects.create(
        profile=profile,
        name="People",
        original_filename="people.csv",
        source_file=csv_upload(),
        source_text="name,email\nAda,ada@example.com\nGrace,grace@example.com\n",
        status=DatasetStatus.PREVIEWED,
        headers=["name", "email"],
        preview_rows=[{"name": "Ada", "email": "ada@example.com"}],
        row_count=2,
    )

    def run_sync(func_path, dataset_id, **kwargs):
        assert func_path == "apps.datasets.tasks.import_dataset_rows"
        return import_dataset_rows(dataset_id)

    monkeypatch.setattr("apps.datasets.views.async_task", run_sync)

    response = auth_client.post(
        reverse("dataset_confirm_import", args=[dataset.key]),
        {"index_column": "email"},
    )

    assert response.status_code == 302
    dataset.refresh_from_db()
    assert dataset.status == DatasetStatus.READY
    assert dataset.confirmed_at is not None
    assert dataset.rows.count() == 2
    assert dataset.index_column == "email"
    assert dataset.column_schema == {
        "name": {"type": "text"},
        "email": {"type": "email"},
    }
    assert dataset.rows.first().index_value == "ada@example.com"
    assert dataset.rows.first().data == {"name": "Ada", "email": "ada@example.com"}


def test_confirm_import_persists_user_selected_column_types(auth_client, profile, monkeypatch):
    dataset = Dataset.objects.create(
        profile=profile,
        name="People",
        original_filename="people.csv",
        source_file=csv_upload(),
        source_text="name,email\nAda,ada@example.com\nGrace,grace@example.com\n",
        status=DatasetStatus.PREVIEWED,
        headers=["name", "email"],
        column_schema={"name": {"type": "text"}, "email": {"type": "email"}},
        preview_rows=[{"name": "Ada", "email": "ada@example.com"}],
        row_count=2,
    )

    monkeypatch.setattr(
        "apps.datasets.views.async_task",
        lambda func_path, dataset_id, **kwargs: import_dataset_rows(dataset_id),
    )

    response = auth_client.post(
        reverse("dataset_confirm_import", args=[dataset.key]),
        {
            "index_column": GENERATED_INDEX_CHOICE,
            "column_types": '{"name":"text","email":"text"}',
        },
    )

    assert response.status_code == 302
    dataset.refresh_from_db()
    assert dataset.headers == ["filebridge_id", "name", "email"]
    assert dataset.column_schema == {
        "filebridge_id": {"type": "integer"},
        "name": {"type": "text"},
        "email": {"type": "text"},
    }


def test_confirm_import_file_fallback_validates_selected_index(auth_client, profile, monkeypatch):
    dataset = Dataset.objects.create(
        profile=profile,
        name="People",
        original_filename="people.csv",
        source_file=csv_upload(),
        source_text="",
        status=DatasetStatus.PREVIEWED,
        headers=["name", "email"],
        preview_rows=[{"name": "Ada", "email": "ada@example.com"}],
        row_count=2,
    )

    monkeypatch.setattr(
        "apps.datasets.views.async_task",
        lambda func_path, dataset_id, **kwargs: import_dataset_rows(dataset_id),
    )

    response = auth_client.post(
        reverse("dataset_confirm_import", args=[dataset.key]),
        {"index_column": "email"},
    )

    assert response.status_code == 302
    dataset.refresh_from_db()
    assert dataset.status == DatasetStatus.READY
    assert dataset.rows.first().index_value == "ada@example.com"


def test_confirm_import_rejects_missing_google_sheets_source_text(auth_client, profile):
    dataset = Dataset.objects.create(
        profile=profile,
        name="People",
        original_filename="Google Sheets import",
        file_type=GOOGLE_SHEETS_FILE_TYPE,
        source_url="https://docs.google.com/spreadsheets/d/abc123/edit",
        source_text="",
        status=DatasetStatus.PREVIEWED,
        headers=["name", "email"],
        preview_rows=[{"name": "Ada", "email": "ada@example.com"}],
        row_count=2,
    )

    response = auth_client.post(
        reverse("dataset_confirm_import", args=[dataset.key]),
        {"index_column": "email"},
    )

    assert response.status_code == 400
    assert "stored dataset content" in response.json()["error"]


def test_confirm_import_rejects_duplicate_index_column(auth_client, profile):
    dataset = Dataset.objects.create(
        profile=profile,
        name="People",
        original_filename="people.csv",
        source_file=csv_upload("name,email\nAda,same@example.com\nGrace,same@example.com\n"),
        source_text="name,email\nAda,same@example.com\nGrace,same@example.com\n",
        status=DatasetStatus.PREVIEWED,
        headers=["name", "email"],
        preview_rows=[{"name": "Ada", "email": "same@example.com"}],
        row_count=2,
    )

    response = auth_client.post(
        reverse("dataset_confirm_import", args=[dataset.key]),
        {"index_column": "email"},
    )

    assert response.status_code == 400
    assert "must be unique" in response.json()["error"]


def test_confirm_import_can_generate_index_column(auth_client, profile, monkeypatch):
    dataset = Dataset.objects.create(
        profile=profile,
        name="People",
        original_filename="people.csv",
        source_file=csv_upload(),
        source_text="name,email\nAda,ada@example.com\nGrace,grace@example.com\n",
        status=DatasetStatus.PREVIEWED,
        headers=["name", "email"],
        preview_rows=[{"name": "Ada", "email": "ada@example.com"}],
        row_count=2,
    )

    monkeypatch.setattr(
        "apps.datasets.views.async_task",
        lambda func_path, dataset_id, **kwargs: import_dataset_rows(dataset_id),
    )

    response = auth_client.post(
        reverse("dataset_confirm_import", args=[dataset.key]),
        {"index_column": GENERATED_INDEX_CHOICE},
    )

    assert response.status_code == 302
    dataset.refresh_from_db()
    assert dataset.index_column == "filebridge_id"
    assert dataset.index_generated is True
    assert dataset.headers == ["filebridge_id", "name", "email"]
    assert dataset.column_schema["filebridge_id"] == {"type": "integer"}
    assert dataset.rows.first().index_value == "1"
    assert dataset.rows.first().data == {
        "filebridge_id": "1",
        "name": "Ada",
        "email": "ada@example.com",
    }


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
    assert (
        response["Content-Disposition"]
        == 'attachment; filename="R&D \\"People\\"-2026.csv"'
    )


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


def test_dataset_api_creates_ready_dataset_with_explicit_index(client, profile):
    response = client.post(
        "/api/datasets",
        data={
            "name": "Products",
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
    assert dataset.headers == ["filebridge_id", "task"]
    assert dataset.column_schema == {
        "filebridge_id": {"type": "integer"},
        "task": {"type": "text"},
    }
    assert dataset.index_column == "filebridge_id"
    assert dataset.index_generated is True
    assert dataset.rows.first().data == {"filebridge_id": "1", "task": "Draft"}

    create_response = client.post(
        f"/api/datasets/{dataset.key}/rows?api_key={profile.key}",
        data={"data": {"filebridge_id": "custom", "task": "Ship"}},
        content_type="application/json",
    )

    assert create_response.status_code == 200
    assert create_response.json()["row"]["index_value"] == "2"
    assert create_response.json()["row"]["data"] == {"filebridge_id": "2", "task": "Ship"}


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
    dataset.index_column = "filebridge_id"
    dataset.index_generated = True
    dataset.headers = ["filebridge_id", "name", "email"]
    dataset.save(update_fields=["index_column", "index_generated", "headers"])
    row = dataset.rows.first()
    row.index_value = "1"
    row.data = {"filebridge_id": "1", **row.data}
    row.save(update_fields=["index_value", "data"])

    response = client.patch(
        f"/api/datasets/{dataset.key}/rows/{row.id}?api_key={profile.key}",
        data={"data": {"filebridge_id": "custom"}},
        content_type="application/json",
    )

    assert response.status_code == 400
    assert "managed by FileBridge" in response.json()["detail"]


def test_dataset_api_rejects_other_users_dataset(client, django_user_model, profile):
    dataset = create_ready_dataset(profile)
    other_user = django_user_model.objects.create_user(
        username="other",
        email="other@example.com",
        password="password123",
    )

    response = client.get(f"/api/datasets/{dataset.key}/rows?api_key={other_user.profile.key}")

    assert response.status_code == 404


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
