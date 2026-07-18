import pytest

from apps.core import capabilities
from apps.core.capabilities import (
    CapabilitySelectionError,
    RowsetCapabilityTopic,
    RowsetUseCase,
    rowset_capabilities_payload,
)


def test_use_case_feature_references_match_registered_capability_ids():
    payload = rowset_capabilities_payload(full=True, include_use_cases=True)
    capability_ids = {capability["id"] for capability in payload["capabilities"]}

    for use_case in payload["use_cases"]:
        assert set(use_case["rowset_features"]) <= capability_ids


def test_capabilities_payload_includes_core_rowset_surfaces():
    payload = rowset_capabilities_payload(full=True)

    assert {capability["id"] for capability in payload["capabilities"]} >= {"rows"}


def test_capabilities_payload_rejects_unknown_use_case_feature_references(monkeypatch):
    monkeypatch.setattr(
        capabilities,
        "ROWSET_USE_CASES",
        capabilities.ROWSET_USE_CASES
        + (
            RowsetUseCase(
                id="invalid_reference",
                title="Invalid reference",
                summary="Invalid registry fixture.",
                starter_shape=("Fixture only.",),
                rowset_features=("missing_capability",),
            ),
        ),
    )

    with pytest.raises(
        ValueError,
        match="invalid_reference: missing_capability",
    ):
        rowset_capabilities_payload(full=True, include_use_cases=True)


def test_capabilities_payload_rejects_duplicate_capability_ids(monkeypatch):
    monkeypatch.setattr(
        capabilities,
        "ROWSET_CAPABILITIES",
        capabilities.ROWSET_CAPABILITIES + (capabilities.ROWSET_CAPABILITIES[0],),
    )

    with pytest.raises(ValueError, match="duplicate IDs"):
        rowset_capabilities_payload(full=True)


def test_capabilities_payload_defaults_to_compact_topic_index():
    payload = rowset_capabilities_payload()

    assert payload["mode"] == "summary"
    assert "capabilities" not in payload
    assert "interfaces" not in payload
    assert "recommended_startup" not in payload
    assert "use_cases" not in payload
    assert {topic["id"] for topic in payload["available_topics"]} >= {
        "rows",
        "relationships",
        "schema",
        "assets",
        "previews",
        "setup",
    }
    assert len(str(payload)) < 3_000


def test_capabilities_payload_returns_only_requested_topics():
    payload = rowset_capabilities_payload(topics=["rows", "schema"])

    assert payload["mode"] == "topics"
    assert payload["requested_topics"] == ["rows", "schema"]
    assert {capability["id"] for capability in payload["capabilities"]} == {
        "rows",
        "dataset_context",
        "schema_mutations",
    }
    assert "interfaces" not in payload
    assert "recommended_startup" not in payload
    assert "use_cases" not in payload


def test_topic_payload_includes_only_fully_supported_use_cases():
    payload = rowset_capabilities_payload(
        topics=["schema", "rows", "projects"],
        include_use_cases=True,
    )

    assert [use_case["id"] for use_case in payload["use_cases"]] == ["task_board"]


def test_capabilities_payload_setup_topic_includes_setup_details():
    payload = rowset_capabilities_payload(topics=["setup"])

    assert {interface["id"] for interface in payload["interfaces"]} == {
        "mcp",
        "cli",
        "rest",
    }
    assert payload["recommended_startup"]


def test_capabilities_payload_makes_use_cases_opt_in():
    without_use_cases = rowset_capabilities_payload()
    with_use_cases = rowset_capabilities_payload(include_use_cases=True)

    assert "use_cases" not in without_use_cases
    assert {use_case["id"] for use_case in with_use_cases["use_cases"]} >= {
        "task_board",
        "bug_tracker",
    }


def test_capabilities_payload_rejects_unknown_topics():
    with pytest.raises(CapabilitySelectionError, match="Unknown capability topic: unknown"):
        rowset_capabilities_payload(topics=["unknown"])


def test_capabilities_payload_rejects_topics_with_full_mode():
    with pytest.raises(CapabilitySelectionError, match="Choose topics or full mode"):
        rowset_capabilities_payload(topics=["rows"], full=True)


def test_capabilities_payload_rejects_topic_references_missing_from_registry(monkeypatch):
    monkeypatch.setattr(
        capabilities,
        "ROWSET_CAPABILITY_TOPICS",
        capabilities.ROWSET_CAPABILITY_TOPICS
        + (
            RowsetCapabilityTopic(
                id="invalid",
                title="Invalid registry fixture",
                capability_ids=("missing_capability",),
            ),
        ),
    )

    with pytest.raises(ValueError, match=r"unknown=\['missing_capability'\]"):
        rowset_capabilities_payload()


def test_capabilities_payload_rejects_capabilities_missing_from_topics(monkeypatch):
    monkeypatch.setattr(
        capabilities,
        "ROWSET_CAPABILITY_TOPICS",
        tuple(topic for topic in capabilities.ROWSET_CAPABILITY_TOPICS if topic.id != "rows"),
    )

    with pytest.raises(ValueError, match=r"missing=\['rows'\]"):
        rowset_capabilities_payload()
