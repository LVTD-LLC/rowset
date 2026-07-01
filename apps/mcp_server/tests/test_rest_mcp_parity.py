import json

import pytest

from apps.datasets.tests.factories import (
    configure_filterable_dataset,
    create_profile_with_api_key,
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
