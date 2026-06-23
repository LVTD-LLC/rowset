from types import SimpleNamespace

import anyio
import pytest
from django.test import override_settings
from fastmcp import Client

from apps.api.services import DatasetServiceError
from apps.datasets.choices import DatasetStatus
from apps.datasets.models import Dataset, DatasetRow
from apps.mcp_server.server import get_dataset_row as mcp_get_dataset_row
from apps.mcp_server.server import mcp


def _profile():
    user = SimpleNamespace(
        id=7,
        email="ada@example.com",
        username="ada",
        first_name="Ada",
        last_name="Lovelace",
        date_joined="2026-05-14T00:00:00Z",
        is_staff=False,
        is_superuser=False,
        get_full_name=lambda: "Ada Lovelace",
    )
    project = SimpleNamespace(
        key="3efc2ad0-8d28-44bc-a554-cb3eab89f45a",
        name="Launch",
        description="Launch datasets",
    )
    dataset = SimpleNamespace(
        key="6b0fe8f5-89e5-4cb1-a40d-6aa912ba31d7",
        name="Customers",
        project=project,
        original_filename="customers.csv",
        file_type="csv",
        status="ready",
        headers=["email", "name"],
        column_schema={
            "email": {"type": "email"},
            "name": {"type": "text"},
        },
        index_column="email",
        index_generated=False,
        row_count=42,
        public_enabled=False,
        public_key="4b7b8e47-15a5-4bd5-82cb-8c4f4fd40ce9",
        public_page_size=10,
        public_password_hash="",
        is_public_password_protected=False,
        created_at="2026-05-14T00:00:00Z",
        updated_at="2026-05-14T00:01:00Z",
        confirmed_at=None,
        processed_at=None,
        archived_at=None,
        get_public_url=lambda: "/share/datasets/4b7b8e47-15a5-4bd5-82cb-8c4f4fd40ce9/",
    )

    class DatasetQuerySet:
        def count(self):
            return 1

        def __getitem__(self, key):
            assert key == slice(0, 100, None)
            return [dataset]

    class DatasetManager:
        def filter(self, **kwargs):
            assert kwargs == {"archived_at__isnull": True}
            return self

        def select_related(self, *fields):
            assert fields == ("project",)
            return self

        def only(self, *fields):
            return DatasetQuerySet()

    datasets = DatasetManager()
    return SimpleNamespace(
        id=11,
        user=user,
        state="signed_up",
        has_active_subscription=False,
        datasets=datasets,
    )


def test_get_user_info_mcp_tool_returns_safe_user_data(monkeypatch):
    async def run():
        monkeypatch.setattr(
            "apps.mcp_server.server._authenticate_profile",
            lambda api_key=None: _profile(),
        )

        async with Client(mcp) as client:
            result = await client.call_tool("get_user_info", {})

        payload = result.data
        assert payload["email"] == "ada@example.com"
        assert payload["profile"]["id"] == 11
        assert "key" not in payload
        assert "is_staff" not in payload
        assert "is_superuser" not in payload

    anyio.run(run)


def test_get_all_datasets_mcp_tool_returns_dataset_metadata(monkeypatch):
    async def run():
        monkeypatch.setattr(
            "apps.mcp_server.server._authenticate_profile",
            lambda api_key=None: _profile(),
        )

        async with Client(mcp) as client:
            result = await client.call_tool("get_all_datasets", {})

        payload = result.data
        assert payload["count"] == 1
        assert payload["total_count"] == 1
        assert payload["has_more"] is False
        assert payload["datasets"][0]["key"] == "6b0fe8f5-89e5-4cb1-a40d-6aa912ba31d7"
        assert payload["datasets"][0]["name"] == "Customers"
        assert payload["datasets"][0]["row_count"] == 42
        assert "rows" not in payload["datasets"][0]

    anyio.run(run)


