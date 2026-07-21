import csv
import io
import json

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.core.services import create_agent_api_key
from apps.datasets.choices import DatasetMutationType
from apps.datasets.models import DatasetRow, Project
from apps.datasets.tests.dataset_test_helpers import (
    configure_filterable_dataset,
    create_ready_dataset,
)

pytestmark = pytest.mark.django_db


def test_dataset_api_crud_and_export(api_client, profile):
    dataset = create_ready_dataset(profile)

    list_response = api_client.get(f"/api/datasets/{dataset.key}/rows")
    assert list_response.status_code == 200
    assert list_response.json()["count"] == 2

    public_key_list_response = api_client.get(f"/api/datasets/{dataset.public_key}/rows")
    assert public_key_list_response.status_code == 200
    assert public_key_list_response.json()["dataset"] == str(dataset.key)

    create_response = api_client.post(
        f"/api/datasets/{dataset.public_key}/rows",
        data={"data": {"name": "Katherine", "email": "kat@example.com"}},
        content_type="application/json",
    )
    assert create_response.status_code == 200
    assert create_response.json()["dataset"] == str(dataset.key)
    row_id = create_response.json()["row"]["id"]
    assert create_response.json()["row"]["index_value"] == "kat@example.com"

    missing_index_patch_response = api_client.patch(
        f"/api/datasets/{dataset.key}/rows/by-index?index_value=missing@example.com",
        data={"data": {"name": "Missing"}},
        content_type="application/json",
    )
    assert missing_index_patch_response.status_code == 404

    conflicting_index_patch_response = api_client.patch(
        f"/api/datasets/{dataset.key}/rows/by-index?index_value=kat@example.com",
        data={"data": {"email": "ada@example.com"}},
        content_type="application/json",
    )
    assert conflicting_index_patch_response.status_code == 409

    get_by_index_response = api_client.get(
        f"/api/datasets/{dataset.key}/rows/by-index?index_value=kat@example.com"
    )
    assert get_by_index_response.status_code == 200
    assert get_by_index_response.json()["row"]["data"]["name"] == "Katherine"

    patch_by_index_response = api_client.patch(
        f"/api/datasets/{dataset.key}/rows/by-index?index_value=kat@example.com",
        data={"data": {"name": "Katherine Johnson", "email": "katherine.johnson@example.com"}},
        content_type="application/json",
    )
    assert patch_by_index_response.status_code == 200
    assert patch_by_index_response.json()["row"]["id"] == row_id
    assert patch_by_index_response.json()["row"]["index_value"] == "katherine.johnson@example.com"
    assert patch_by_index_response.json()["row"]["data"]["name"] == "Katherine Johnson"

    get_updated_index_response = api_client.get(
        f"/api/datasets/{dataset.key}/rows/by-index?index_value=katherine.johnson@example.com"
    )
    assert get_updated_index_response.status_code == 200
    assert get_updated_index_response.json()["row"]["id"] == row_id

    patch_response = api_client.patch(
        f"/api/datasets/{dataset.public_key}/rows/{row_id}",
        data={"data": {"email": "katherine@example.com", "ignored": "nope"}},
        content_type="application/json",
    )
    assert patch_response.status_code == 200
    assert patch_response.json()["dataset"] == str(dataset.key)
    assert patch_response.json()["row"]["data"] == {
        "name": "Katherine Johnson",
        "email": "katherine@example.com",
    }

    export_response = api_client.get(f"/api/datasets/{dataset.key}/export.csv")
    assert export_response.status_code == 200
    exported = list(csv.DictReader(io.StringIO(export_response.content.decode())))
    assert exported[0] == {"name": "Ada", "email": "ada@example.com"}

    delete_response = api_client.delete(f"/api/datasets/{dataset.public_key}/rows/{row_id}")
    assert delete_response.status_code == 200
    assert delete_response.json()["dataset"] == str(dataset.key)
    assert not DatasetRow.objects.filter(id=row_id).exists()


