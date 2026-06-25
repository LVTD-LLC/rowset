from apps.core.capabilities import rowset_capabilities_payload


def test_use_case_feature_references_match_registered_capability_ids():
    payload = rowset_capabilities_payload()
    capability_ids = {capability["id"] for capability in payload["capabilities"]}

    for use_case in payload["use_cases"]:
        assert set(use_case["rowset_features"]) <= capability_ids
