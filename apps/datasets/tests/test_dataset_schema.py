import re

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.api.services import serialize_dataset_detail
from apps.datasets.choices import DatasetColumnType, DatasetMutationType
from apps.datasets.models import Dataset, DatasetRow
from apps.datasets.services import (
    choice_constraints_from_schema,
    infer_column_type,
    normalize_column_schema,
)
from apps.datasets.tests.dataset_test_helpers import (
    create_choice_status_dataset,
    create_ready_dataset,
)

pytestmark = pytest.mark.django_db


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


def test_dataset_detail_keeps_choice_values_plain_when_colorize_is_disabled(
    auth_client,
    profile,
):
    profile.choice_colorization_enabled = False
    profile.save(update_fields=["choice_colorization_enabled"])
    dataset = create_choice_status_dataset(profile)

    response = auth_client.get(dataset.get_absolute_url())
    content = response.content.decode()

    assert response.status_code == 200
    first_status_cell = response.context["rows_with_values"][0]["cells"][1]
    assert "is_choice" not in first_status_cell
    assert "choice_accent_class" not in first_status_cell
    assert "fb-choice-pill" not in content
    assert '<a href="/datasets/' in content
    assert re.search(r">\s*todo\s*</a>", content)


def test_dataset_detail_renders_choice_values_with_color_accents_when_enabled(
    auth_client,
    profile,
):
    profile.choice_colorization_enabled = True
    profile.save(update_fields=["choice_colorization_enabled"])
    dataset = create_choice_status_dataset(profile)

    response = auth_client.get(dataset.get_absolute_url())
    content = response.content.decode()

    assert response.status_code == 200
    first_status_cell = response.context["rows_with_values"][0]["cells"][1]
    second_status_cell = response.context["rows_with_values"][1]["cells"][1]
    ad_hoc_status_cell = response.context["rows_with_values"][2]["cells"][1]
    assert first_status_cell["is_choice"]
    assert first_status_cell["choice_accent_class"] != second_status_cell["choice_accent_class"]
    assert ad_hoc_status_cell["is_choice"]
    assert ad_hoc_status_cell["choice_accent_class"] != second_status_cell["choice_accent_class"]
    assert 'class="fb-focus fb-choice-pill' in content
    assert '<span class="truncate">todo</span>' in content
    assert '<span class="truncate">done</span>' in content
    assert '<span class="truncate">paused</span>' in content
    dataset.refresh_from_db()
    assert dataset.rows.get(index_value="TASK-1").data["status"] == "todo"


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
    assert re.search(r'name="filter_2"\s+value="P1"\s+checked', content)
    assert "TASK-1" in content
    assert "TASK-2" not in content
    assert "TASK-3" not in content

    multi_response = auth_client.get(
        dataset.get_absolute_url(),
        {"filter_2": ["P1", "P2"]},
    )
    multi_content = multi_response.content.decode()

    assert multi_response.status_code == 200
    assert multi_response.context["row_page_obj"].paginator.count == 2
    assert multi_response.context["row_filter_fields"][2]["selected_values"] == ["P1", "P2"]
    assert re.search(r'name="filter_2"\s+value="P1"\s+checked', multi_content)
    assert re.search(r'name="filter_2"\s+value="P2"\s+checked', multi_content)
    assert re.search(r'type="hidden"\s+name="filter_2"\s+value="P1"', multi_content)
    assert re.search(r'type="hidden"\s+name="filter_2"\s+value="P2"', multi_content)
    assert "2 choices selected" in multi_content
    assert "TASK-1" in multi_content
    assert "TASK-2" not in multi_content
    assert "TASK-3" in multi_content


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


def test_choice_constraints_from_normalized_schema_allows_none():
    assert choice_constraints_from_schema(["status"], None, normalized=True) == {}


