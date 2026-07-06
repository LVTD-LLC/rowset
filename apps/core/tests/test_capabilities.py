from types import SimpleNamespace

import pytest

from apps.core import capabilities
from apps.core.capabilities import RowsetUseCase, rowset_capabilities_payload


def test_use_case_feature_references_match_registered_capability_ids():
    payload = rowset_capabilities_payload()
    capability_ids = {capability["id"] for capability in payload["capabilities"]}

    for use_case in payload["use_cases"]:
        assert set(use_case["rowset_features"]) <= capability_ids


def test_capabilities_payload_hides_staff_only_plugins_by_default():
    payload = rowset_capabilities_payload()

    assert {capability["id"] for capability in payload["capabilities"]} >= {"rows"}
    assert "dataset_plugins" not in {capability["id"] for capability in payload["capabilities"]}
    assert "flashcards" not in {use_case["id"] for use_case in payload["use_cases"]}


def test_capabilities_payload_includes_plugins_for_staff_profiles():
    profile = SimpleNamespace(user=SimpleNamespace(is_staff=True))

    payload = rowset_capabilities_payload(profile)

    assert "dataset_plugins" in {capability["id"] for capability in payload["capabilities"]}
    assert "flashcards" in {use_case["id"] for use_case in payload["use_cases"]}


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
        rowset_capabilities_payload()


def test_capabilities_payload_rejects_duplicate_capability_ids(monkeypatch):
    monkeypatch.setattr(
        capabilities,
        "ROWSET_CAPABILITIES",
        capabilities.ROWSET_CAPABILITIES + (capabilities.ROWSET_CAPABILITIES[0],),
    )

    with pytest.raises(ValueError, match="duplicate IDs"):
        rowset_capabilities_payload()
