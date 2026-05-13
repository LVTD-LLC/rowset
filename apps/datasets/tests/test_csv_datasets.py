import csv
import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.datasets.choices import DatasetStatus
from apps.datasets.models import Dataset, DatasetRow
from apps.datasets.services import CSVParseError, preview_csv_file
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


def create_ready_dataset(profile):
    dataset = Dataset.objects.create(
        profile=profile,
        name="People",
        original_filename="people.csv",
        source_file=csv_upload(),
        status=DatasetStatus.READY,
        headers=["name", "email"],
        preview_rows=[{"name": "Ada", "email": "ada@example.com"}],
        row_count=2,
    )
    DatasetRow.objects.create(
        dataset=dataset,
        row_number=1,
        data={"name": "Ada", "email": "ada@example.com"},
    )
    DatasetRow.objects.create(
        dataset=dataset,
        row_number=2,
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

    dataset = Dataset.objects.get(profile=profile)
    assert dataset.status == DatasetStatus.PREVIEWED
    assert dataset.source_text == "name,email\nAda,ada@example.com\nGrace,grace@example.com\n"
    assert dataset.rows.count() == 0


def test_upload_preview_rejects_oversized_csv(auth_client):
    upload = csv_upload("name,email\n" + ("Ada,ada@example.com\n" * 600_000))

    response = auth_client.post(
        reverse("dataset_upload_preview"),
        {"file": upload},
    )

    assert response.status_code == 400
    assert response.json() == {
        "ok": False,
        "error": "CSV files must be 10 MB or smaller for now.",
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
        preview_rows=[{"name": "Ada", "email": "ada@example.com"}],
        row_count=2,
    )

    import_dataset_rows(dataset.id)

    dataset.refresh_from_db()
    assert dataset.status == DatasetStatus.READY
    assert dataset.rows.count() == 2


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

    response = auth_client.post(reverse("dataset_confirm_import", args=[dataset.key]))

    assert response.status_code == 302
    dataset.refresh_from_db()
    assert dataset.status == DatasetStatus.READY
    assert dataset.confirmed_at is not None
    assert dataset.rows.count() == 2
    assert dataset.rows.first().data == {"name": "Ada", "email": "ada@example.com"}


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


def test_dataset_api_rejects_other_users_dataset(client, django_user_model, profile):
    dataset = create_ready_dataset(profile)
    other_user = django_user_model.objects.create_user(
        username="other",
        email="other@example.com",
        password="password123",
    )

    response = client.get(f"/api/datasets/{dataset.key}/rows?api_key={other_user.profile.key}")

    assert response.status_code == 404
