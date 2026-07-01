import json

import pytest

from apps.datasets.models import ProjectSection
from apps.datasets.tests.factories import (
    configure_filterable_dataset,
    create_crm_datasets,
    create_profile_with_api_key,
    create_project,
    create_ready_dataset,
)
from apps.mcp_server import server as mcp_server
from apps.mcp_server.server import AGENT_API_KEY_PROFILE_ATTR

pytestmark = pytest.mark.django_db(transaction=True)


def _authenticate_mcp_as(monkeypatch, profile):
    setattr(profile, AGENT_API_KEY_PROFILE_ATTR, profile.agent_api_keys.get())
    monkeypatch.setattr(
        "apps.mcp_server.server._authenticate_profile",
        lambda api_key=None: profile,
    )


def _bearer(profile) -> str:
    return f"Bearer {profile.key}"


def _row_names(payload: dict) -> list[str]:
    return [row["data"]["name"] for row in payload["rows"]]


def _extract_mcp_error_payload(error: Exception) -> dict:
    decoder = json.JSONDecoder()
    text = str(error)
    for index, character in enumerate(text):
        if character != "{":
            continue
        try:
            payload, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    pytest.fail(f"No JSON error payload found in: {text}")


def test_rest_and_mcp_create_dataset_share_ready_dataset_contract(
    client,
    django_user_model,
    monkeypatch,
):
    profile = create_profile_with_api_key(django_user_model)
    _authenticate_mcp_as(monkeypatch, profile)
    base_payload = {
        "description": "Supplier catalog",
        "instructions": "Keep sku stable.",
        "metadata": {"workflow": {"default_status": "draft"}},
        "headers": ["sku", "name", "price"],
        "index_column": "sku",
        "rows": [
            {"sku": "A-1", "name": "Adapter", "price": 19.99},
            {"sku": "B-2", "name": "Bridge", "price": 29},
        ],
    }

    rest_response = client.post(
        "/api/datasets",
        data={"name": "REST Products", **base_payload},
        content_type="application/json",
        HTTP_AUTHORIZATION=_bearer(profile),
    )

    mcp_result = mcp_server.create_dataset(name="MCP Products", **base_payload)

    assert rest_response.status_code == 201
    rest_dataset = rest_response.json()["dataset"]
    mcp_dataset = mcp_result["dataset"]
    for payload in (rest_dataset, mcp_dataset):
        assert payload["file_type"] == "api"
        assert payload["status"] == "ready"
        assert payload["description"] == "Supplier catalog"
        assert payload["instructions"] == "Keep sku stable."
        assert payload["metadata"] == {"workflow": {"default_status": "draft"}}
        assert payload["headers"] == ["sku", "name", "price"]
        assert payload["index_column"] == "sku"
        assert payload["column_schema"] == {
            "sku": {"type": "text"},
            "name": {"type": "text"},
            "price": {"type": "currency"},
        }
        assert payload["row_count"] == 2


def test_rest_and_mcp_list_rows_share_filter_and_sort_semantics(
    client,
    django_user_model,
    monkeypatch,
):
    profile = create_profile_with_api_key(django_user_model)
    _authenticate_mcp_as(monkeypatch, profile)
    dataset = configure_filterable_dataset(create_ready_dataset(profile))
    filters = {"active": "true"}

    rest_response = client.get(
        f"/api/datasets/{dataset.key}/rows",
        {
            "filters": json.dumps(filters),
            "sort": "name",
            "direction": "desc",
        },
        HTTP_AUTHORIZATION=_bearer(profile),
    )

    mcp_result = mcp_server.list_dataset_rows(
        str(dataset.key),
        filters=filters,
        sort="name",
        direction="desc",
    )

    assert rest_response.status_code == 200
    assert rest_response.json()["count"] == mcp_result["count"] == 2
    assert rest_response.json()["total_count"] == mcp_result["total_count"] == 3
    assert (
        _row_names(rest_response.json())
        == _row_names(mcp_result)
        == [
            "Katherine Johnson",
            "Ada Lovelace",
        ]
    )


