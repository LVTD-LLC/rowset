import importlib.util
import json
import sys
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError, URLError

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "agent-eval-seed.py"
SPEC = importlib.util.spec_from_file_location("agent_eval_seed_script", SCRIPT_PATH)
assert SPEC is not None
agent_eval_seed = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = agent_eval_seed
SPEC.loader.exec_module(agent_eval_seed)


class FakeResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


def test_rowset_eval_result_schema_payload_defines_private_indexed_dataset():
    payload = agent_eval_seed.rowset_eval_result_schema_payload(
        project_key="project-key",
        section_key="section-key",
    )

    assert payload["name"] == "Rowset Agent Eval Results"
    assert payload["index_column"] == "run_id"
    assert payload["headers"] == agent_eval_seed.ROWSET_EVAL_RESULT_HEADERS
    assert payload["project_key"] == "project-key"
    assert payload["section_key"] == "section-key"
    assert payload["column_types"]["result"]["choices"] == [
        "dry_run",
        "pending",
        "pass",
        "fail",
        "blocked",
    ]
    assert "Do not store API keys" in payload["instructions"]
    assert payload["metadata"]["dataset_kind"] == "agent_eval_results"


def test_rowset_eval_result_row_flattens_artifact_for_dataset_write():
    artifact = {
        "run_id": "run-1",
        "seed_id": "EVAL-001",
        "seed_title": "Choice Column Canonicalization",
        "created_at": "2026-07-01T00:00:00Z",
        "status": "pass",
        "agent": "Codex",
        "model": "gpt-5",
        "base_sha": "base",
        "head_sha": "head",
        "changed_files": ["apps/api/services.py"],
        "observed_checks": ["make test -- apps/api -q"],
        "checks_passed": ["make test -- apps/api -q"],
        "checks_failed": ["make lint-python"],
        "duration_seconds": "12.5",
        "cost_usd": "0.42",
        "failure_mode": "lint",
        "artifact_url": "https://rowset.example/artifacts/run-1",
        "follow_up_notes": "Review lint output.",
    }

    row = agent_eval_seed.rowset_eval_result_row(artifact)

    assert row["run_id"] == "run-1"
    assert row["seed_id"] == "EVAL-001"
    assert row["result"] == "pass"
    assert row["checks_passed"] == '["make test -- apps/api -q"]'
    assert row["checks_failed"] == '["make lint-python"]'
    assert row["changed_files"] == '["apps/api/services.py"]'
    assert row["duration_seconds"] == "12.5"
    assert row["cost_usd"] == "0.42"
    assert row["artifact_url"] == "https://rowset.example/artifacts/run-1"


def test_write_rowset_eval_result_row_patches_then_creates_when_missing(monkeypatch):
    requests = []
    row = {"run_id": "run-1", "seed_id": "EVAL-001"}

    def fake_urlopen(request, timeout):
        requests.append(request)
        if len(requests) == 1:
            raise HTTPError(
                request.full_url,
                404,
                "Not Found",
                {},
                BytesIO(b'{"detail": "Dataset row not found."}'),
            )
        return FakeResponse({"status": "success", "row": {"id": 123}})

    monkeypatch.setattr(agent_eval_seed.request, "urlopen", fake_urlopen)

    response = agent_eval_seed.write_rowset_eval_result_row(
        api_base="https://rowset.example/api/",
        api_key="secret-token",
        dataset_key="dataset-key",
        row=row,
    )

    assert response == {"status": "success", "row": {"id": 123}}
    assert len(requests) == 2
    assert requests[0].get_method() == "PATCH"
    assert (
        requests[0].full_url
        == "https://rowset.example/api/datasets/dataset-key/rows/by-index?index_value=run-1"
    )
    assert requests[0].get_header("Authorization") == "Bearer secret-token"
    assert requests[1].get_method() == "POST"
    assert requests[1].full_url == "https://rowset.example/api/datasets/dataset-key/rows"
    assert json.loads(requests[1].data) == {"data": row}


def test_write_rowset_eval_result_row_reports_connection_failures_cleanly(monkeypatch):
    def fake_urlopen(request, timeout):
        raise URLError("connection refused")

    monkeypatch.setattr(agent_eval_seed.request, "urlopen", fake_urlopen)

    try:
        agent_eval_seed.write_rowset_eval_result_row(
            api_base="https://rowset.example/api/",
            api_key="secret-token",
            dataset_key="dataset-key",
            row={"run_id": "run-1", "seed_id": "EVAL-001"},
        )
    except agent_eval_seed.RowsetApiError as exc:
        assert exc.status_code == 0
        assert "Unable to reach Rowset API: connection refused" in str(exc)
    else:
        raise AssertionError("Expected RowsetApiError")