def test_get_dataset_mcp_tool_returns_single_dataset_metadata(monkeypatch):
    async def run():
        profile = _profile()
        dataset = profile.datasets.only().__getitem__(slice(0, 100, None))[0]
        monkeypatch.setattr(
            "apps.mcp_server.server._authenticate_profile",
            lambda api_key=None: profile,
        )
        monkeypatch.setattr(
            "apps.mcp_server.server.get_profile_dataset",
            lambda authenticated_profile, dataset_key: dataset,
        )

        async with Client(mcp) as client:
            result = await client.call_tool(
                "get_dataset",
                {
                    "dataset_key": "6b0fe8f5-89e5-4cb1-a40d-6aa912ba31d7",
                },
            )

        payload = result.data
        assert payload["key"] == "6b0fe8f5-89e5-4cb1-a40d-6aa912ba31d7"
        assert payload["name"] == "Customers"
        assert "rows" not in payload

    anyio.run(run)


def test_project_mcp_tools_call_project_services(monkeypatch):
    calls = []

    def list_projects(authenticated_profile, limit=100, offset=0):
        calls.append(("list_projects", authenticated_profile.id, limit, offset))
        return {
            "count": 1,
            "total_count": 1,
            "limit": limit,
            "offset": offset,
            "has_more": False,
            "projects": [{"key": "project-key", "name": "Launch"}],
        }

    def create_project(authenticated_profile, *, name, description=None):
        calls.append(("create_project", authenticated_profile.id, name, description))
        return {
            "status": "success",
            "message": "Project created.",
            "project": {"key": "project-key", "name": name, "description": description},
        }

    def get_project(authenticated_profile, project_key, limit=100, offset=0):
        calls.append(("get_project", authenticated_profile.id, project_key, limit, offset))
        return {
            "status": "success",
            "message": "Project retrieved.",
            "project": {"key": project_key, "name": "Launch"},
            "datasets": {"count": 0, "datasets": []},
        }

    def update_project(authenticated_profile, dataset_key, project_key):
        calls.append(("update_project", authenticated_profile.id, dataset_key, project_key))
        return {
            "status": "success",
            "message": "Dataset project updated.",
            "dataset": {"key": dataset_key, "project": {"key": project_key}},
        }

    async def run():
        monkeypatch.setattr(
            "apps.mcp_server.server._authenticate_profile",
            lambda api_key=None: _profile(),
        )
        monkeypatch.setattr("apps.mcp_server.server.serialize_profile_projects", list_projects)
        monkeypatch.setattr("apps.mcp_server.server.create_profile_project", create_project)
        monkeypatch.setattr("apps.mcp_server.server.serialize_profile_project_detail", get_project)
        monkeypatch.setattr("apps.mcp_server.server.update_profile_dataset_project", update_project)

        async with Client(mcp) as client:
            list_result = await client.call_tool(
                "get_all_projects",
                {"limit": 5},
            )
            create_result = await client.call_tool(
                "create_project",
                {"name": "Launch", "description": "Launch datasets"},
            )
            detail_result = await client.call_tool(
                "get_project",
                {"project_key": "project-key", "limit": 2},
            )
            update_result = await client.call_tool(
                "update_dataset_project",
                {"dataset_key": "dataset-key", "project_key": "project-key"},
            )

        assert list_result.data["projects"][0]["key"] == "project-key"
        assert create_result.data["project"]["name"] == "Launch"
        assert detail_result.data["project"]["key"] == "project-key"
        assert update_result.data["dataset"]["project"]["key"] == "project-key"
        assert calls == [
            ("list_projects", 11, 5, 0),
            ("create_project", 11, "Launch", "Launch datasets"),
            ("get_project", 11, "project-key", 2, 0),
            ("update_project", 11, "dataset-key", "project-key"),
        ]

    anyio.run(run)


