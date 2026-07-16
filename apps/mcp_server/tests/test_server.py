import json
from datetime import timedelta
from types import SimpleNamespace

import anyio
import pytest
from django.test import override_settings
from django.utils import timezone
from fastmcp import Client

from apps.api.services import DatasetServiceError
from apps.core.analytics import ROWSET_GET_USER_INFO_SUCCEEDED
from apps.core.choices import AgentApiKeyAccessLevel, FeedbackSource
from apps.core.models import Feedback
from apps.core.services import create_agent_api_key
from apps.datasets.models import Dataset, DatasetRow
from apps.mcp_server.server import (
    AGENT_API_KEY_PROFILE_ATTR,
    mcp,
)
from apps.mcp_server.server import (
    get_dataset_row as mcp_get_dataset_row,
)


@pytest.fixture(autouse=True)
def disable_trial_activation(monkeypatch):
    monkeypatch.setattr(
        "apps.mcp_server.server.activate_or_require_trial_access",
        lambda _profile: None,
    )


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


def _expected_mcp_error(
    *,
    code: str,
    message: str,
    suggested_action: str,
    http_status: int,
    retryable: bool = False,
) -> dict:
    return {
        "code": code,
        "message": message,
        "retryable": retryable,
        "suggested_action": suggested_action,
        "details": {"http_status": http_status},
    }


def _profile(agent_api_key_access_level=AgentApiKeyAccessLevel.READ_WRITE):
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
        description="Customers eligible for launch outreach.",
        instructions="Use email as the stable identity. Do not rewrite names from guesses.",
        metadata={"workflow": {"default_status": "new"}},
        project=project,
        headers=["email", "name"],
        column_schema={
            "email": {
                "type": "email",
                "description": "Primary contact address for the customer.",
            },
            "name": {"type": "text"},
        },
        index_column="email",
        index_generated=False,
        column_count=2,
        row_count=42,
        public_enabled=False,
        public_key="4b7b8e47-15a5-4bd5-82cb-8c4f4fd40ce9",
        public_page_size=10,
        public_password_hash="",
        is_public_password_protected=False,
        created_at="2026-05-14T00:00:00Z",
        updated_at="2026-05-14T00:01:00Z",
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
            assert fields == ("project", "section")
            return self

        def annotate(self, **annotations):
            assert set(annotations) == {"column_count"}
            return self

        def only(self, *fields):
            assert "headers" not in fields
            return DatasetQuerySet()

    datasets = DatasetManager()
    profile = SimpleNamespace(
        id=11,
        user=user,
        state="signed_up",
        has_active_subscription=False,
        trial_started_at=None,
        trial_ends_at=None,
        datasets=datasets,
    )
    if agent_api_key_access_level is not None:
        setattr(
            profile,
            AGENT_API_KEY_PROFILE_ATTR,
            SimpleNamespace(id=3, access_level=agent_api_key_access_level),
        )
    return profile


