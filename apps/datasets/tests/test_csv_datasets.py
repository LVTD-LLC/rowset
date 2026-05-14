import csv
import io

import polars as pl
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.datasets.choices import DatasetStatus
from apps.datasets.models import Dataset, DatasetRow
from apps.datasets.services import (
    GENERATED_INDEX_CHOICE,
    CSVParseError,
    TabularPreview,
    preview_csv_file,
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


def test_upload_preview_creates_preview_dataset(auth_client, profile):
    response = auth_client.post(
        reverse("dataset_upload_preview"),
        {"file": csv_upload()},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["dataset"]["headers"] == ["name", "email"]
    assert payload["dataset"]["row_count"] == 2
    assert payload["dataset"]["generated_index_choice"] == GENERATED_INDEX_CHOICE

    dataset = Dataset.objects.get(profile=profile)
    assert dataset.status == DatasetStatus.PREVIEWED
    assert dataset.source_text == "name,email\nAda,ada@example.com\nGrace,grace@example.com\n"
    assert dataset.rows.count() == 0


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
    assert dataset.rows.first().index_value == "ada@example.com"
    assert dataset.rows.first().data == {"name": "Ada", "email": "ada@example.com"}


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
    assert dataset.rows.first().index_value == "1"
    assert dataset.rows.first().data == {
        "filebridge_id": "1",
        "name": "Ada",
        "email": "ada@example.com",
    }


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