def test_dataset_api_filters_and_sorts_rows(api_client, profile):
    dataset = configure_filterable_dataset(create_ready_dataset(profile))

    filtered_response = api_client.get(
        f"/api/datasets/{dataset.key}/rows",
        {
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

    search_response = api_client.get(
        f"/api/datasets/{dataset.key}/rows",
        {
            "query": "grace",
            "sort": "score",
        },
    )

    assert search_response.status_code == 200
    assert search_response.json()["count"] == 1
    assert search_response.json()["rows"][0]["data"]["name"] == "Grace Hopper"

    invalid_sort_response = api_client.get(
        f"/api/datasets/{dataset.key}/rows",
        {"sort": "missing"},
    )
    assert invalid_sort_response.status_code == 400
    assert "Row sort" in invalid_sort_response.json()["detail"]

    invalid_filter_response = api_client.get(
        f"/api/datasets/{dataset.key}/rows",
        {
            "filters": json.dumps({"missing": "value"}),
        },
    )
    assert invalid_filter_response.status_code == 400
    assert "not in this dataset" in invalid_filter_response.json()["detail"]

    malformed_filters_response = api_client.get(
        f"/api/datasets/{dataset.key}/rows",
        {"filters": "not-json"},
    )
    assert malformed_filters_response.status_code == 400
    assert "filters must be a JSON object" in malformed_filters_response.json()["detail"]


def test_dataset_api_archives_and_restores_dataset(api_client, profile):
    project = Project.objects.create(profile=profile, name="Cleanup")
    dataset = create_ready_dataset(profile)
    dataset.project = project
    dataset.public_enabled = True
    dataset.save(update_fields=["project", "public_enabled"])
    public_url = reverse("public_dataset", args=[dataset.public_key])

    archive_response = api_client.delete(f"/api/datasets/{dataset.key}")

    assert archive_response.status_code == 200
    assert archive_response.json()["message"] == "Dataset archived."
    dataset.refresh_from_db()
    assert dataset.archived_at is not None
    assert dataset.public_enabled is False
    assert DatasetRow.objects.filter(dataset=dataset).count() == 2

    list_response = api_client.get("/api/datasets")
    assert list_response.status_code == 200
    assert list_response.json()["datasets"] == []

    project_response = api_client.get(f"/api/projects/{project.key}")
    assert project_response.status_code == 200
    assert project_response.json()["project"]["dataset_count"] == 0
    assert project_response.json()["datasets"]["datasets"] == []

    public_response = api_client.get(public_url)
    assert public_response.status_code == 404

    already_archived_response = api_client.delete(f"/api/datasets/{dataset.key}")
    assert already_archived_response.status_code == 200
    assert already_archived_response.json()["message"] == "Dataset was already archived."

    restore_response = api_client.post(f"/api/datasets/{dataset.key}/restore")

    assert restore_response.status_code == 200
    assert restore_response.json()["message"] == "Dataset restored."
    dataset.refresh_from_db()
    assert dataset.archived_at is None
    assert dataset.public_enabled is False

    already_restored_response = api_client.post(f"/api/datasets/{dataset.key}/restore")
    assert already_restored_response.status_code == 200
    assert already_restored_response.json()["message"] == "Dataset was not archived."

    restored_list_response = api_client.get("/api/datasets")
    assert restored_list_response.status_code == 200
    assert [item["key"] for item in restored_list_response.json()["datasets"]] == [str(dataset.key)]
    assert list(dataset.mutations.values_list("mutation_type", flat=True)) == [
        DatasetMutationType.DATASET_RESTORED,
        DatasetMutationType.DATASET_ARCHIVED,
    ]


def test_archiving_already_archived_dataset_records_public_preview_disable(api_client, profile):
    dataset = create_ready_dataset(profile)
    dataset.archived_at = timezone.now()
    dataset.public_enabled = True
    dataset.save(update_fields=["archived_at", "public_enabled"])

    response = api_client.delete(f"/api/datasets/{dataset.key}")

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


def test_dataset_api_lists_archived_datasets_separately(api_client, profile):
    active_dataset = create_ready_dataset(profile)
    archived_dataset = create_ready_dataset(profile)
    archived_dataset.name = "Archived people"
    archived_dataset.archived_at = timezone.now()
    archived_dataset.save(update_fields=["name", "archived_at"])

    archived_response = api_client.get("/api/datasets/archived")

    assert archived_response.status_code == 200
    assert archived_response.json()["total_count"] == 1
    assert [item["key"] for item in archived_response.json()["datasets"]] == [
        str(archived_dataset.key)
    ]
    assert archived_response.json()["datasets"][0]["name"] == "Archived people"
    assert archived_response.json()["datasets"][0]["archived_at"] is not None

    active_response = api_client.get("/api/datasets")
    assert active_response.status_code == 200
    assert [item["key"] for item in active_response.json()["datasets"]] == [str(active_dataset.key)]


def test_dataset_api_updates_dataset_metadata(api_client, profile):
    dataset = create_ready_dataset(profile)
    dataset.description = "Initial task board."
    dataset.instructions = "Use todo, doing, and done."
    dataset.metadata = {"status_order": ["todo", "doing", "done"]}
    dataset.save(update_fields=["description", "instructions", "metadata"])

    response = api_client.patch(
        f"/api/datasets/{dataset.key}/metadata",
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


def test_dataset_api_rejects_non_object_dataset_metadata(api_client, profile):
    dataset = create_ready_dataset(profile)

    response = api_client.patch(
        f"/api/datasets/{dataset.key}/metadata",
        data={"metadata": ["not", "an", "object"]},
        content_type="application/json",
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "payload", "metadata"]
    dataset.refresh_from_db()
    assert dataset.metadata == {}


def test_dataset_api_treats_null_dataset_metadata_fields_as_omitted(api_client, profile):
    dataset = create_ready_dataset(profile)
    dataset.description = "Initial task board."
    dataset.instructions = "Use todo, doing, and done."
    dataset.metadata = {"status_order": ["todo", "doing", "done"]}
    dataset.save(update_fields=["description", "instructions", "metadata"])

    response = api_client.patch(
        f"/api/datasets/{dataset.key}/metadata",
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


def test_dataset_api_reports_no_dataset_metadata_changes(api_client, profile):
    dataset = create_ready_dataset(profile)
    dataset.description = "Initial task board."
    dataset.instructions = "Use todo, doing, and done."
    dataset.metadata = {"status_order": ["todo", "doing", "done"]}
    dataset.save(update_fields=["description", "instructions", "metadata"])

    response = api_client.patch(
        f"/api/datasets/{dataset.key}/metadata",
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


def test_dataset_api_rejects_patch_to_generated_index(api_client, profile):
    dataset = create_ready_dataset(profile)
    dataset.index_column = "rowset_id"
    dataset.index_generated = True
    dataset.headers = ["rowset_id", "name", "email"]
    dataset.save(update_fields=["index_column", "index_generated", "headers"])
    row = dataset.rows.first()
    row.index_value = "1"
    row.data = {"rowset_id": "1", **row.data}
    row.save(update_fields=["index_value", "data"])

    response = api_client.patch(
        f"/api/datasets/{dataset.key}/rows/{row.id}",
        data={"data": {"rowset_id": "custom"}},
        content_type="application/json",
    )

    assert response.status_code == 400
    assert "managed by Rowset" in response.json()["detail"]

    by_index_response = api_client.patch(
        f"/api/datasets/{dataset.key}/rows/by-index?index_value=1",
        data={"data": {"rowset_id": "custom"}},
        content_type="application/json",
    )

    assert by_index_response.status_code == 400
    assert "managed by Rowset" in by_index_response.json()["detail"]

    idempotent_response = api_client.patch(
        f"/api/datasets/{dataset.key}/rows/{row.id}",
        data={"data": {"rowset_id": "1", "name": "Ada Updated"}},
        content_type="application/json",
    )

    assert idempotent_response.status_code == 200
    assert idempotent_response.json()["row"]["index_value"] == "1"
    assert idempotent_response.json()["row"]["data"]["name"] == "Ada Updated"

    idempotent_by_index_response = api_client.patch(
        f"/api/datasets/{dataset.key}/rows/by-index?index_value=1",
        data={"data": {"rowset_id": "1", "name": "Ada By Index"}},
        content_type="application/json",
    )

    assert idempotent_by_index_response.status_code == 200
    assert idempotent_by_index_response.json()["row"]["index_value"] == "1"
    assert idempotent_by_index_response.json()["row"]["data"]["name"] == "Ada By Index"


def test_dataset_api_rejects_other_users_dataset(api_client, django_user_model, profile):
    dataset = create_ready_dataset(profile)
    other_user = django_user_model.objects.create_user(
        username="other",
        email="other@example.com",
        password="password123",
    )
    other_credential = create_agent_api_key(other_user.profile, "Other Agent")

    response = api_client.get(
        f"/api/datasets/{dataset.key}/rows",
        HTTP_AUTHORIZATION=f"Bearer {other_credential.raw_key}",
    )

    assert response.status_code == 404

    public_key_response = api_client.get(
        f"/api/datasets/{dataset.public_key}/rows",
        HTTP_AUTHORIZATION=f"Bearer {other_credential.raw_key}",
    )

    assert public_key_response.status_code == 404