def test_create_dataset_mcp_tool_calls_dataset_service(monkeypatch):
    calls = []

    def create_dataset(
        authenticated_profile,
        *,
        name,
        headers=None,
        rows=None,
        index_column=None,
        column_types=None,
        project_key=None,
    ):
        calls.append(
            (
                authenticated_profile.id,
                name,
                headers,
                rows,
                index_column,
                column_types,
                project_key,
            )
        )
        return {
            "status": "success",
            "message": "Dataset created.",
            "dataset": {
                "key": "dataset-key",
                "name": name,
                "headers": headers,
                "index_column": index_column,
            },
        }

    async def run():
        monkeypatch.setattr(
            "apps.mcp_server.server._authenticate_profile",
            lambda api_key=None: _profile(),
        )
        monkeypatch.setattr("apps.mcp_server.server.create_profile_dataset", create_dataset)

        async with Client(mcp) as client:
            result = await client.call_tool(
                "create_dataset",
                {
                    "name": "Products",
                    "headers": ["sku", "name"],
                    "rows": [{"sku": "A-1", "name": "Adapter"}],
                    "index_column": "sku",
                    "column_types": {"sku": "text", "name": "text"},
                    "project_key": "project-key",
                },
            )

        assert result.data["dataset"]["key"] == "dataset-key"
        assert calls == [
            (
                11,
                "Products",
                ["sku", "name"],
                [{"sku": "A-1", "name": "Adapter"}],
                "sku",
                {"sku": "text", "name": "text"},
                "project-key",
            )
        ]

    anyio.run(run)


def test_dataset_row_mcp_tools_call_dataset_services(monkeypatch):
    calls = []

    def profile():
        return _profile()

    def list_rows(authenticated_profile, dataset_key, limit=100, offset=0):
        calls.append(("list", dataset_key, limit, offset))
        return {
            "dataset": dataset_key,
            "count": 1,
            "rows": [{"id": 1, "data": {"email": "a@example.com"}}],
        }

    def get_row(authenticated_profile, dataset_key, row_id):
        calls.append(("get", dataset_key, row_id))
        return {"status": "success", "message": "Row retrieved.", "row": {"id": row_id}}

    def get_by_index(authenticated_profile, dataset_key, index_value):
        calls.append(("get_by_index", dataset_key, index_value))
        return {
            "status": "success",
            "message": "Row retrieved.",
            "row": {"index_value": index_value},
        }

    def create_row(authenticated_profile, dataset_key, data):
        calls.append(("create", dataset_key, data))
        return {"status": "success", "message": "Row created.", "row": {"data": data}}

    def update_row(authenticated_profile, dataset_key, row_id, data):
        calls.append(("update", dataset_key, row_id, data))
        return {"status": "success", "message": "Row updated.", "row": {"id": row_id, "data": data}}

    def update_row_by_index(authenticated_profile, dataset_key, index_value, data):
        calls.append(("update_by_index", dataset_key, index_value, data))
        return {
            "status": "success",
            "message": "Row updated.",
            "row": {"index_value": index_value, "data": data},
        }

    def delete_row(authenticated_profile, dataset_key, row_id):
        calls.append(("delete", dataset_key, row_id))
        return {"status": "success", "message": "Row deleted."}

    async def run():
        monkeypatch.setattr(
            "apps.mcp_server.server._authenticate_profile",
            lambda api_key=None: profile(),
        )
        monkeypatch.setattr("apps.mcp_server.server.list_profile_dataset_rows", list_rows)
        monkeypatch.setattr("apps.mcp_server.server.get_profile_dataset_row", get_row)
        monkeypatch.setattr("apps.mcp_server.server.get_profile_dataset_row_by_index", get_by_index)
        monkeypatch.setattr("apps.mcp_server.server.create_profile_dataset_row", create_row)
        monkeypatch.setattr("apps.mcp_server.server.patch_profile_dataset_row", update_row)
        monkeypatch.setattr(
            "apps.mcp_server.server.patch_profile_dataset_row_by_index",
            update_row_by_index,
        )
        monkeypatch.setattr("apps.mcp_server.server.delete_profile_dataset_row", delete_row)

        async with Client(mcp) as client:
            list_result = await client.call_tool(
                "list_dataset_rows",
                {"dataset_key": "ds", "limit": 5},
            )
            get_result = await client.call_tool(
                "get_dataset_row",
                {"dataset_key": "ds", "row_id": 7},
            )
            get_by_index_result = await client.call_tool(
                "get_dataset_row_by_index",
                {"dataset_key": "ds", "index_value": "a@example.com"},
            )
            create_result = await client.call_tool(
                "create_dataset_row",
                {"dataset_key": "ds", "data": {"email": "b@example.com"}},
            )
            update_result = await client.call_tool(
                "update_dataset_row",
                {"dataset_key": "ds", "row_id": 7, "data": {"email": "c@example.com"}},
            )
            update_by_index_result = await client.call_tool(
                "update_dataset_row_by_index",
                {
                    "dataset_key": "ds",
                    "index_value": "c@example.com",
                    "data": {"name": "Ada"},
                },
            )
            delete_result = await client.call_tool(
                "delete_dataset_row",
                {"dataset_key": "ds", "row_id": 7},
            )

        assert list_result.data["count"] == 1
        assert get_result.data["row"]["id"] == 7
        assert get_by_index_result.data["row"]["index_value"] == "a@example.com"
        assert create_result.data["row"]["data"]["email"] == "b@example.com"
        assert update_result.data["row"]["data"]["email"] == "c@example.com"
        assert update_by_index_result.data["row"]["data"]["name"] == "Ada"
        assert delete_result.data["message"] == "Row deleted."

        assert calls == [
            ("list", "ds", 5, 0),
            ("get", "ds", 7),
            ("get_by_index", "ds", "a@example.com"),
            ("create", "ds", {"email": "b@example.com"}),
            ("update", "ds", 7, {"email": "c@example.com"}),
            ("update_by_index", "ds", "c@example.com", {"name": "Ada"}),
            ("delete", "ds", 7),
        ]

    anyio.run(run)


