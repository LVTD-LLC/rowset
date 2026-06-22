import csv
import io

import polars as pl
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.datasets.choices import DatasetStatus
from apps.datasets.models import Dataset, DatasetRow, Project
from apps.datasets.services import (
    CSVParseError,
    infer_column_type,
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


def test_dataset_detail_orders_sample_cells_by_headers(auth_client, profile):
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
    customer_id_position = content.index(">C-1001<")
    name_position = content.index(">Ada Lovelace<")
    plan_position = content.index(">Scale<")
    assert customer_id_position < name_position < plan_position


def test_dataset_detail_uses_export_menu_and_hides_duplicate_schema(auth_client, profile):
    dataset = create_ready_dataset(profile)

    response = auth_client.get(dataset.get_absolute_url())

    content = response.content.decode()
    assert response.status_code == 200
    assert "Sample rows" in content
    assert 'id="schema-heading"' not in content
    assert "Dataset API" not in content
    assert "Export CSV" not in content
    assert "Export Parquet" not in content
    assert "CSV snapshot" in content
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
    customer_id_position = content.index(">C-1001<")
    name_position = content.index(">Ada Lovelace<")
    plan_position = content.index(">Scale<")
    assert customer_id_position < name_position < plan_position


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