def test_rest_and_mcp_patch_row_by_index_ignore_unknown_columns(
    client,
    django_user_model,
    monkeypatch,
):
    profile = create_profile_with_api_key(django_user_model)
    _authenticate_mcp_as(monkeypatch, profile)
    rest_dataset = create_ready_dataset(profile)
    mcp_dataset = create_ready_dataset(profile)
    patch_payload = {"name": "Ada Byron", "ignored": "nope"}

    rest_response = client.patch(
        f"/api/datasets/{rest_dataset.key}/rows/by-index",
        {"data": patch_payload},
        content_type="application/json",
        HTTP_AUTHORIZATION=_bearer(profile),
        QUERY_STRING="index_value=ada@example.com",
    )

    mcp_result = mcp_server.update_dataset_row_by_index(
        str(mcp_dataset.key),
        "ada@example.com",
        patch_payload,
    )

    assert rest_response.status_code == 200
    assert rest_response.json()["row"]["data"] == mcp_result["row"]["data"]
    assert rest_response.json()["row"]["data"] == {
        "name": "Ada Byron",
        "email": "ada@example.com",
    }


def test_rest_and_mcp_update_public_preview_share_response_contract(
    client,
    django_user_model,
    monkeypatch,
):
    profile = create_profile_with_api_key(django_user_model)
    _authenticate_mcp_as(monkeypatch, profile)
    rest_dataset = create_ready_dataset(profile)
    mcp_dataset = create_ready_dataset(profile)

    rest_response = client.patch(
        f"/api/datasets/{rest_dataset.key}/public-preview",
        {"public_enabled": True, "public_page_size": 1},
        content_type="application/json",
        HTTP_AUTHORIZATION=_bearer(profile),
    )

    mcp_result = mcp_server.update_dataset_public_preview(
        str(mcp_dataset.key),
        public_enabled=True,
        public_page_size=1,
    )

    assert rest_response.status_code == 200
    rest_dataset_payload = rest_response.json()["dataset"]
    mcp_dataset_payload = mcp_result["dataset"]
    assert rest_dataset_payload["public_enabled"] is True
    assert mcp_dataset_payload["public_enabled"] is True
    assert rest_dataset_payload["public_page_size"] == mcp_dataset_payload["public_page_size"] == 1
    assert rest_dataset_payload["public_url"]
    assert mcp_dataset_payload["public_url"]


def test_rest_and_mcp_project_section_assignment_share_contract(
    client,
    django_user_model,
    monkeypatch,
):
    profile = create_profile_with_api_key(django_user_model)
    _authenticate_mcp_as(monkeypatch, profile)
    project = create_project(profile, name="Launch")
    section = ProjectSection.objects.create(profile=profile, project=project, name="Backlog")
    rest_dataset = create_ready_dataset(profile)
    mcp_dataset = create_ready_dataset(profile)
    payload = {"project_key": str(project.key), "section_key": str(section.key)}

    rest_response = client.patch(
        f"/api/datasets/{rest_dataset.key}/project",
        payload,
        content_type="application/json",
        HTTP_AUTHORIZATION=_bearer(profile),
    )

    mcp_result = mcp_server.update_dataset_project(str(mcp_dataset.key), **payload)

    assert rest_response.status_code == 200
    rest_dataset_payload = rest_response.json()["dataset"]
    mcp_dataset_payload = mcp_result["dataset"]
    assert rest_dataset_payload["project"]["key"] == mcp_dataset_payload["project"]["key"]
    assert rest_dataset_payload["section"]["key"] == mcp_dataset_payload["section"]["key"]
    assert rest_dataset_payload["project"]["name"] == mcp_dataset_payload["project"]["name"]
    assert rest_dataset_payload["section"]["name"] == mcp_dataset_payload["section"]["name"]