@pytest.mark.django_db(transaction=True)
@override_settings(SITE_URL="https://rowset.example")
def test_dataset_row_mcp_tool_resolves_owned_public_row_url(monkeypatch, django_user_model):
    user = django_user_model.objects.create_user(
        username="mcppublicurl",
        email="mcppublicurl@example.com",
        password="password123",
    )
    dataset = Dataset.objects.create(
        profile=user.profile,
        name="People",
        original_filename="Created via API",
        file_type="api",
        status=DatasetStatus.READY,
        headers=["email", "name"],
        index_column="email",
        row_count=1,
        public_enabled=True,
    )
    row = DatasetRow.objects.create(
        dataset=dataset,
        row_number=1,
        index_value="ada@example.com",
        data={"email": "ada@example.com", "name": "Ada"},
    )
    public_row_url = f"https://rowset.example/share/datasets/{dataset.public_key}/rows/{row.id}/"

    monkeypatch.setattr(
        "apps.mcp_server.server._authenticate_profile",
        lambda api_key=None: user.profile,
    )

    result = mcp_get_dataset_row(public_row_url, row.id)

    assert result["dataset"] == str(dataset.key)
    assert result["row"]["id"] == row.id
    assert result["row"]["data"]["email"] == "ada@example.com"


def test_update_dataset_column_types_mcp_tool_calls_dataset_service(monkeypatch):
    calls = []

    def update_column_types(authenticated_profile, dataset_key, column_types):
        calls.append((authenticated_profile.id, dataset_key, column_types))
        return {
            "status": "success",
            "message": "Column types updated.",
            "dataset": {"key": dataset_key, "column_schema": {"email": {"type": "text"}}},
        }

    async def run():
        monkeypatch.setattr(
            "apps.mcp_server.server._authenticate_profile",
            lambda api_key=None: _profile(),
        )
        monkeypatch.setattr(
            "apps.mcp_server.server.update_profile_dataset_column_types",
            update_column_types,
        )

        async with Client(mcp) as client:
            result = await client.call_tool(
                "update_dataset_column_types",
                {
                    "dataset_key": "ds",
                    "column_types": {"email": "text"},
                },
            )

        assert result.data["message"] == "Column types updated."
        assert calls == [(11, "ds", {"email": "text"})]

    anyio.run(run)


