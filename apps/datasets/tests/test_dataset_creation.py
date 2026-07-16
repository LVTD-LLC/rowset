import pytest

from apps.api.services import DatasetServiceError, create_profile_dataset
from apps.core.analytics import ROWSET_DATASET_CREATED
from apps.core.choices import ProfileStates
from apps.datasets.models import Dataset, Project

pytestmark = pytest.mark.django_db


def test_dataset_api_creates_ready_dataset_with_explicit_index(client, profile):
    project = Project.objects.create(profile=profile, name="Catalogs")

    response = client.post(
        "/api/datasets",
        data={
            "name": "Products",
            "description": "Supplier product catalog for the agent-managed store.",
            "instructions": "Keep sku stable. Treat price as USD unless a row says otherwise.",
            "metadata": {
                "workflow": {
                    "status_values": ["draft", "active", "retired"],
                    "default_status": "draft",
                }
            },
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
    assert payload["dataset"]["description"] == (
        "Supplier product catalog for the agent-managed store."
    )
    assert payload["dataset"]["instructions"] == (
        "Keep sku stable. Treat price as USD unless a row says otherwise."
    )
    assert payload["dataset"]["metadata"] == {
        "workflow": {
            "status_values": ["draft", "active", "retired"],
            "default_status": "draft",
        }
    }
    assert payload["dataset"]["project"] == {
        "key": str(project.key),
        "name": "Catalogs",
        "description": "",
    }
    assert payload["dataset"]["index_column"] == "sku"
    assert payload["dataset"]["column_schema"] == {
        "sku": {"type": "text"},
        "name": {"type": "text"},
        "price": {"type": "currency"},
    }
    assert payload["dataset"]["row_count"] == 2

    dataset = Dataset.objects.get(key=payload["dataset"]["key"], profile=profile)
    assert dataset.project == project
    assert dataset.description == "Supplier product catalog for the agent-managed store."
    assert dataset.instructions == (
        "Keep sku stable. Treat price as USD unless a row says otherwise."
    )
    assert dataset.metadata == {
        "workflow": {
            "status_values": ["draft", "active", "retired"],
            "default_status": "draft",
        }
    }
    assert dataset.headers == ["sku", "name", "price"]
    assert dataset.column_schema == {
        "sku": {"type": "text"},
        "name": {"type": "text"},
        "price": {"type": "currency"},
    }
    assert list(dataset.rows.values_list("index_value", flat=True)) == ["A-1", "B-2"]
    assert dataset.rows.first().data == {
        "sku": "A-1",
        "name": "Adapter",
        "price": "19.99",
    }


def test_dataset_api_creates_ready_dataset_with_generated_index(api_client, profile):
    response = api_client.post(
        "/api/datasets",
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

    create_response = api_client.post(
        f"/api/datasets/{dataset.key}/rows",
        data={"data": {"rowset_id": "custom", "task": "Ship"}},
        content_type="application/json",
    )

    assert create_response.status_code == 200
    assert create_response.json()["row"]["index_value"] == "2"
    assert create_response.json()["row"]["data"] == {"rowset_id": "2", "task": "Ship"}


def test_dataset_api_rejects_non_object_initial_dataset_metadata(api_client, profile):
    response = api_client.post(
        "/api/datasets",
        data={
            "name": "Invalid metadata",
            "headers": ["name"],
            "metadata": ["not", "an", "object"],
        },
        content_type="application/json",
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "payload", "metadata"]
    assert not Dataset.objects.filter(profile=profile, name="Invalid metadata").exists()


def test_dataset_api_accepts_explicit_column_types_on_create(api_client, profile):
    response = api_client.post(
        "/api/datasets",
        data={
            "name": "Products",
            "headers": ["sku", "price"],
            "index_column": "sku",
            "column_types": {
                "sku": {
                    "type": "text",
                    "description": "Stable supplier SKU used for row lookup.",
                },
                "price": {
                    "type": "number",
                    "description": "Current retail price in USD.",
                },
            },
            "rows": [{"sku": "A-1", "price": "19.99"}],
        },
        content_type="application/json",
    )

    assert response.status_code == 201
    dataset = Dataset.objects.get(key=response.json()["dataset"]["key"], profile=profile)
    assert dataset.column_schema == {
        "sku": {
            "type": "text",
            "description": "Stable supplier SKU used for row lookup.",
        },
        "price": {
            "type": "number",
            "description": "Current retail price in USD.",
        },
    }


def test_dataset_api_rejects_duplicate_index_on_create(api_client, profile):
    response = api_client.post(
        "/api/datasets",
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


def test_dataset_api_rejects_too_many_initial_rows(api_client, profile):
    response = api_client.post(
        "/api/datasets",
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
    with pytest.raises(DatasetServiceError, match="at most 1000 initial rows") as exc_info:
        create_profile_dataset(
            profile,
            name="Too many rows",
            headers=["name"],
            rows=[{"name": str(index)} for index in range(1001)],
        )

    assert exc_info.value.status_code == 400
    assert not Dataset.objects.filter(profile=profile, name="Too many rows").exists()


def test_create_profile_dataset_tracks_activation_without_private_payload(profile, monkeypatch):
    calls = []

    def track_activation_event(profile, event_name, properties, source_function=None):
        calls.append((profile.id, event_name, properties, source_function))

    monkeypatch.setattr("apps.api.services.track_activation_event", track_activation_event)

    result = create_profile_dataset(
        profile,
        name="Private leads",
        headers=["email", "name"],
        rows=[{"email": "ada@example.com", "name": "Ada"}],
        index_column="email",
    )

    dataset = Dataset.objects.get(key=result["dataset"]["key"])
    assert calls == [
        (
            profile.id,
            ROWSET_DATASET_CREATED,
            {
                "dataset_id": dataset.id,
                "is_first_dataset": True,
                "initial_row_count": 1,
                "column_count": 2,
                "index_generated": False,
                "has_project": False,
                "has_section": False,
                "agent_api_key_present": False,
                "agent_api_key_id": None,
                "agent_api_key_access_level": "",
            },
            "apps.api.services.create_profile_dataset",
        )
    ]
    assert "Private leads" not in str(calls)
    assert "ada@example.com" not in str(calls)
    assert "email" not in calls[0][2]


def test_trial_account_can_create_third_active_dataset(profile):
    for index in range(2):
        Dataset.objects.create(
            profile=profile,
            name=f"Dataset {index}",
            headers=["rowset_id", "name"],
            index_column="rowset_id",
            index_generated=True,
            row_count=0,
        )

    result = create_profile_dataset(
        profile,
        name="Third dataset",
        headers=["name"],
        rows=[],
    )

    assert Dataset.objects.filter(key=result["dataset"]["key"], profile=profile).exists()


def test_trial_account_can_create_dataset_with_more_than_50_initial_rows(profile):
    rows = [{"name": str(index)} for index in range(51)]

    result = create_profile_dataset(
        profile,
        name="Trial dataset",
        headers=["name"],
        rows=rows,
    )

    dataset = Dataset.objects.get(key=result["dataset"]["key"])
    assert dataset.row_count == 51


def test_paid_account_can_create_more_than_free_dataset_and_row_limits(profile):
    profile.state = ProfileStates.SUBSCRIBED
    profile.save(update_fields=["state"])
    for index in range(2):
        Dataset.objects.create(
            profile=profile,
            name=f"Existing dataset {index}",
            headers=["rowset_id", "name"],
            index_column="rowset_id",
            index_generated=True,
            row_count=0,
        )

    result = create_profile_dataset(
        profile,
        name="Paid dataset",
        headers=["name"],
        rows=[{"name": str(index)} for index in range(51)],
    )

    dataset = Dataset.objects.get(key=result["dataset"]["key"])
    assert dataset.row_count == 51
    assert Dataset.objects.filter(profile=profile).count() == 3
