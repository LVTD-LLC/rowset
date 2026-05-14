from types import SimpleNamespace

import anyio
import pytest
from fastmcp import Client

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
    dataset = SimpleNamespace(
        key="6b0fe8f5-89e5-4cb1-a40d-6aa912ba31d7",
        name="Customers",
        original_filename="customers.csv",
        file_type="csv",
        status="ready",
        headers=["email", "name"],
        index_column="email",
        index_generated=False,
        row_count=42,
        public_enabled=False,
        created_at="2026-05-14T00:00:00Z",
        updated_at="2026-05-14T00:01:00Z",
        confirmed_at=None,
        processed_at=None,
    )

    class DatasetQuerySet:
        def count(self):
            return 1

        def __getitem__(self, key):
            assert key == slice(0, 100, None)
            return [dataset]

    datasets = SimpleNamespace(only=lambda *fields: DatasetQuerySet())
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
            result = await client.call_tool("get_user_info", {"api_key": "secret-key"})

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
            result = await client.call_tool("get_all_datasets", {"api_key": "secret-key"})

        payload = result.data
        assert payload["count"] == 1
        assert payload["total_count"] == 1
        assert payload["has_more"] is False
        assert payload["datasets"][0]["key"] == "6b0fe8f5-89e5-4cb1-a40d-6aa912ba31d7"
        assert payload["datasets"][0]["name"] == "Customers"
        assert payload["datasets"][0]["row_count"] == 42
        assert "rows" not in payload["datasets"][0]

    anyio.run(run)


def test_get_user_info_mcp_tool_rejects_invalid_api_key(monkeypatch):
    def reject(api_key=None):
        raise PermissionError("Invalid FileBridge API key")

    async def run():
        monkeypatch.setattr("apps.mcp_server.server._authenticate_profile", reject)

        async with Client(mcp) as client:
            with pytest.raises(Exception, match="Invalid FileBridge API key"):
                await client.call_tool("get_user_info", {"api_key": "not-real"})

    anyio.run(run)
