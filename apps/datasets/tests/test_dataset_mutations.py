import pytest
from django.urls import reverse

from apps.api.services import create_profile_dataset, create_profile_dataset_row
from apps.core.analytics import ROWSET_DATASET_ROW_MUTATED
from apps.core.services import create_agent_api_key
from apps.datasets.choices import DatasetMutationType
from apps.datasets.history import record_dataset_mutation
from apps.datasets.models import Dataset, DatasetMutation, Project
from apps.datasets.tests.dataset_test_helpers import create_ready_dataset
from apps.datasets.views import DATASET_CHANGES_PAGE_SIZE

pytestmark = pytest.mark.django_db


def test_dataset_detail_omits_row_mutation_chrome(auth_client, profile):
    dataset = create_ready_dataset(profile)

    response = auth_client.get(dataset.get_absolute_url())
    content = response.content.decode()

    assert response.status_code == 200
    assert reverse("dataset_row_create", args=[dataset.key]) not in content
    assert reverse("dataset_rows_bulk_action", args=[dataset.key]) not in content
    assert "Delete selected rows" not in content
    assert 'x-data="rowBulkActions"' not in content
    assert 'id="row-search"' not in content
    assert 'id="row-sort"' not in content


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


def test_row_update_mutation_records_field_diffs_and_renders_history(api_client, profile):
    dataset = create_ready_dataset(profile)
    row = dataset.rows.get(row_number=1)

    patch_response = api_client.patch(
        f"/api/datasets/{dataset.key}/rows/{row.id}",
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

    api_client.force_login(profile.user)
    detail_content = api_client.get(dataset.get_absolute_url()).content.decode()
    changes_content = api_client.get(dataset.get_changes_url()).content.decode()

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


def test_row_update_mutation_omits_noop_fields(api_client, profile):
    dataset = create_ready_dataset(profile)
    row = dataset.rows.get(row_number=1)

    patch_response = api_client.patch(
        f"/api/datasets/{dataset.key}/rows/{row.id}",
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


def test_dataset_api_schema_mutations_preserve_column_descriptions(api_client, profile):
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

    rename_response = api_client.post(
        f"/api/datasets/{dataset.key}/columns/rename",
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

    reorder_response = api_client.post(
        f"/api/datasets/{dataset.key}/columns/reorder",
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

    drop_response = api_client.post(
        f"/api/datasets/{dataset.key}/columns/drop",
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


def test_dataset_mutation_history_records_row_update_diffs_without_schema_backfill_values(
    api_client,
    profile,
):
    create_response = api_client.post(
        "/api/datasets",
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

    add_column_response = api_client.post(
        f"/api/datasets/{dataset.key}/columns",
        data={"name": "private_note", "default_value": "secret-default"},
        content_type="application/json",
    )
    assert add_column_response.status_code == 200

    patch_row_response = api_client.patch(
        f"/api/datasets/{dataset.key}/rows/{row.id}",
        data={"data": {"name": "New Private"}},
        content_type="application/json",
    )
    assert patch_row_response.status_code == 200

    delete_row_response = api_client.delete(f"/api/datasets/{dataset.key}/rows/{row.id}")
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