def test_schema_mutation_mcp_tools_call_dataset_services(monkeypatch):
    calls = []

    def add_column(
        authenticated_profile,
        dataset_key,
        *,
        name,
        default_value="",
        column_type=None,
    ):
        calls.append(
            ("add", authenticated_profile.id, dataset_key, name, default_value, column_type)
        )
        return {
            "status": "success",
            "message": "Column added.",
            "dataset": {"key": dataset_key, "headers": ["email", name]},
        }

    def rename_column(authenticated_profile, dataset_key, *, old_name, new_name):
        calls.append(("rename", authenticated_profile.id, dataset_key, old_name, new_name))
        return {
            "status": "success",
            "message": "Column renamed.",
            "dataset": {"key": dataset_key, "headers": [new_name]},
        }

    def drop_column(authenticated_profile, dataset_key, *, name):
        calls.append(("drop", authenticated_profile.id, dataset_key, name))
        return {
            "status": "success",
            "message": "Column dropped.",
            "dataset": {"key": dataset_key, "headers": ["email"]},
        }

    def reorder_columns(authenticated_profile, dataset_key, *, headers):
        calls.append(("reorder", authenticated_profile.id, dataset_key, headers))
        return {
            "status": "success",
            "message": "Columns reordered.",
            "dataset": {"key": dataset_key, "headers": headers},
        }

    async def run():
        monkeypatch.setattr(
            "apps.mcp_server.server._authenticate_profile",
            lambda api_key=None: _profile(),
        )
        monkeypatch.setattr("apps.mcp_server.server.add_profile_dataset_column", add_column)
        monkeypatch.setattr("apps.mcp_server.server.rename_profile_dataset_column", rename_column)
        monkeypatch.setattr("apps.mcp_server.server.drop_profile_dataset_column", drop_column)
        monkeypatch.setattr(
            "apps.mcp_server.server.reorder_profile_dataset_columns",
            reorder_columns,
        )

        async with Client(mcp) as client:
            add_result = await client.call_tool(
                "add_column",
                {
                    "dataset_key": "ds",
                    "name": "visibility_level",
                    "default_value": "internal",
                    "column_type": "text",
                },
            )
            rename_result = await client.call_tool(
                "rename_column",
                {"dataset_key": "ds", "old_name": "name", "new_name": "full_name"},
            )
            drop_result = await client.call_tool(
                "drop_column",
                {"dataset_key": "ds", "name": "notes"},
            )
            reorder_result = await client.call_tool(
                "reorder_columns",
                {"dataset_key": "ds", "headers": ["email", "full_name"]},
            )

        assert add_result.data["message"] == "Column added."
        assert rename_result.data["message"] == "Column renamed."
        assert drop_result.data["message"] == "Column dropped."
        assert reorder_result.data["dataset"]["headers"] == ["email", "full_name"]
        assert calls == [
            ("add", 11, "ds", "visibility_level", "internal", "text"),
            ("rename", 11, "ds", "name", "full_name"),
            ("drop", 11, "ds", "notes"),
            ("reorder", 11, "ds", ["email", "full_name"]),
        ]

    anyio.run(run)