def test_dataset_api_dataset_reference_columns_accept_archived_datasets(api_client, profile):
    target = create_ready_dataset(profile)
    target.name = "Review Gate First Implementation Tasks"
    target.archived_at = timezone.now()
    target.save(update_fields=["name", "archived_at"])

    response = api_client.post(
        "/api/datasets",
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


def test_dataset_api_dataset_reference_columns_reject_missing_datasets(api_client, profile):
    missing_key = "38698383-f515-4b60-b426-4f4ae3bc94ce"

    response = api_client.post(
        "/api/datasets",
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


def test_dataset_api_dataset_reference_columns_canonicalize_row_writes(api_client, profile):
    target = create_ready_dataset(profile)
    source = Dataset.objects.create(
        profile=profile,
        name="Sprint history",
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
    )

    create_response = api_client.post(
        f"/api/datasets/{source.key}/rows",
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

    invalid_patch = api_client.patch(
        f"/api/datasets/{source.key}/rows/{row.id}",
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


def test_dataset_api_enforces_choice_values(api_client, profile):
    create_response = api_client.post(
        "/api/datasets",
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

    invalid_create = api_client.post(
        f"/api/datasets/{dataset.key}/rows",
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

    valid_create = api_client.post(
        f"/api/datasets/{dataset.key}/rows",
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
    invalid_patch = api_client.patch(
        f"/api/datasets/{dataset.key}/rows/{row.id}",
        data={"data": {"status": "Blocked"}},
        content_type="application/json",
    )

    assert invalid_patch.status_code == 400
    assert invalid_patch.json()["detail"] == (
        "Column 'status' must be blank or one of: Ready to do, Doing, Done."
    )
    row.refresh_from_db()
    assert row.data["status"] == "Ready to do"

    valid_patch = api_client.patch(
        f"/api/datasets/{dataset.key}/rows/{row.id}",
        data={"data": {"status": " done "}},
        content_type="application/json",
    )

    assert valid_patch.status_code == 200
    assert valid_patch.json()["row"]["data"]["status"] == "Done"

    enum_style_patch = api_client.patch(
        f"/api/datasets/{dataset.key}/rows/{row.id}",
        data={"data": {"status": "_ready_to_do-"}},
        content_type="application/json",
    )

    assert enum_style_patch.status_code == 200
    assert enum_style_patch.json()["row"]["data"]["status"] == "Ready to do"


def test_dataset_api_rejects_choice_column_without_choices(api_client, profile):
    response = api_client.post(
        "/api/datasets",
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


def test_dataset_api_rejects_existing_values_when_setting_choice_schema(api_client, profile):
    dataset = create_ready_dataset(profile)

    response = api_client.patch(
        f"/api/datasets/{dataset.key}/column-types",
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


def test_dataset_api_choice_schema_ignores_stale_preview_rows(api_client, profile):
    dataset = create_ready_dataset(profile)
    row = dataset.rows.get(index_value="ada@example.com")

    patch_response = api_client.patch(
        f"/api/datasets/{dataset.key}/rows/{row.id}",
        data={"data": {"name": "Ada Lovelace"}},
        content_type="application/json",
    )
    assert patch_response.status_code == 200

    dataset.refresh_from_db()
    assert dataset.preview_rows == [{"name": "Ada", "email": "ada@example.com"}]
    assert dataset.rows.get(index_value="ada@example.com").data["name"] == "Ada Lovelace"

    response = api_client.patch(
        f"/api/datasets/{dataset.key}/column-types",
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


def test_dataset_api_adds_choice_column_and_validates_default(api_client, profile):
    dataset = create_ready_dataset(profile)

    response = api_client.post(
        f"/api/datasets/{dataset.key}/columns",
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

    invalid_response = api_client.post(
        f"/api/datasets/{dataset.key}/columns",
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


def test_dataset_api_updates_column_types(api_client, profile):
    dataset = create_ready_dataset(profile)

    response = api_client.patch(
        f"/api/datasets/{dataset.key}/column-types",
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


def test_dataset_api_adds_column_and_backfills_existing_rows(api_client, profile):
    dataset = create_ready_dataset(profile)

    response = api_client.post(
        f"/api/datasets/{dataset.key}/columns",
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


def test_dataset_api_add_column_backfills_rows_across_bulk_update_chunks(api_client, profile):
    dataset = Dataset.objects.create(
        profile=profile,
        name="Large People",
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

    response = api_client.post(
        f"/api/datasets/{dataset.key}/columns",
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


def test_dataset_api_renames_column_and_preserves_values(api_client, profile):
    dataset = create_ready_dataset(profile)

    response = api_client.post(
        f"/api/datasets/{dataset.key}/columns/rename",
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


def test_dataset_api_rename_only_stringifies_renamed_value(api_client, profile):
    dataset = Dataset.objects.create(
        profile=profile,
        name="Mixed",
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

    response = api_client.post(
        f"/api/datasets/{dataset.key}/columns/rename",
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


def test_dataset_api_drops_non_index_column(api_client, profile):
    dataset = create_ready_dataset(profile)

    response = api_client.post(
        f"/api/datasets/{dataset.key}/columns/drop",
        data={"name": "name"},
        content_type="application/json",
    )

    assert response.status_code == 200
    assert response.json()["dataset"]["headers"] == ["email"]
    dataset.refresh_from_db()
    assert dataset.headers == ["email"]
    assert dataset.column_schema == {"email": {"type": "text"}}
    assert dataset.rows.first().data == {"email": "ada@example.com"}


def test_dataset_api_rejects_dropping_index_column(api_client, profile):
    dataset = create_ready_dataset(profile)

    response = api_client.post(
        f"/api/datasets/{dataset.key}/columns/drop",
        data={"name": "email"},
        content_type="application/json",
    )

    assert response.status_code == 400
    assert "Index column" in response.json()["detail"]
    dataset.refresh_from_db()
    assert dataset.headers == ["name", "email"]


def test_dataset_api_reorders_columns(api_client, profile):
    dataset = create_ready_dataset(profile)

    response = api_client.post(
        f"/api/datasets/{dataset.key}/columns/reorder",
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


def test_dataset_api_rejects_unknown_column_type_header(api_client, profile):
    dataset = create_ready_dataset(profile)

    response = api_client.patch(
        f"/api/datasets/{dataset.key}/column-types",
        data={"column_types": {"missing": "text"}},
        content_type="application/json",
    )

    assert response.status_code == 400
    assert "unknown headers" in response.json()["detail"]


def test_dataset_settings_shows_choice_values_with_color_accents(auth_client, profile):
    dataset = create_choice_status_dataset(profile)

    response = auth_client.get(dataset.get_settings_url())
    content = response.content.decode()

    assert response.status_code == 200
    assert "Choice values" in content
    assert 'class="fb-choice-pill fb-choice-pill-' in content
    assert '<span class="truncate">todo</span>' in content
    assert '<span class="truncate">doing</span>' in content
    assert '<span class="truncate">blocked</span>' in content
    assert '<span class="truncate">done</span>' in content


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