def test_rest_and_mcp_add_column_share_schema_mutation_contract(
    client,
    django_user_model,
    monkeypatch,
):
    profile = create_profile_with_api_key(django_user_model)
    _authenticate_mcp_as(monkeypatch, profile)
    rest_dataset = create_ready_dataset(profile)
    mcp_dataset = create_ready_dataset(profile)
    payload = {
        "name": "status",
        "default_value": "todo",
        "column_type": {"type": "choice", "choices": ["todo", "done"]},
    }

    rest_response = client.post(
        f"/api/datasets/{rest_dataset.key}/columns",
        payload,
        content_type="application/json",
        HTTP_AUTHORIZATION=_bearer(profile),
    )

    mcp_result = mcp_server.add_column(str(mcp_dataset.key), **payload)

    assert rest_response.status_code == 200
    rest_dataset_payload = rest_response.json()["dataset"]
    mcp_dataset_payload = mcp_result["dataset"]
    assert rest_dataset_payload["headers"] == mcp_dataset_payload["headers"]
    assert rest_dataset_payload["column_schema"] == mcp_dataset_payload["column_schema"]
    assert rest_dataset_payload["row_count"] == mcp_dataset_payload["row_count"] == 2


def test_rest_and_mcp_relationship_create_and_resolve_share_contract(
    client,
    django_user_model,
    monkeypatch,
):
    profile = create_profile_with_api_key(django_user_model)
    _authenticate_mcp_as(monkeypatch, profile)
    rest_people, rest_messages = create_crm_datasets(profile)
    mcp_people, mcp_messages = create_crm_datasets(profile)
    payload = {
        "source_column": "person_id",
        "target_dataset_key": str(rest_people.key),
        "name": "Message person",
        "enforce_integrity": True,
    }

    rest_create_response = client.post(
        f"/api/datasets/{rest_messages.key}/relationships",
        payload,
        content_type="application/json",
        HTTP_AUTHORIZATION=_bearer(profile),
    )

    mcp_result = mcp_server.create_dataset_relationship(
        str(mcp_messages.key),
        source_column=payload["source_column"],
        target_dataset_key=str(mcp_people.key),
        name=payload["name"],
        enforce_integrity=payload["enforce_integrity"],
    )

    assert rest_create_response.status_code == 201
    rest_relationship = rest_create_response.json()["relationship"]
    mcp_relationship = mcp_result["relationship"]
    assert rest_relationship["name"] == mcp_relationship["name"] == "Message person"
    assert rest_relationship["source_column"] == mcp_relationship["source_column"] == "person_id"
    assert rest_relationship["target_index_column"] == mcp_relationship["target_index_column"]
    assert rest_relationship["enforce_integrity"] is mcp_relationship["enforce_integrity"] is True

    rest_resolve_response = client.get(
        f"/api/datasets/{rest_messages.key}/relationships/{rest_relationship['key']}/resolve",
        {"source_index_value": "M-1"},
        HTTP_AUTHORIZATION=_bearer(profile),
    )
    mcp_resolve_result = mcp_server.resolve_dataset_relationship(
        str(mcp_messages.key),
        mcp_relationship["key"],
        source_index_value="M-1",
    )

    assert rest_resolve_response.status_code == 200
    rest_resolve_payload = rest_resolve_response.json()
    assert rest_resolve_payload["message"] == mcp_resolve_result["message"]
    assert rest_resolve_payload["target_index_value"] == mcp_resolve_result["target_index_value"]
    assert rest_resolve_payload["target_row"]["data"] == mcp_resolve_result["target_row"]["data"]


def test_rest_and_mcp_missing_dataset_share_not_found_error_path(
    client,
    django_user_model,
    monkeypatch,
):
    profile = create_profile_with_api_key(django_user_model)
    _authenticate_mcp_as(monkeypatch, profile)
    missing_dataset_key = "00000000-0000-0000-0000-000000000000"

    rest_response = client.post(
        f"/api/datasets/{missing_dataset_key}/columns",
        {"name": "status", "default_value": ""},
        content_type="application/json",
        HTTP_AUTHORIZATION=_bearer(profile),
    )

    with pytest.raises(Exception) as exc_info:
        mcp_server.add_column(missing_dataset_key, name="status", default_value="")

    assert rest_response.status_code == 404
    mcp_error = _extract_mcp_error_payload(exc_info.value)
    assert mcp_error["code"] == "DATASET_NOT_FOUND"
    assert mcp_error["details"]["http_status"] == rest_response.status_code