def test_update_dataset_public_preview_mcp_tool_calls_dataset_service(monkeypatch):
    calls = []

    def update_public_preview(
        authenticated_profile,
        dataset_key,
        *,
        public_enabled=None,
        public_page_size=None,
        public_password=None,
        clear_public_password=False,
    ):
        calls.append(
            (
                authenticated_profile.id,
                dataset_key,
                public_enabled,
                public_page_size,
                public_password,
                clear_public_password,
            )
        )
        return {
            "status": "success",
            "message": "Public preview settings updated.",
            "dataset": {
                "key": dataset_key,
                "public_enabled": public_enabled,
                "public_url": "https://rowset.example/share/datasets/public-key/",
            },
        }

    async def run():
        monkeypatch.setattr(
            "apps.mcp_server.server._authenticate_profile",
            lambda api_key=None: _profile(),
        )
        monkeypatch.setattr(
            "apps.mcp_server.server.update_profile_dataset_public_preview",
            update_public_preview,
        )

        async with Client(mcp) as client:
            result = await client.call_tool(
                "update_dataset_public_preview",
                {
                    "dataset_key": "ds",
                    "public_enabled": True,
                    "public_page_size": 25,
                    "public_password": "secret",
                },
            )
            partial_result = await client.call_tool(
                "update_dataset_public_preview",
                {
                    "dataset_key": "ds",
                    "public_page_size": 50,
                },
            )

        assert result.data["dataset"]["public_url"].endswith("/share/datasets/public-key/")
        assert partial_result.data["message"] == "Public preview settings updated."
        assert calls == [
            (11, "ds", True, 25, "secret", False),
            (11, "ds", None, 50, None, False),
        ]

    anyio.run(run)


def test_dataset_archive_restore_mcp_tools_call_dataset_services(monkeypatch):
    calls = []

    def archive_dataset(authenticated_profile, dataset_key, agent_api_key=None):
        calls.append(("archive", authenticated_profile.id, dataset_key))
        return {
            "status": "success",
            "message": "Dataset archived.",
            "dataset": {"key": dataset_key, "archived_at": "2026-05-14T00:00:00Z"},
        }

    def restore_dataset(authenticated_profile, dataset_key, agent_api_key=None):
        calls.append(("restore", authenticated_profile.id, dataset_key))
        return {
            "status": "success",
            "message": "Dataset restored.",
            "dataset": {"key": dataset_key, "archived_at": None},
        }

    async def run():
        monkeypatch.setattr(
            "apps.mcp_server.server._authenticate_profile",
            lambda api_key=None: _profile(),
        )
        monkeypatch.setattr(
            "apps.mcp_server.server.archive_profile_dataset",
            archive_dataset,
            raising=False,
        )
        monkeypatch.setattr(
            "apps.mcp_server.server.restore_profile_dataset",
            restore_dataset,
            raising=False,
        )

        async with Client(mcp) as client:
            archive_result = await client.call_tool(
                "archive_dataset",
                {"dataset_key": "ds"},
            )
            restore_result = await client.call_tool(
                "restore_dataset",
                {"dataset_key": "ds"},
            )

        assert archive_result.data["message"] == "Dataset archived."
        assert restore_result.data["dataset"]["archived_at"] is None
        assert calls == [
            ("archive", 11, "ds"),
            ("restore", 11, "ds"),
        ]

    anyio.run(run)


def test_dataset_row_mcp_tools_return_service_errors(monkeypatch):
    async def run():
        monkeypatch.setattr(
            "apps.mcp_server.server._authenticate_profile",
            lambda api_key=None: _profile(),
        )
        monkeypatch.setattr(
            "apps.mcp_server.server.get_profile_dataset_row",
            lambda profile, dataset_key, row_id: (_ for _ in ()).throw(
                DatasetServiceError(404, "Row not found.")
            ),
        )

        async with Client(mcp) as client:
            with pytest.raises(Exception, match="404: Row not found"):
                await client.call_tool("get_dataset_row", {"dataset_key": "ds", "row_id": 999})

    anyio.run(run)


def test_get_user_info_mcp_tool_rejects_invalid_api_key(monkeypatch):
    def reject(api_key=None):
        raise PermissionError("Invalid Rowset API key")

    async def run():
        monkeypatch.setattr("apps.mcp_server.server._authenticate_profile", reject)

        async with Client(mcp) as client:
            with pytest.raises(Exception, match="Invalid Rowset API key"):
                await client.call_tool("get_user_info", {})

    anyio.run(run)