def test_get_user_info_mcp_tool_returns_safe_user_data(monkeypatch):
    calls = []

    def track_activation_event(profile, event_name, properties, source_function=None):
        calls.append((profile.id, event_name, properties, source_function))

    async def run():
        monkeypatch.setattr(
            "apps.mcp_server.server._authenticate_profile",
            lambda: _profile(),
        )
        monkeypatch.setattr(
            "apps.mcp_server.server.track_activation_event",
            track_activation_event,
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
    assert calls == [
        (
            11,
            ROWSET_GET_USER_INFO_SUCCEEDED,
            {
                "interface": "mcp",
                "agent_api_key_present": True,
                "agent_api_key_id": 3,
                "agent_api_key_access_level": AgentApiKeyAccessLevel.READ_WRITE,
            },
            "apps.mcp_server.server.get_user_info",
        )
    ]


@override_settings(SITE_URL="https://rowset.example")
def test_expired_trial_returns_structured_mcp_upgrade_error(monkeypatch):
    ended_at = timezone.now() - timedelta(seconds=1)

    async def run():
        from apps.core.trials import TrialExpiredError

        monkeypatch.setattr(
            "apps.mcp_server.server._authenticate_profile",
            lambda: (_ for _ in ()).throw(TrialExpiredError(ended_at)),
        )

        async with Client(mcp) as client:
            with pytest.raises(Exception) as exc_info:
                await client.call_tool("get_user_info", {})

        payload = _extract_mcp_error_payload(exc_info.value)
        assert payload == {
            "code": "TRIAL_EXPIRED",
            "message": (
                "Your Rowset trial has ended. Upgrade to continue using the API, CLI, and MCP."
            ),
            "retryable": False,
            "suggested_action": "Upgrade at https://rowset.example/pricing.",
            "details": {
                "http_status": 402,
                "trial_ended_at": ended_at.isoformat(),
                "upgrade_url": "https://rowset.example/pricing",
            },
        }

    anyio.run(run)


def test_write_mcp_tool_rejects_read_only_agent_api_key(monkeypatch):
    trial_activations = []

    async def run():
        profile = _profile()
        setattr(
            profile,
            AGENT_API_KEY_PROFILE_ATTR,
            SimpleNamespace(id=3, access_level=AgentApiKeyAccessLevel.READ),
        )
        monkeypatch.setattr(
            "apps.mcp_server.server._authenticate_profile",
            lambda: profile,
        )
        monkeypatch.setattr(
            "apps.mcp_server.server.activate_or_require_trial_access",
            trial_activations.append,
        )

        async with Client(mcp) as client:
            with pytest.raises(Exception) as exc_info:
                await client.call_tool("create_project", {"name": "Launch"})

        payload = _extract_mcp_error_payload(exc_info.value)
        assert payload == _expected_mcp_error(
            code="API_KEY_FORBIDDEN",
            message=(
                "This Rowset API key has Read access, but this action requires Read + write access."
            ),
            suggested_action="Use a Rowset API key with enough permissions for this action.",
            http_status=403,
        )

    anyio.run(run)
    assert trial_activations == []


def test_write_mcp_tool_rejects_missing_agent_api_key_context(monkeypatch):
    async def run():
        monkeypatch.setattr(
            "apps.mcp_server.server._authenticate_profile",
            lambda: _profile(agent_api_key_access_level=None),
        )

        async with Client(mcp) as client:
            with pytest.raises(Exception) as exc_info:
                await client.call_tool("create_project", {"name": "Launch"})

        payload = _extract_mcp_error_payload(exc_info.value)
        assert payload == _expected_mcp_error(
            code="AUTHENTICATION_FAILED",
            message="This action requires an active Rowset agent API key.",
            suggested_action=(
                "Check that the MCP request sends Authorization: Bearer <ROWSET_API_KEY> "
                "with an active Rowset API key."
            ),
            http_status=401,
        )

    anyio.run(run)


def test_create_agent_api_key_mcp_tool_requires_admin_and_returns_new_key(monkeypatch):
    calls = []
    trial_activations = []

    def create_agent_api_key(profile, name, access_level):
        calls.append((profile.id, name, access_level))
        agent_api_key = SimpleNamespace(
            name=name,
            key_prefix="rsk_created",
        )
        return SimpleNamespace(agent_api_key=agent_api_key, raw_key="rsk_created-secret")

    async def run():
        profile = _profile()
        setattr(
            profile,
            AGENT_API_KEY_PROFILE_ATTR,
            SimpleNamespace(id=3, access_level=AgentApiKeyAccessLevel.ADMIN),
        )
        monkeypatch.setattr(
            "apps.mcp_server.server._authenticate_profile",
            lambda: profile,
        )
        monkeypatch.setattr(
            "apps.mcp_server.server.create_agent_api_key_credential",
            create_agent_api_key,
        )
        monkeypatch.setattr(
            "apps.mcp_server.server.activate_or_require_trial_access",
            trial_activations.append,
        )
        monkeypatch.setattr(
            "apps.mcp_server.server.serialize_agent_api_key",
            lambda agent_api_key: {
                "name": agent_api_key.name,
                "key_prefix": agent_api_key.key_prefix,
                "access_level": AgentApiKeyAccessLevel.READ,
            },
        )

        async with Client(mcp) as client:
            result = await client.call_tool(
                "create_agent_api_key",
                {"name": "Reporting Agent", "access_level": "read"},
            )

        payload = result.data
        assert payload["status"] == "success"
        assert payload["agent_api_key"]["access_level"] == AgentApiKeyAccessLevel.READ
        assert payload["api_key"] == "rsk_created-secret"
        assert calls == [(11, "Reporting Agent", "read")]

    anyio.run(run)
    assert trial_activations == []


@override_settings(SITE_URL="https://rowset.example")
def test_create_agent_api_key_mcp_tool_rejects_expired_trial(monkeypatch):
    ended_at = timezone.now() - timedelta(seconds=1)

    async def run():
        profile = _profile()
        profile.trial_started_at = ended_at - timedelta(days=7)
        profile.trial_ends_at = ended_at
        setattr(
            profile,
            AGENT_API_KEY_PROFILE_ATTR,
            SimpleNamespace(id=3, access_level=AgentApiKeyAccessLevel.ADMIN),
        )
        monkeypatch.setattr(
            "apps.mcp_server.server._authenticate_profile",
            lambda: profile,
        )

        async with Client(mcp) as client:
            with pytest.raises(Exception) as exc_info:
                await client.call_tool(
                    "create_agent_api_key",
                    {"name": "Denied Agent", "access_level": "read"},
                )

        payload = _extract_mcp_error_payload(exc_info.value)
        assert payload["code"] == "TRIAL_EXPIRED"
        assert payload["retryable"] is False
        assert payload["details"]["http_status"] == 402
        assert payload["details"]["upgrade_url"] == "https://rowset.example/pricing"

    anyio.run(run)


def test_create_agent_api_key_mcp_tool_rejects_missing_agent_api_key_context(monkeypatch):
    async def run():
        monkeypatch.setattr(
            "apps.mcp_server.server._authenticate_profile",
            lambda: _profile(agent_api_key_access_level=None),
        )

        async with Client(mcp) as client:
            with pytest.raises(Exception) as exc_info:
                await client.call_tool(
                    "create_agent_api_key",
                    {"name": "Denied Agent", "access_level": "read"},
                )

        payload = _extract_mcp_error_payload(exc_info.value)
        assert payload == _expected_mcp_error(
            code="AUTHENTICATION_FAILED",
            message="This action requires an active Rowset agent API key.",
            suggested_action=(
                "Check that the MCP request sends Authorization: Bearer <ROWSET_API_KEY> "
                "with an active Rowset API key."
            ),
            http_status=401,
        )

    anyio.run(run)


def test_get_rowset_capabilities_mcp_tool_returns_feature_guide(monkeypatch):
    async def run():
        monkeypatch.setattr(
            "apps.mcp_server.server._authenticate_profile",
            lambda: _profile(),
        )

        async with Client(mcp) as client:
            result = await client.call_tool("get_rowset_capabilities", {})

        payload = result.data
        assert payload["product"] == "Rowset"
        assert payload["capability_version"]
        capability_ids = {capability["id"] for capability in payload["capabilities"]}
        assert "relationships" in capability_ids
        assert "dataset_context" in capability_ids
        assert "image_assets" in capability_ids
        assert "audio_assets" in capability_ids
        assert {interface["id"] for interface in payload["interfaces"]} == {
            "mcp",
            "cli",
            "rest",
        }
        startup = " ".join(payload["recommended_startup"])
        assert "ask the user which interface to configure" in startup
        assert "authenticated user-info request" in startup
        assert "start the trial" in startup
        assert "suggest two to four project, section, and dataset structures" in startup
        assert "Ask before creating anything" in startup
        assert "daily Rowset tips automation" in startup
        assert "explicit agreement" in startup
        dataset_context = next(
            capability
            for capability in payload["capabilities"]
            if capability["id"] == "dataset_context"
        )
        assert "tags" in " ".join(dataset_context["notes"])
        image_assets = next(
            capability
            for capability in payload["capabilities"]
            if capability["id"] == "image_assets"
        )
        audio_assets = next(
            capability
            for capability in payload["capabilities"]
            if capability["id"] == "audio_assets"
        )
        assert "attach_image_to_dataset_row" in image_assets["mcp_tools"]
        assert "hosted MCP cannot read local file paths" in " ".join(image_assets["notes"])
        assert "attach_audio_to_dataset_row" in audio_assets["mcp_tools"]
        assert "hosted MCP cannot read local file paths" in " ".join(audio_assets["notes"])
        assert "guardrails" in payload

    anyio.run(run)


def test_tags_column_type_is_explained_in_live_mcp_tool_schemas():
    async def run():
        async with Client(mcp) as client:
            tools = {tool.name: tool for tool in await client.list_tools()}

        tool_properties = (
            ("create_dataset", "column_types"),
            ("update_dataset_column_types", "column_types"),
            ("add_column", "column_type"),
        )
        for tool_name, property_name in tool_properties:
            description = tools[tool_name].inputSchema["properties"][property_name]["description"]
            assert "tags" in description
            assert "comma-separated string values" in description
            assert "returns the original string unchanged" in description

    anyio.run(run)


@pytest.mark.django_db(transaction=True)
@override_settings(
    SITE_URL="https://rowset.example",
)
def test_submit_feedback_mcp_tool_creates_feedback_dataset_row(django_user_model, monkeypatch):
    user = django_user_model.objects.create_user(
        username="feedback-mcp-user",
        email="feedback-mcp-user@example.com",
        password="password123",
    )
    profile = user.profile
    observed = {}

    credential = create_agent_api_key(
        profile,
        "Feedback Agent",
        AgentApiKeyAccessLevel.READ_WRITE,
    )
    setattr(profile, AGENT_API_KEY_PROFILE_ATTR, credential.agent_api_key)

    async def run():
        monkeypatch.setattr(
            "apps.mcp_server.server._authenticate_profile",
            lambda: profile,
        )

        async with Client(mcp) as client:
            result = await client.call_tool(
                "submit_feedback",
                {
                    "feedback": "MCP feedback should be saved.",
                    "page": "get_rowset_capabilities",
                    "context": {"tool": "get_rowset_capabilities", "category": "docs"},
                },
            )

        observed["payload"] = result.data

    anyio.run(run)
    payload = observed["payload"]
    feedback = Feedback.objects.get(id=payload["feedback"]["id"])
    dataset = Dataset.objects.select_related("project", "section").get(key=payload["dataset"])
    row = dataset.rows.get(id=payload["row"])

    assert payload["status"] == "success"
    assert payload["row_url"] == f"https://rowset.example/datasets/{dataset.key}/rows/{row.id}/"
    assert payload["feedback"]["id"] == feedback.id
    assert payload["feedback"]["uuid"] == str(feedback.uuid)
    assert payload["feedback"]["source"] == FeedbackSource.MCP
    assert payload["feedback"]["page"] == "get_rowset_capabilities"
    assert payload["feedback"]["context"] == {
        "tool": "get_rowset_capabilities",
        "category": "docs",
    }
    assert feedback.feedback == "MCP feedback should be saved."
    assert feedback.page == "get_rowset_capabilities"
    assert feedback.source == FeedbackSource.MCP
    assert feedback.agent_api_key == credential.agent_api_key
    assert feedback.metadata == {
        "tool": "get_rowset_capabilities",
        "category": "docs",
        "rowset_row_url": payload["row_url"],
    }
    assert dataset.project.name == "Rowset"
    assert dataset.section.name == "CX"
    assert row.created_by_agent_api_key == credential.agent_api_key
    assert row.data["feedback_id"] == str(feedback.id)
    assert row.data["submitted_via"] == "mcp"
    assert row.data["context"] == '{"category":"docs","tool":"get_rowset_capabilities"}'
    assert row.data["feedback"] == "MCP feedback should be saved."


def test_get_all_datasets_mcp_tool_returns_compact_dataset_cards(monkeypatch):
    async def run():
        monkeypatch.setattr(
            "apps.mcp_server.server._authenticate_profile",
            lambda: _profile(),
        )

        async with Client(mcp) as client:
            result = await client.call_tool("get_all_datasets", {})

        payload = result.data
        assert payload["count"] == 1
        assert payload["total_count"] == 1
        assert payload["has_more"] is False
        assert payload["datasets"][0] == {
            "key": "6b0fe8f5-89e5-4cb1-a40d-6aa912ba31d7",
            "name": "Customers",
            "description": "Customers eligible for launch outreach.",
            "project": {
                "key": "3efc2ad0-8d28-44bc-a554-cb3eab89f45a",
                "name": "Launch",
                "description": "Launch datasets",
            },
            "section": None,
            "column_count": 2,
            "row_count": 42,
            "updated_at": "2026-05-14T00:01:00Z",
            "archived_at": None,
        }

    anyio.run(run)


def test_get_archived_datasets_mcp_tool_returns_archived_dataset_metadata(monkeypatch):
    calls = []

    def list_archived(authenticated_profile, limit=100, offset=0):
        calls.append((authenticated_profile.id, limit, offset))
        return {
            "count": 1,
            "total_count": 1,
            "limit": limit,
            "offset": offset,
            "has_more": False,
            "datasets": [
                {
                    "key": "6b0fe8f5-89e5-4cb1-a40d-6aa912ba31d7",
                    "name": "Archived customers",
                    "archived_at": "2026-05-15T00:00:00Z",
                }
            ],
        }

    async def run():
        monkeypatch.setattr(
            "apps.mcp_server.server._authenticate_profile",
            lambda: _profile(),
        )
        monkeypatch.setattr(
            "apps.mcp_server.server.serialize_profile_archived_datasets",
            list_archived,
        )

        async with Client(mcp) as client:
            result = await client.call_tool("get_archived_datasets", {"limit": 5})

        assert result.data["count"] == 1
        assert result.data["datasets"][0]["name"] == "Archived customers"
        assert result.data["datasets"][0]["archived_at"] == "2026-05-15T00:00:00Z"
        assert calls == [(11, 5, 0)]

    anyio.run(run)


def test_get_dataset_mcp_tool_returns_single_dataset_metadata(monkeypatch):
    async def run():
        profile = _profile()
        dataset = profile.datasets.only().__getitem__(slice(0, 100, None))[0]
        monkeypatch.setattr(
            "apps.mcp_server.server._authenticate_profile",
            lambda: profile,
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
        assert payload["description"] == "Customers eligible for launch outreach."
        assert payload["instructions"] == (
            "Use email as the stable identity. Do not rewrite names from guesses."
        )
        assert payload["metadata"] == {"workflow": {"default_status": "new"}}
        assert payload["headers"] == ["email", "name"]
        assert payload["column_schema"]["email"]["description"] == (
            "Primary contact address for the customer."
        )
        assert payload["index_column"] == "email"
        assert payload["index_generated"] is False
        assert payload["public_enabled"] is False
        assert payload["public_key"] == "4b7b8e47-15a5-4bd5-82cb-8c4f4fd40ce9"
        assert payload["public_page_size"] == 10
        assert payload["public_url"] is None
        assert payload["relationships"] == {"outgoing": [], "incoming": []}
        assert "rows" not in payload

    anyio.run(run)


def test_search_mcp_tools_call_search_services(monkeypatch):
    calls = []

    def search_datasets(
        authenticated_profile,
        *,
        query=None,
        project_key=None,
        section_key=None,
        header_contains=None,
        updated_after=None,
        limit=100,
        offset=0,
    ):
        calls.append(
            (
                "search_datasets",
                authenticated_profile.id,
                query,
                project_key,
                section_key,
                header_contains,
                updated_after,
                limit,
                offset,
            )
        )
        return {
            "count": 1,
            "total_count": 1,
            "limit": limit,
            "offset": offset,
            "has_more": False,
            "datasets": [{"key": "dataset-key", "name": "Feature Suggestions"}],
        }

    def search_projects(authenticated_profile, *, query=None, limit=100, offset=0):
        calls.append(("search_projects", authenticated_profile.id, query, limit, offset))
        return {
            "count": 1,
            "total_count": 1,
            "limit": limit,
            "offset": offset,
            "has_more": False,
            "projects": [{"key": "project-key", "name": "Rowset"}],
        }

    def search_rows(authenticated_profile, dataset_key, *, query, filters=None, limit=10):
        calls.append(
            (
                "search_dataset_rows",
                authenticated_profile.id,
                dataset_key,
                query,
                filters,
                limit,
            )
        )
        return {
            "dataset": dataset_key,
            "query": query,
            "filters": filters or {},
            "limit": limit,
            "count": 1,
            "results": [{"rank": 1, "row": {"id": 1}, "match": {"source": "hybrid"}}],
        }

    def search_all_rows(
        authenticated_profile,
        *,
        query,
        filters=None,
        filter_operators=None,
        dataset_key=None,
        project_key=None,
        section_key=None,
        archived=False,
        sort=None,
        direction=None,
        limit=10,
    ):
        calls.append(
            (
                "search_rows",
                authenticated_profile.id,
                query,
                filters,
                filter_operators,
                dataset_key,
                project_key,
                section_key,
                archived,
                sort,
                direction,
                limit,
            )
        )
        return {
            "query": query,
            "filters": filters or {},
            "filter_operators": filter_operators or {},
            "dataset_filters": {
                "dataset_key": dataset_key,
                "project_key": project_key,
                "section_key": section_key,
                "archived": archived,
            },
            "sort": sort or "rank",
            "direction": direction or "desc",
            "limit": limit,
            "count": 1,
            "results": [{"rank": 1, "dataset": {"key": "dataset-key"}, "row": {"id": 1}}],
        }

    async def run():
        monkeypatch.setattr(
            "apps.mcp_server.server._authenticate_profile",
            lambda: _profile(),
        )
        monkeypatch.setattr("apps.mcp_server.server.search_profile_datasets", search_datasets)
        monkeypatch.setattr("apps.mcp_server.server.search_profile_projects", search_projects)
        monkeypatch.setattr("apps.mcp_server.server.search_profile_dataset_rows", search_rows)
        monkeypatch.setattr("apps.mcp_server.server.search_profile_rows", search_all_rows)

        async with Client(mcp) as client:
            dataset_result = await client.call_tool(
                "search_datasets",
                {
                    "query": "feature",
                    "project_key": "project-key",
                    "section_key": "section-key",
                    "header_contains": "suggestion_id",
                    "updated_after": "2026-06-01",
                    "limit": 5,
                    "offset": 2,
                },
            )
            project_result = await client.call_tool(
                "search_projects",
                {"query": "rowset", "limit": 3},
            )
            row_result = await client.call_tool(
                "search_dataset_rows",
                {
                    "dataset_key": "dataset-key",
                    "query": "stale vectors",
                    "filters": '{"status": "Ready", "active": true}',
                    "limit": None,
                },
            )
            all_rows_result = await client.call_tool(
                "search_rows",
                {
                    "query": "renewal risk",
                    "filters": '{"status": "Ready", "active": true}',
                    "filter_operators": {"status": "is"},
                    "dataset_key": "dataset-key",
                    "project_key": "project-key",
                    "section_key": "section-key",
                    "archived": False,
                    "sort": "rank",
                    "direction": "desc",
                    "limit": None,
                },
            )

        assert dataset_result.data["datasets"][0]["key"] == "dataset-key"
        assert project_result.data["projects"][0]["key"] == "project-key"
        assert row_result.data["results"][0]["match"]["source"] == "hybrid"
        assert all_rows_result.data["results"][0]["dataset"]["key"] == "dataset-key"
        assert calls == [
            (
                "search_datasets",
                11,
                "feature",
                "project-key",
                "section-key",
                "suggestion_id",
                "2026-06-01",
                5,
                2,
            ),
            ("search_projects", 11, "rowset", 3, 0),
            (
                "search_dataset_rows",
                11,
                "dataset-key",
                "stale vectors",
                {"status": "Ready", "active": "true"},
                10,
            ),
            (
                "search_rows",
                11,
                "renewal risk",
                {"status": "Ready", "active": "true"},
                {"status": "is"},
                "dataset-key",
                "project-key",
                "section-key",
                False,
                "rank",
                "desc",
                10,
            ),
        ]

    anyio.run(run)


def test_project_mcp_tools_call_project_services(monkeypatch):  # noqa: C901
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

    def create_project(authenticated_profile, *, name, description=None, metadata=None):
        calls.append(("create_project", authenticated_profile.id, name, description, metadata))
        return {
            "status": "success",
            "message": "Project created.",
            "project": {
                "key": "project-key",
                "name": name,
                "description": description,
                "metadata": metadata,
            },
        }

    def create_project_section(
        authenticated_profile,
        project_key,
        *,
        name,
        description=None,
        metadata=None,
    ):
        calls.append(
            (
                "create_project_section",
                authenticated_profile.id,
                project_key,
                name,
                description,
                metadata,
            )
        )
        return {
            "status": "success",
            "message": "Project section created.",
            "section": {
                "key": "section-key",
                "name": name,
                "description": description,
                "metadata": metadata,
            },
        }

    def list_project_sections(authenticated_profile, project_key, limit=100, offset=0):
        calls.append(
            ("list_project_sections", authenticated_profile.id, project_key, limit, offset)
        )
        return {
            "count": 1,
            "total_count": 1,
            "limit": limit,
            "offset": offset,
            "has_more": False,
            "sections": [{"key": "section-key", "name": "Blog"}],
        }

    def update_project_section(
        authenticated_profile,
        project_key,
        section_key,
        *,
        name=None,
        description=None,
    ):
        calls.append(
            (
                "update_project_section",
                authenticated_profile.id,
                project_key,
                section_key,
                name,
                description,
            )
        )
        return {
            "status": "success",
            "message": "Project section updated.",
            "section": {"key": section_key, "name": name, "description": description},
        }

    def archive_project_section(authenticated_profile, project_key, section_key):
        calls.append(
            ("archive_project_section", authenticated_profile.id, project_key, section_key)
        )
        return {
            "status": "success",
            "message": "Project section archived.",
            "section": {"key": section_key, "archived_at": "2026-05-14T00:00:00Z"},
        }

    def get_project(authenticated_profile, project_key, limit=100, offset=0):
        calls.append(("get_project", authenticated_profile.id, project_key, limit, offset))
        return {
            "status": "success",
            "message": "Project retrieved.",
            "project": {"key": project_key, "name": "Launch"},
            "datasets": {"count": 0, "datasets": []},
        }

    def update_project_details(authenticated_profile, project_key, *, name=None, description=None):
        calls.append(
            (
                "update_project_details",
                authenticated_profile.id,
                project_key,
                name,
                description,
            )
        )
        return {
            "status": "success",
            "message": "Project updated.",
            "project": {"key": project_key, "name": name, "description": description},
        }

    def update_dataset_project(
        authenticated_profile,
        dataset_key,
        project_key,
        section_key=None,
        agent_api_key=None,
    ):
        calls.append(
            (
                "update_dataset_project",
                authenticated_profile.id,
                dataset_key,
                project_key,
                section_key,
            )
        )
        return {
            "status": "success",
            "message": "Dataset project updated.",
            "dataset": {
                "key": dataset_key,
                "project": {"key": project_key},
                "section": {"key": section_key},
            },
        }

    def update_project_metadata(authenticated_profile, project_key, **kwargs):
        calls.append(("update_project_metadata", authenticated_profile.id, project_key, kwargs))
        return {
            "status": "success",
            "message": "Project metadata updated.",
            "project": {"key": project_key, "metadata": kwargs.get("metadata", {})},
        }

    def archive_project(authenticated_profile, project_key):
        calls.append(("archive_project", authenticated_profile.id, project_key))
        return {
            "status": "success",
            "message": "Project archived.",
            "project": {"key": project_key, "archived_at": "2026-05-14T00:00:00Z"},
        }

    async def run():
        monkeypatch.setattr(
            "apps.mcp_server.server._authenticate_profile",
            lambda: _profile(),
        )
        monkeypatch.setattr("apps.mcp_server.server.serialize_profile_projects", list_projects)
        monkeypatch.setattr("apps.mcp_server.server.create_profile_project", create_project)
        monkeypatch.setattr(
            "apps.mcp_server.server.create_profile_project_section",
            create_project_section,
        )
        monkeypatch.setattr(
            "apps.mcp_server.server.serialize_profile_project_sections",
            list_project_sections,
        )
        monkeypatch.setattr(
            "apps.mcp_server.server.update_profile_project_section",
            update_project_section,
        )
        monkeypatch.setattr(
            "apps.mcp_server.server.archive_profile_project_section",
            archive_project_section,
        )
        monkeypatch.setattr("apps.mcp_server.server.serialize_profile_project_detail", get_project)
        monkeypatch.setattr("apps.mcp_server.server.update_profile_project", update_project_details)
        monkeypatch.setattr(
            "apps.mcp_server.server.update_profile_dataset_project",
            update_dataset_project,
        )
        monkeypatch.setattr(
            "apps.mcp_server.server.update_profile_project_metadata",
            update_project_metadata,
        )
        monkeypatch.setattr("apps.mcp_server.server.archive_profile_project", archive_project)

        async with Client(mcp) as client:
            list_result = await client.call_tool(
                "get_all_projects",
                {"limit": 5},
            )
            create_result = await client.call_tool(
                "create_project",
                {
                    "name": "Launch",
                    "description": "Launch datasets",
                    "metadata": {"github_repo": "https://github.com/acme/launch"},
                },
            )
            detail_result = await client.call_tool(
                "get_project",
                {"project_key": "project-key", "limit": 2},
            )
            section_create_result = await client.call_tool(
                "create_project_section",
                {
                    "project_key": "project-key",
                    "name": "Blog",
                    "description": "Content operations datasets",
                    "metadata": {"goal": "content-led growth"},
                },
            )
            section_list_result = await client.call_tool(
                "get_project_sections",
                {"project_key": "project-key", "limit": 10},
            )
            section_update_result = await client.call_tool(
                "update_project_section",
                {
                    "project_key": "project-key",
                    "section_key": "section-key",
                    "name": "Editorial",
                    "description": "",
                },
            )
            section_archive_result = await client.call_tool(
                "archive_project_section",
                {"project_key": "project-key", "section_key": "section-key"},
            )
            update_project_result = await client.call_tool(
                "update_project",
                {
                    "project_key": "project-key",
                    "name": "Launch operations",
                    "description": "",
                },
            )
            metadata_result = await client.call_tool(
                "update_project_metadata",
                {
                    "project_key": "project-key",
                    "metadata": {"notion_doc": "https://notion.so/acme/launch"},
                },
            )
            archive_result = await client.call_tool(
                "archive_project",
                {"project_key": "project-key"},
            )
            update_result = await client.call_tool(
                "update_dataset_project",
                {
                    "dataset_key": "dataset-key",
                    "project_key": "project-key",
                    "section_key": "section-key",
                },
            )

        assert list_result.data["projects"][0]["key"] == "project-key"
        assert create_result.data["project"]["name"] == "Launch"
        assert create_result.data["project"]["metadata"]["github_repo"] == (
            "https://github.com/acme/launch"
        )
        assert detail_result.data["project"]["key"] == "project-key"
        assert section_create_result.data["section"]["name"] == "Blog"
        assert section_list_result.data["sections"][0]["key"] == "section-key"
        assert section_update_result.data["section"]["name"] == "Editorial"
        assert section_archive_result.data["section"]["archived_at"] == "2026-05-14T00:00:00Z"
        assert update_project_result.data["project"]["name"] == "Launch operations"
        assert update_project_result.data["project"]["description"] == ""
        assert metadata_result.data["project"]["metadata"]["notion_doc"] == (
            "https://notion.so/acme/launch"
        )
        assert archive_result.data["project"]["archived_at"] == "2026-05-14T00:00:00Z"
        assert update_result.data["dataset"]["project"]["key"] == "project-key"
        assert update_result.data["dataset"]["section"]["key"] == "section-key"
        assert calls == [
            ("list_projects", 11, 5, 0),
            (
                "create_project",
                11,
                "Launch",
                "Launch datasets",
                {"github_repo": "https://github.com/acme/launch"},
            ),
            ("get_project", 11, "project-key", 2, 0),
            (
                "create_project_section",
                11,
                "project-key",
                "Blog",
                "Content operations datasets",
                {"goal": "content-led growth"},
            ),
            ("list_project_sections", 11, "project-key", 10, 0),
            (
                "update_project_section",
                11,
                "project-key",
                "section-key",
                "Editorial",
                "",
            ),
            ("archive_project_section", 11, "project-key", "section-key"),
            (
                "update_project_details",
                11,
                "project-key",
                "Launch operations",
                "",
            ),
            (
                "update_project_metadata",
                11,
                "project-key",
                {"metadata": {"notion_doc": "https://notion.so/acme/launch"}},
            ),
            ("archive_project", 11, "project-key"),
            ("update_dataset_project", 11, "dataset-key", "project-key", "section-key"),
        ]

    anyio.run(run)


def test_create_dataset_mcp_tool_calls_dataset_service(monkeypatch):
    calls = []

    def create_dataset(
        authenticated_profile,
        *,
        name,
        description=None,
        instructions=None,
        metadata=None,
        headers=None,
        rows=None,
        index_column=None,
        column_types=None,
        project_key=None,
        section_key=None,
        agent_api_key=None,
    ):
        calls.append(
            (
                authenticated_profile.id,
                name,
                description,
                instructions,
                metadata,
                headers,
                rows,
                index_column,
                column_types,
                project_key,
                section_key,
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
            lambda: _profile(),
        )
        monkeypatch.setattr("apps.mcp_server.server.create_profile_dataset", create_dataset)

        async with Client(mcp) as client:
            result = await client.call_tool(
                "create_dataset",
                {
                    "name": "Products",
                    "description": "Supplier catalog.",
                    "instructions": "Use sku as the stable identity.",
                    "metadata": {"workflow": {"default_status": "draft"}},
                    "headers": ["sku", "name", "topics"],
                    "rows": [
                        {
                            "sku": "A-1",
                            "name": "Adapter",
                            "topics": " Django, HTMX, , django ,  ",
                        }
                    ],
                    "index_column": "sku",
                    "column_types": {"sku": "text", "name": "text", "topics": "tags"},
                    "project_key": "project-key",
                    "section_key": "section-key",
                },
            )

        assert result.data["dataset"]["key"] == "dataset-key"
        assert calls == [
            (
                11,
                "Products",
                "Supplier catalog.",
                "Use sku as the stable identity.",
                {"workflow": {"default_status": "draft"}},
                ["sku", "name", "topics"],
                [
                    {
                        "sku": "A-1",
                        "name": "Adapter",
                        "topics": " Django, HTMX, , django ,  ",
                    }
                ],
                "sku",
                {"sku": "text", "name": "text", "topics": "tags"},
                "project-key",
                "section-key",
            )
        ]

    anyio.run(run)


def test_update_dataset_metadata_mcp_tool_calls_dataset_service(monkeypatch):
    calls = []

    def update_metadata(
        authenticated_profile,
        dataset_key,
        *,
        description=None,
        instructions=None,
        metadata=None,
        agent_api_key=None,
    ):
        calls.append((authenticated_profile.id, dataset_key, description, instructions, metadata))
        return {
            "status": "success",
            "message": "Dataset metadata updated.",
            "dataset": {
                "key": dataset_key,
                "description": description,
                "instructions": instructions,
                "metadata": metadata,
            },
        }

    async def run():
        monkeypatch.setattr(
            "apps.mcp_server.server._authenticate_profile",
            lambda: _profile(),
        )
        monkeypatch.setattr(
            "apps.mcp_server.server.update_profile_dataset_metadata",
            update_metadata,
        )

        async with Client(mcp) as client:
            result = await client.call_tool(
                "update_dataset_metadata",
                {
                    "dataset_key": "ds",
                    "description": "Task board.",
                    "instructions": "Keep status transitions explicit.",
                    "metadata": {"status_order": ["todo", "doing", "done"]},
                },
            )

        assert result.data["message"] == "Dataset metadata updated."
        assert calls == [
            (
                11,
                "ds",
                "Task board.",
                "Keep status transitions explicit.",
                {"status_order": ["todo", "doing", "done"]},
            )
        ]

    anyio.run(run)


def test_update_dataset_metadata_mcp_tool_treats_null_metadata_as_omitted(monkeypatch):
    calls = []

    def update_metadata(authenticated_profile, dataset_key, **kwargs):
        kwargs.pop("agent_api_key", None)
        calls.append((authenticated_profile.id, dataset_key, kwargs))
        return {
            "status": "success",
            "message": "Dataset metadata updated.",
            "dataset": {
                "key": dataset_key,
                "description": "Existing task board.",
                "instructions": kwargs.get("instructions", "Existing instructions."),
                "metadata": {"status_order": ["todo", "doing", "done"]},
            },
        }

    async def run():
        monkeypatch.setattr(
            "apps.mcp_server.server._authenticate_profile",
            lambda: _profile(),
        )
        monkeypatch.setattr(
            "apps.mcp_server.server.update_profile_dataset_metadata",
            update_metadata,
        )

        async with Client(mcp) as client:
            result = await client.call_tool(
                "update_dataset_metadata",
                {
                    "dataset_key": "ds",
                    "instructions": "Keep status transitions explicit.",
                    "metadata": None,
                },
            )

        assert result.data["message"] == "Dataset metadata updated."
        assert calls == [
            (
                11,
                "ds",
                {"instructions": "Keep status transitions explicit."},
            )
        ]

    anyio.run(run)


def test_dataset_row_mcp_tools_call_dataset_services(monkeypatch):
    calls = []

    def profile():
        return _profile()

    def list_rows(
        authenticated_profile,
        dataset_key,
        limit=100,
        offset=0,
        query=None,
        filters=None,
        sort=None,
        direction=None,
    ):
        calls.append(("list", dataset_key, limit, offset, query, filters, sort, direction))
        return {
            "dataset": dataset_key,
            "count": 1,
            "total_count": 2,
            "limit": limit,
            "offset": offset,
            "has_more": False,
            "query": query or "",
            "filters": filters or {},
            "sort": sort or "row_number",
            "direction": direction or "asc",
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

    def create_row(authenticated_profile, dataset_key, data, agent_api_key=None):
        calls.append(("create", dataset_key, data))
        return {"status": "success", "message": "Row created.", "row": {"data": data}}

    def update_row(authenticated_profile, dataset_key, row_id, data, agent_api_key=None):
        calls.append(("update", dataset_key, row_id, data))
        return {"status": "success", "message": "Row updated.", "row": {"id": row_id, "data": data}}

    def update_row_by_index(
        authenticated_profile, dataset_key, index_value, data, agent_api_key=None
    ):
        calls.append(("update_by_index", dataset_key, index_value, data))
        return {
            "status": "success",
            "message": "Row updated.",
            "row": {"index_value": index_value, "data": data},
        }

    def delete_row(authenticated_profile, dataset_key, row_id, agent_api_key=None):
        calls.append(("delete", dataset_key, row_id))
        return {"status": "success", "message": "Row deleted."}

    async def run():
        monkeypatch.setattr(
            "apps.mcp_server.server._authenticate_profile",
            lambda: profile(),
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
                {
                    "dataset_key": "ds",
                    "limit": 5,
                    "query": "ada",
                    "filters": {"active": "true"},
                    "sort": "email",
                    "direction": "desc",
                },
            )
            tolerant_list_result = await client.call_tool(
                "list_dataset_rows",
                {
                    "dataset_key": "ds",
                    "limit": None,
                    "offset": None,
                    "filters": '{"active": true, "score": 7, "empty": null}',
                },
            )
            with pytest.raises(Exception) as invalid_filters:
                await client.call_tool(
                    "list_dataset_rows",
                    {"dataset_key": "ds", "filters": "active=true"},
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
                {
                    "dataset_key": "ds",
                    "data": {"email": "b@example.com", "score": 42},
                },
            )
            update_result = await client.call_tool(
                "update_dataset_row",
                {
                    "dataset_key": "ds",
                    "row_id": 7,
                    "data": {"email": "c@example.com", "empty": None},
                },
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
        assert tolerant_list_result.data["count"] == 1
        assert get_result.data["row"]["id"] == 7
        assert get_by_index_result.data["row"]["index_value"] == "a@example.com"
        assert create_result.data["row"]["data"]["email"] == "b@example.com"
        assert create_result.data["row"]["data"]["score"] == 42
        assert update_result.data["row"]["data"]["email"] == "c@example.com"
        assert update_result.data["row"]["data"]["empty"] is None
        assert update_by_index_result.data["row"]["data"]["name"] == "Ada"
        assert delete_result.data["message"] == "Row deleted."

        assert list_result.data["filters"] == {"active": "true"}
        assert list_result.data["sort"] == "email"
        assert tolerant_list_result.data["filters"] == {
            "active": "true",
            "score": "7",
            "empty": "",
        }
        assert _extract_mcp_error_payload(invalid_filters.value) == _expected_mcp_error(
            code="VALIDATION_ERROR",
            message="filters must be a JSON object keyed by dataset header.",
            suggested_action="Check the tool arguments against the dataset schema and try again.",
            http_status=400,
        )

        assert calls == [
            ("list", "ds", 5, 0, "ada", {"active": "true"}, "email", "desc"),
            (
                "list",
                "ds",
                100,
                0,
                None,
                {"active": "true", "score": "7", "empty": ""},
                None,
                None,
            ),
            ("get", "ds", 7),
            ("get_by_index", "ds", "a@example.com"),
            ("create", "ds", {"email": "b@example.com", "score": 42}),
            ("update", "ds", 7, {"email": "c@example.com", "empty": None}),
            ("update_by_index", "ds", "c@example.com", {"name": "Ada"}),
            ("delete", "ds", 7),
        ]

    anyio.run(run)


def test_dataset_image_mcp_tools_call_dataset_services(monkeypatch):
    calls = []

    def attach_image(
        authenticated_profile,
        dataset_key,
        *,
        column_name,
        image_base64,
        filename=None,
        content_type=None,
        row_id=None,
        index_value=None,
        agent_api_key=None,
    ):
        calls.append(
            (
                "attach",
                authenticated_profile.id,
                dataset_key,
                row_id,
                index_value,
                column_name,
                image_base64,
                filename,
                content_type,
                getattr(agent_api_key, "id", None),
            )
        )
        return {
            "status": "success",
            "message": "Image attached.",
            "dataset": dataset_key,
            "row": {"id": row_id, "data": {column_name: "asset:asset-key"}},
            "asset": {"key": "asset-key", "ref": "asset:asset-key"},
        }

    def get_asset(authenticated_profile, dataset_key, asset_key):
        calls.append(("get_asset", authenticated_profile.id, dataset_key, asset_key))
        return {
            "status": "success",
            "message": "Dataset asset retrieved.",
            "asset": {"key": asset_key, "ref": f"asset:{asset_key}"},
        }

    async def run():
        monkeypatch.setattr(
            "apps.mcp_server.server._authenticate_profile",
            lambda: _profile(),
        )
        monkeypatch.setattr(
            "apps.mcp_server.server.attach_profile_dataset_image_asset",
            attach_image,
        )
        monkeypatch.setattr(
            "apps.mcp_server.server.serialize_profile_dataset_asset",
            get_asset,
        )

        async with Client(mcp) as client:
            attach_result = await client.call_tool(
                "attach_image_to_dataset_row",
                {
                    "dataset_key": "ds",
                    "row_id": 7,
                    "column_name": "photo",
                    "image_base64": "aW1hZ2U=",
                    "filename": "photo.png",
                    "content_type": "image/png",
                },
            )
            asset_result = await client.call_tool(
                "get_dataset_image_asset",
                {"dataset_key": "ds", "asset_key": "asset-key"},
            )

        assert attach_result.data["message"] == "Image attached."
        assert asset_result.data["asset"]["ref"] == "asset:asset-key"
        assert calls == [
            (
                "attach",
                11,
                "ds",
                7,
                None,
                "photo",
                "aW1hZ2U=",
                "photo.png",
                "image/png",
                3,
            ),
            ("get_asset", 11, "ds", "asset-key"),
        ]

    anyio.run(run)


def test_dataset_audio_mcp_tools_call_dataset_services(monkeypatch):
    calls = []

    def attach_audio(
        authenticated_profile,
        dataset_key,
        *,
        column_name,
        audio_base64,
        filename=None,
        content_type=None,
        row_id=None,
        index_value=None,
        agent_api_key=None,
    ):
        calls.append(
            (
                "attach",
                authenticated_profile.id,
                dataset_key,
                row_id,
                index_value,
                column_name,
                audio_base64,
                filename,
                content_type,
                getattr(agent_api_key, "id", None),
            )
        )
        return {
            "status": "success",
            "message": "Audio attached.",
            "dataset": dataset_key,
            "row": {"id": row_id, "data": {column_name: "asset:asset-key"}},
            "asset": {"key": "asset-key", "ref": "asset:asset-key"},
        }

    def get_asset(authenticated_profile, dataset_key, asset_key):
        calls.append(("get_asset", authenticated_profile.id, dataset_key, asset_key))
        return {
            "status": "success",
            "message": "Dataset asset retrieved.",
            "asset": {"key": asset_key, "ref": f"asset:{asset_key}"},
        }

    async def run():
        monkeypatch.setattr(
            "apps.mcp_server.server._authenticate_profile",
            lambda: _profile(),
        )
        monkeypatch.setattr(
            "apps.mcp_server.server.attach_profile_dataset_audio_asset",
            attach_audio,
        )
        monkeypatch.setattr(
            "apps.mcp_server.server.serialize_profile_dataset_asset",
            get_asset,
        )

        async with Client(mcp) as client:
            attach_result = await client.call_tool(
                "attach_audio_to_dataset_row",
                {
                    "dataset_key": "ds",
                    "row_id": 7,
                    "column_name": "audio",
                    "audio_base64": "YXVkaW8=",
                    "filename": "clip.wav",
                    "content_type": "audio/wav",
                },
            )
            asset_result = await client.call_tool(
                "get_dataset_audio_asset",
                {"dataset_key": "ds", "asset_key": "asset-key"},
            )

        assert attach_result.data["message"] == "Audio attached."
        assert asset_result.data["asset"]["ref"] == "asset:asset-key"
        assert calls == [
            (
                "attach",
                11,
                "ds",
                7,
                None,
                "audio",
                "YXVkaW8=",
                "clip.wav",
                "audio/wav",
                3,
            ),
            ("get_asset", 11, "ds", "asset-key"),
        ]

    anyio.run(run)


def test_dataset_relationship_mcp_tools_call_dataset_services(monkeypatch):
    calls = []
    relationship_payload = {
        "key": "relationship-key",
        "name": "Message person",
        "source_dataset": {
            "key": "messages-key",
            "name": "CRM Messages",
            "index_column": "message_id",
        },
        "source_column": "person_id",
        "target_dataset": {
            "key": "people-key",
            "name": "People",
            "index_column": "person_id",
        },
        "target_index_column": "person_id",
        "enforce_integrity": True,
        "created_at": "2026-06-25T00:00:00Z",
        "updated_at": "2026-06-25T00:00:00Z",
    }

    def list_relationships(authenticated_profile, dataset_key):
        calls.append(("list", authenticated_profile.id, dataset_key))
        return {"dataset": dataset_key, "relationships": [relationship_payload]}

    def create_relationship(
        authenticated_profile,
        dataset_key,
        *,
        source_column,
        target_dataset_key,
        name=None,
        enforce_integrity=True,
        agent_api_key=None,
    ):
        calls.append(
            (
                "create",
                authenticated_profile.id,
                dataset_key,
                source_column,
                target_dataset_key,
                name,
                enforce_integrity,
            )
        )
        return {
            "status": "success",
            "message": "Relationship created.",
            "relationship": relationship_payload,
        }

    def resolve_relationship(
        authenticated_profile,
        dataset_key,
        relationship_key,
        *,
        source_index_value,
    ):
        calls.append(
            (
                "resolve",
                authenticated_profile.id,
                dataset_key,
                relationship_key,
                source_index_value,
            )
        )
        return {
            "status": "success",
            "message": "Related row resolved.",
            "relationship": relationship_payload,
            "source_row": {
                "id": 2,
                "row_number": 1,
                "index_value": "M-1",
                "data": {"message_id": "M-1", "person_id": "P-1"},
            },
            "target_index_value": "P-1",
            "target_row": {
                "id": 1,
                "row_number": 1,
                "index_value": "P-1",
                "data": {"person_id": "P-1", "name": "Ada Lovelace"},
            },
        }

    def delete_relationship(
        authenticated_profile, dataset_key, relationship_key, agent_api_key=None
    ):
        calls.append(("delete", authenticated_profile.id, dataset_key, relationship_key))
        return {
            "status": "success",
            "message": "Relationship deleted.",
            "relationship": relationship_payload,
        }

    async def run():
        monkeypatch.setattr(
            "apps.mcp_server.server._authenticate_profile",
            lambda: _profile(),
        )
        monkeypatch.setattr(
            "apps.mcp_server.server.list_profile_dataset_relationships",
            list_relationships,
        )
        monkeypatch.setattr(
            "apps.mcp_server.server.create_profile_dataset_relationship",
            create_relationship,
        )
        monkeypatch.setattr(
            "apps.mcp_server.server.resolve_profile_dataset_relationship",
            resolve_relationship,
        )
        monkeypatch.setattr(
            "apps.mcp_server.server.delete_profile_dataset_relationship",
            delete_relationship,
        )

        async with Client(mcp) as client:
            list_result = await client.call_tool(
                "list_dataset_relationships",
                {"dataset_key": "messages-key"},
            )
            create_result = await client.call_tool(
                "create_dataset_relationship",
                {
                    "dataset_key": "messages-key",
                    "source_column": "person_id",
                    "target_dataset_key": "people-key",
                    "name": "Message person",
                    "enforce_integrity": True,
                },
            )
            resolve_result = await client.call_tool(
                "resolve_dataset_relationship",
                {
                    "dataset_key": "messages-key",
                    "relationship_key": "relationship-key",
                    "source_index_value": "M-1",
                },
            )
            delete_result = await client.call_tool(
                "delete_dataset_relationship",
                {
                    "dataset_key": "messages-key",
                    "relationship_key": "relationship-key",
                },
            )

        assert list_result.data["relationships"][0]["key"] == "relationship-key"
        assert create_result.data["relationship"]["source_column"] == "person_id"
        assert resolve_result.data["target_row"]["data"]["name"] == "Ada Lovelace"
        assert delete_result.data["message"] == "Relationship deleted."
        assert calls == [
            ("list", 11, "messages-key"),
            (
                "create",
                11,
                "messages-key",
                "person_id",
                "people-key",
                "Message person",
                True,
            ),
            ("resolve", 11, "messages-key", "relationship-key", "M-1"),
            ("delete", 11, "messages-key", "relationship-key"),
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
    setattr(
        user.profile,
        AGENT_API_KEY_PROFILE_ATTR,
        SimpleNamespace(id=1, access_level=AgentApiKeyAccessLevel.READ),
    )

    monkeypatch.setattr(
        "apps.mcp_server.server._authenticate_profile",
        lambda: user.profile,
    )

    result = mcp_get_dataset_row(public_row_url, row.id)

    assert result["dataset"] == str(dataset.key)
    assert result["row"]["id"] == row.id
    assert result["row"]["data"]["email"] == "ada@example.com"


def test_update_dataset_column_types_mcp_tool_calls_dataset_service(monkeypatch):
    calls = []

    def update_column_types(authenticated_profile, dataset_key, column_types, agent_api_key=None):
        calls.append((authenticated_profile.id, dataset_key, column_types))
        return {
            "status": "success",
            "message": "Column types updated.",
            "dataset": {"key": dataset_key, "column_schema": {"email": {"type": "text"}}},
        }

    async def run():
        monkeypatch.setattr(
            "apps.mcp_server.server._authenticate_profile",
            lambda: _profile(),
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


def test_choice_column_metadata_mcp_tools_call_dataset_services(monkeypatch):
    calls = []
    choice_schema = {
        "type": "choice",
        "choices": ["Ready to do", "Doing", "Done"],
    }

    def create_dataset(
        authenticated_profile,
        *,
        name,
        description=None,
        instructions=None,
        metadata=None,
        headers=None,
        rows=None,
        index_column=None,
        column_types=None,
        project_key=None,
        section_key=None,
        agent_api_key=None,
    ):
        calls.append(("create", authenticated_profile.id, column_types))
        return {
            "status": "success",
            "message": "Dataset created.",
            "dataset": {"key": "dataset-key", "column_schema": {"status": choice_schema}},
        }

    def update_column_types(authenticated_profile, dataset_key, column_types, agent_api_key=None):
        calls.append(("update", authenticated_profile.id, dataset_key, column_types))
        return {
            "status": "success",
            "message": "Column types updated.",
            "dataset": {"key": dataset_key, "column_schema": {"status": choice_schema}},
        }

    async def run():
        monkeypatch.setattr(
            "apps.mcp_server.server._authenticate_profile",
            lambda: _profile(),
        )
        monkeypatch.setattr("apps.mcp_server.server.create_profile_dataset", create_dataset)
        monkeypatch.setattr(
            "apps.mcp_server.server.update_profile_dataset_column_types",
            update_column_types,
        )

        async with Client(mcp) as client:
            create_result = await client.call_tool(
                "create_dataset",
                {
                    "name": "Task board",
                    "headers": ["task_id", "status"],
                    "rows": [{"task_id": "T-1", "status": "Ready to do"}],
                    "index_column": "task_id",
                    "column_types": {"status": choice_schema},
                },
            )
            update_result = await client.call_tool(
                "update_dataset_column_types",
                {
                    "dataset_key": "ds",
                    "column_types": {"status": choice_schema},
                },
            )

        assert create_result.data["dataset"]["column_schema"]["status"] == choice_schema
        assert update_result.data["dataset"]["column_schema"]["status"] == choice_schema
        assert calls == [
            ("create", 11, {"status": choice_schema}),
            ("update", 11, "ds", {"status": choice_schema}),
        ]

    anyio.run(run)


def test_schema_mutation_mcp_tools_call_dataset_services(monkeypatch):
    calls = []
    choice_schema = {"type": "choice", "choices": ["internal", "shared"]}

    def add_column(
        authenticated_profile,
        dataset_key,
        *,
        name,
        default_value="",
        column_type=None,
        agent_api_key=None,
    ):
        calls.append(
            ("add", authenticated_profile.id, dataset_key, name, default_value, column_type)
        )
        return {
            "status": "success",
            "message": "Column added.",
            "dataset": {"key": dataset_key, "headers": ["email", name]},
        }

    def rename_column(
        authenticated_profile, dataset_key, *, old_name, new_name, agent_api_key=None
    ):
        calls.append(("rename", authenticated_profile.id, dataset_key, old_name, new_name))
        return {
            "status": "success",
            "message": "Column renamed.",
            "dataset": {"key": dataset_key, "headers": [new_name]},
        }

    def drop_column(authenticated_profile, dataset_key, *, name, agent_api_key=None):
        calls.append(("drop", authenticated_profile.id, dataset_key, name))
        return {
            "status": "success",
            "message": "Column dropped.",
            "dataset": {"key": dataset_key, "headers": ["email"]},
        }

    def reorder_columns(authenticated_profile, dataset_key, *, headers, agent_api_key=None):
        calls.append(("reorder", authenticated_profile.id, dataset_key, headers))
        return {
            "status": "success",
            "message": "Columns reordered.",
            "dataset": {"key": dataset_key, "headers": headers},
        }

    async def run():
        monkeypatch.setattr(
            "apps.mcp_server.server._authenticate_profile",
            lambda: _profile(),
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
                    "column_type": choice_schema,
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
            ("add", 11, "ds", "visibility_level", "internal", choice_schema),
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
        agent_api_key=None,
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
            lambda: _profile(),
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
            lambda: _profile(),
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


@pytest.mark.parametrize(
    ("service_error", "expected_payload"),
    [
        (
            DatasetServiceError(404, "Row not found."),
            _expected_mcp_error(
                code="ROW_NOT_FOUND",
                message="Row not found.",
                suggested_action="Check the row id or index value and try again.",
                http_status=404,
            ),
        ),
        (
            DatasetServiceError(404, "Dataset not found."),
            _expected_mcp_error(
                code="DATASET_NOT_FOUND",
                message="Dataset not found.",
                suggested_action=(
                    "Check that dataset_key is a private key, public key, or Rowset URL "
                    "for a dataset owned by this profile."
                ),
                http_status=404,
            ),
        ),
        (
            DatasetServiceError(404, "Project not found."),
            _expected_mcp_error(
                code="PROJECT_NOT_FOUND",
                message="Project not found.",
                suggested_action="Check the project key and try again.",
                http_status=404,
            ),
        ),
        (
            DatasetServiceError(404, "Column not found."),
            _expected_mcp_error(
                code="COLUMN_NOT_FOUND",
                message="Column not found.",
                suggested_action="Check the column name against the dataset headers and try again.",
                http_status=404,
            ),
        ),
        (
            DatasetServiceError(404, "Thing not found."),
            _expected_mcp_error(
                code="NOT_FOUND",
                message="Thing not found.",
                suggested_action="Check the identifier and try again.",
                http_status=404,
            ),
        ),
        (
            DatasetServiceError(400, "Invalid input."),
            _expected_mcp_error(
                code="VALIDATION_ERROR",
                message="Invalid input.",
                suggested_action=(
                    "Check the tool arguments against the dataset schema and try again."
                ),
                http_status=400,
            ),
        ),
        (
            DatasetServiceError(409, "Dataset is archived. Restore it before making changes."),
            _expected_mcp_error(
                code="DATASET_ARCHIVED",
                message="Dataset is archived. Restore it before making changes.",
                suggested_action="Restore the dataset before making changes.",
                http_status=409,
            ),
        ),
        (
            DatasetServiceError(409, "Row with index already exists."),
            _expected_mcp_error(
                code="CONFLICT",
                message="Row with index already exists.",
                suggested_action=(
                    "Refresh the dataset or row state, resolve the conflict, and try again."
                ),
                http_status=409,
            ),
        ),
        (
            DatasetServiceError(403, "Forbidden."),
            _expected_mcp_error(
                code="AUTHORIZATION_FAILED",
                message="Forbidden.",
                suggested_action="Check that the API key has access to this Rowset resource.",
                http_status=403,
            ),
        ),
        (
            DatasetServiceError(401, "Unauthorized."),
            _expected_mcp_error(
                code="AUTHORIZATION_FAILED",
                message="Unauthorized.",
                suggested_action="Check that the API key has access to this Rowset resource.",
                http_status=401,
            ),
        ),
        (
            DatasetServiceError(429, "Rate limited."),
            _expected_mcp_error(
                code="RATE_LIMITED",
                message="Rate limited.",
                retryable=True,
                suggested_action="Back off before retrying the request.",
                http_status=429,
            ),
        ),
        (
            DatasetServiceError(500, "Rowset exploded."),
            _expected_mcp_error(
                code="ROWSET_SERVICE_ERROR",
                message="Rowset exploded.",
                retryable=True,
                suggested_action="Retry the request. If it keeps failing, report the error.",
                http_status=500,
            ),
        ),
        (
            DatasetServiceError(418, "Unexpected teapot."),
            _expected_mcp_error(
                code="ROWSET_ERROR",
                message="Unexpected teapot.",
                suggested_action="Check the request and try again.",
                http_status=418,
            ),
        ),
    ],
)
def test_dataset_row_mcp_tools_return_service_errors(
    monkeypatch,
    service_error,
    expected_payload,
):
    async def run():
        monkeypatch.setattr(
            "apps.mcp_server.server._authenticate_profile",
            lambda: _profile(),
        )
        monkeypatch.setattr(
            "apps.mcp_server.server.get_profile_dataset_row",
            lambda profile, dataset_key, row_id: (_ for _ in ()).throw(service_error),
        )

        async with Client(mcp) as client:
            with pytest.raises(Exception) as exc_info:
                await client.call_tool("get_dataset_row", {"dataset_key": "ds", "row_id": 999})

        assert _extract_mcp_error_payload(exc_info.value) == expected_payload

    anyio.run(run)


@pytest.mark.parametrize(
    ("tool_name", "arguments", "serializer_path"),
    [
        ("get_user_info", {}, "apps.mcp_server.server.serialize_user_info"),
        ("get_all_datasets", {}, "apps.mcp_server.server.serialize_profile_datasets"),
        ("get_all_projects", {}, "apps.mcp_server.server.serialize_profile_projects"),
    ],
)
def test_metadata_mcp_tools_return_service_errors(
    monkeypatch,
    tool_name,
    arguments,
    serializer_path,
):
    expected_payload = _expected_mcp_error(
        code="VALIDATION_ERROR",
        message="Invalid metadata.",
        suggested_action="Check the tool arguments against the dataset schema and try again.",
        http_status=400,
    )

    def raise_service_error(*args, **kwargs):
        raise DatasetServiceError(400, "Invalid metadata.")

    async def run():
        monkeypatch.setattr(
            "apps.mcp_server.server._authenticate_profile",
            lambda: _profile(),
        )
        monkeypatch.setattr(serializer_path, raise_service_error)

        async with Client(mcp) as client:
            with pytest.raises(Exception) as exc_info:
                await client.call_tool(tool_name, arguments)

        assert _extract_mcp_error_payload(exc_info.value) == expected_payload

    anyio.run(run)


@pytest.mark.parametrize(
    ("message", "expected_code", "expected_message", "expected_suggested_action"),
    [
        (
            "Missing Rowset authorization. Configure the Rowset MCP server request with "
            "Authorization: Bearer <ROWSET_API_KEY>.",
            "AUTHORIZATION_MISSING",
            "Missing Rowset authorization. Configure the Rowset MCP server request with "
            "Authorization: Bearer <ROWSET_API_KEY>.",
            "Configure the MCP request with Authorization: Bearer <ROWSET_API_KEY>.",
        ),
        (
            "The Rowset agent API key for this token is no longer active.",
            "API_KEY_INACTIVE",
            "The Rowset agent API key for this token is no longer active.",
            "Create or select an active Rowset agent API key and retry.",
        ),
        (
            "Invalid Rowset API key",
            "AUTHENTICATION_FAILED",
            "Invalid Rowset API key.",
            (
                "Check that the MCP request sends Authorization: Bearer <ROWSET_API_KEY> "
                "with an active Rowset API key."
            ),
        ),
        (
            "A required field is missing",
            "AUTHENTICATION_FAILED",
            "A required field is missing.",
            (
                "Check that the MCP request sends Authorization: Bearer <ROWSET_API_KEY> "
                "with an active Rowset API key."
            ),
        ),
    ],
)
def test_get_user_info_mcp_tool_returns_structured_auth_errors(
    monkeypatch,
    message,
    expected_code,
    expected_message,
    expected_suggested_action,
):
    def reject():
        raise PermissionError(message)

    async def run():
        monkeypatch.setattr("apps.mcp_server.server._authenticate_profile", reject)

        async with Client(mcp) as client:
            with pytest.raises(Exception) as exc_info:
                await client.call_tool("get_user_info", {})

        assert _extract_mcp_error_payload(exc_info.value) == {
            "code": expected_code,
            "message": expected_message,
            "retryable": False,
            "suggested_action": expected_suggested_action,
            "details": {"http_status": 401},
        }

    anyio.run(run)
