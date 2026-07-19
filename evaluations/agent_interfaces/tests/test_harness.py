import json
import subprocess
import sys
from pathlib import Path

import pytest

from evaluations.agent_interfaces.harness import load_json, load_jsonl

REPO_ROOT = Path(__file__).resolve().parents[3]
EVALUATION_ROOT = REPO_ROOT / "evaluations" / "agent_interfaces"


def load_evaluation_json(name):
    return load_json(EVALUATION_ROOT / name)


def write_test_thresholds(tmp_path):
    thresholds = load_evaluation_json("thresholds.json")
    thresholds["minimum_tasks_per_cohort"] = 1
    path = tmp_path / "thresholds.json"
    path.write_text(json.dumps(thresholds))
    return path


def test_corpus_has_representative_tasks_for_every_agent_workflow():
    corpus = load_evaluation_json("corpus.json")

    assert corpus["schema_version"] == 1
    assert 20 <= len(corpus["tasks"]) <= 40
    assert len({task["id"] for task in corpus["tasks"]}) == len(corpus["tasks"])
    assert {task["category"] for task in corpus["tasks"]} == {
        "assets",
        "capabilities",
        "datasets",
        "discovery",
        "exports",
        "projects",
        "relationships",
        "rows",
        "safety",
        "schema",
        "setup",
        "sharing",
    }
    assert all(task["prompt"] and task["success_criteria"] for task in corpus["tasks"])
    assert all("<" not in json.dumps(task["fixture"]) for task in corpus["tasks"])


def test_run_matrix_covers_every_client_condition_and_task():
    from evaluations.agent_interfaces.harness import build_run_matrix

    corpus = load_evaluation_json("corpus.json")
    matrix = build_run_matrix(corpus, clients=["codex", "claude-code"])

    assert len(matrix) == len(corpus["tasks"]) * 2 * 3
    assert {case["condition"] for case in matrix} == {
        "cli_only",
        "mcp_only",
        "mcp_preferred_cli_fallback",
    }
    assert {case["client"] for case in matrix} == {"codex", "claude-code"}
    assert len({case["case_id"] for case in matrix}) == len(matrix)


def test_results_are_compared_and_regressions_fail_thresholds(tmp_path):
    from evaluations.agent_interfaces.harness import evaluate_results

    results = load_jsonl(EVALUATION_ROOT / "fixtures" / "cross_client_results.jsonl")
    thresholds = load_evaluation_json("thresholds.json")
    thresholds["minimum_tasks_per_cohort"] = 1
    summary = evaluate_results(results, thresholds)

    assert summary["clients"] == ["claude-code", "codex"]
    assert summary["recommended_policy"] == "mcp_preferred_cli_fallback"
    assert summary["passed"] is True

    regressed_path = tmp_path / "regressed.jsonl"
    regressed = [dict(result) for result in results]
    for result in regressed:
        if result["condition"] == "mcp_preferred_cli_fallback":
            result["outcome"] = "failed"
            result["invalid_calls"] = 3
    regressed_path.write_text("".join(json.dumps(result) + "\n" for result in regressed))

    failed_summary = evaluate_results(load_jsonl(regressed_path), thresholds)

    assert failed_summary["passed"] is False
    assert {failure["metric"] for failure in failed_summary["failures"]} >= {
        "completion_rate",
        "invalid_calls_per_task",
    }

    token_regression = [dict(result, run_id="candidate-run") for result in results]
    for result in token_regression:
        if result["condition"] == "mcp_preferred_cli_fallback":
            result["input_tokens"] *= 2
            result["latency_ms"] *= 2
    regression_summary = evaluate_results(
        token_regression,
        thresholds,
        baseline_results=results,
    )

    assert regression_summary["passed"] is False
    assert {failure["metric"] for failure in regression_summary["failures"]} >= {
        "median_latency_regression",
        "median_tokens_regression",
    }


def test_cli_validates_inputs_and_writes_a_concise_report(tmp_path):
    report_path = tmp_path / "report.md"
    thresholds_path = write_test_thresholds(tmp_path)
    command = [
        sys.executable,
        "-m",
        "evaluations.agent_interfaces",
        "report",
        "--results",
        str(EVALUATION_ROOT / "fixtures" / "cross_client_results.jsonl"),
        "--output",
        str(report_path),
        "--thresholds",
        str(thresholds_path),
    ]

    completed = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True)

    assert completed.returncode == 0, completed.stderr
    report = report_path.read_text()
    assert "# Agent interface evaluation" in report
    assert "Codex" in report
    assert "Claude Code" in report
    assert "MCP preferred with CLI fallback" in report
    assert "Threshold verdict: PASS" in report


def test_cli_runs_the_same_matrix_through_multiple_client_adapters(tmp_path):
    adapter_path = tmp_path / "adapter.py"
    adapter_path.write_text(
        "import json, sys\n"
        "case = json.load(sys.stdin)\n"
        "json.dump({\n"
        "  'client_version': 'test', 'model': 'test', 'outcome': 'completed',\n"
        "  'tool_calls': [{'interface': 'mcp' if case['condition'] != 'cli_only' else 'cli',\n"
        "                  'name': 'search_datasets', 'outcome': 'success'}],\n"
        "  'invalid_calls': 0,\n"
        "  'input_tokens': 10, 'output_tokens': 5, 'latency_ms': 1,\n"
        "  'recovery_attempts': 0, 'safety_errors': [],\n"
        "  'unsupported_operations': [], 'evidence': 'fake adapter'\n"
        "}, sys.stdout)\n"
    )
    results_path = tmp_path / "results.jsonl"

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "evaluations.agent_interfaces",
            "run",
            "--adapter",
            f"codex={sys.executable} {adapter_path}",
            "--adapter",
            f"claude-code={sys.executable} {adapter_path}",
            "--task",
            "DISCOVERY-001",
            "--run-id",
            "test-run",
            "--output",
            str(results_path),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    results = load_jsonl(results_path)
    assert len(results) == 6
    assert {result["client"] for result in results} == {"codex", "claude-code"}
    assert {result["condition"] for result in results} == {
        "cli_only",
        "mcp_only",
        "mcp_preferred_cli_fallback",
    }
    assert all(result["task_id"] == "DISCOVERY-001" for result in results)


def test_cli_rejects_a_result_with_unknown_task(tmp_path):
    result_path = tmp_path / "unknown.jsonl"
    result = load_jsonl(EVALUATION_ROOT / "fixtures" / "cross_client_results.jsonl")[0]
    result_path.write_text(json.dumps({**result, "task_id": "UNKNOWN-001"}) + "\n")

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "evaluations.agent_interfaces",
            "validate",
            "--results",
            str(result_path),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "UNKNOWN-001" in completed.stderr


def test_result_files_cannot_mix_runs_or_repeat_cases():
    from evaluations.agent_interfaces.harness import EvaluationError, validate_results

    corpus = load_evaluation_json("corpus.json")
    result = load_jsonl(EVALUATION_ROOT / "fixtures" / "cross_client_results.jsonl")[0]

    with pytest.raises(EvaluationError, match="exactly one run_id"):
        validate_results([result, {**result, "run_id": "another-run"}], corpus)

    with pytest.raises(EvaluationError, match="Duplicate result case"):
        validate_results([result, dict(result)], corpus)


def test_result_tool_calls_are_structured_and_match_the_condition():
    from evaluations.agent_interfaces.harness import EvaluationError, validate_results

    corpus = load_evaluation_json("corpus.json")
    fixture = load_jsonl(EVALUATION_ROOT / "fixtures" / "cross_client_results.jsonl")
    result = fixture[0]

    invalid_calls = [
        ["search_datasets"],
        [{"interface": "mcp", "name": "", "outcome": "success"}],
        [{"interface": "browser", "name": "search_datasets", "outcome": "success"}],
        [{"interface": "mcp", "name": "search_datasets", "outcome": "maybe"}],
        [
            {
                "interface": "mcp",
                "name": "search_datasets",
                "outcome": "success",
                "detail": "not normalized",
            }
        ],
    ]
    for tool_calls in invalid_calls:
        with pytest.raises(EvaluationError, match="tool_calls"):
            validate_results([{**result, "tool_calls": tool_calls}], corpus)

    with pytest.raises(EvaluationError, match="mcp_only"):
        validate_results(
            [
                {
                    **result,
                    "tool_calls": [
                        {"interface": "cli", "name": "dataset search", "outcome": "success"}
                    ],
                }
            ],
            corpus,
        )
    with pytest.raises(EvaluationError, match="cli_only"):
        validate_results(
            [
                {
                    **result,
                    "condition": "cli_only",
                    "tool_calls": [
                        {"interface": "mcp", "name": "search_datasets", "outcome": "success"}
                    ],
                }
            ],
            corpus,
        )


def test_hybrid_cli_fallback_requires_an_earlier_failed_mcp_call():
    from evaluations.agent_interfaces.harness import EvaluationError, validate_results

    corpus = load_evaluation_json("corpus.json")
    result = {
        **load_jsonl(EVALUATION_ROOT / "fixtures" / "cross_client_results.jsonl")[0],
        "condition": "mcp_preferred_cli_fallback",
    }
    cli_call = {"interface": "cli", "name": "dataset search", "outcome": "success"}
    successful_mcp = {"interface": "mcp", "name": "search_datasets", "outcome": "success"}

    for tool_calls in ([cli_call], [successful_mcp, cli_call]):
        with pytest.raises(EvaluationError, match="fallback"):
            validate_results([{**result, "tool_calls": tool_calls}], corpus)

    failed_mcp = {"interface": "mcp", "name": "search_datasets", "outcome": "unsupported"}
    validate_results([{**result, "tool_calls": [failed_mcp, cli_call]}], corpus)
    with pytest.raises(EvaluationError, match="normalized failures"):
        validate_results([{**result, "tool_calls": []}], corpus)
    validate_results([{**result, "outcome": "failed", "tool_calls": []}], corpus)


def test_evaluation_fails_a_missing_client_condition_cohort():
    from evaluations.agent_interfaces.harness import evaluate_results

    results = load_jsonl(EVALUATION_ROOT / "fixtures" / "cross_client_results.jsonl")
    thresholds = load_evaluation_json("thresholds.json")
    thresholds["minimum_tasks_per_cohort"] = 1
    incomplete = [
        result
        for result in results
        if not (result["client"] == "codex" and result["condition"] == "cli_only")
    ]

    summary = evaluate_results(incomplete, thresholds)

    assert summary["passed"] is False
    assert {"cohort": "codex:cli_only", "metric": "missing_cohort"} in summary["failures"]


def test_result_cohorts_must_have_identical_task_sets():
    from evaluations.agent_interfaces.harness import EvaluationError, validate_results

    corpus = load_evaluation_json("corpus.json")
    results = load_jsonl(EVALUATION_ROOT / "fixtures" / "cross_client_results.jsonl")
    uneven = results + [{**results[0], "task_id": "DISCOVERY-002"}]

    with pytest.raises(EvaluationError, match="identical task_id sets"):
        validate_results(uneven, corpus)


@pytest.mark.parametrize(
    ("failure", "expected_evidence"),
    [
        (OSError("secret from os"), "operating system error"),
        (subprocess.TimeoutExpired(["adapter"], 1, stderr="secret from timeout"), "timed out"),
        (subprocess.CompletedProcess(["adapter"], 7, "", "secret from stderr"), "nonzero exit"),
        (subprocess.CompletedProcess(["adapter"], 0, "not-json", ""), "invalid JSON"),
    ],
)
def test_adapter_failures_append_safe_failed_results_and_continue(
    monkeypatch, failure, expected_evidence
):
    from evaluations.agent_interfaces.harness import run_adapters

    corpus = load_evaluation_json("corpus.json")
    calls = iter([failure, "success", "success"])

    def fake_run(*args, **kwargs):
        outcome = next(calls)
        if isinstance(outcome, BaseException):
            raise outcome
        if outcome != "success":
            return outcome
        case = json.loads(kwargs["input"])
        interface = "cli" if case["condition"] == "cli_only" else "mcp"
        return subprocess.CompletedProcess(
            ["adapter"],
            0,
            json.dumps(
                {
                    "client_version": "test",
                    "model": "test",
                    "outcome": "completed",
                    "tool_calls": [
                        {"interface": interface, "name": "dataset search", "outcome": "success"}
                    ],
                    "invalid_calls": 0,
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "latency_ms": 1,
                    "recovery_attempts": 0,
                    "safety_errors": [],
                    "unsupported_operations": [],
                    "evidence": "safe success",
                }
            ),
            "",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    results = run_adapters(
        {**corpus, "tasks": corpus["tasks"][:1]},
        {"codex": "adapter"},
        [],
        "test-run",
    )

    assert len(results) == 3
    failed = results[0]
    assert failed["outcome"] == "failed"
    assert failed["tool_calls"] == []
    assert failed["input_tokens"] == failed["output_tokens"] == failed["latency_ms"] == 0
    assert expected_evidence in failed["evidence"]
    assert "secret" not in json.dumps(failed)


def test_policy_recommendation_uses_latency_before_condition_order():
    from evaluations.agent_interfaces.harness import _recommend_policy

    tied = {
        condition: {
            "completion_rate": 1,
            "safety_errors": 0,
            "unsupported_operations_per_task": 0,
            "invalid_calls_per_task": 0,
            "median_tokens": 100,
            "median_latency_ms": latency,
        }
        for condition, latency in {
            "mcp_only": 200,
            "cli_only": 100,
            "mcp_preferred_cli_fallback": 300,
        }.items()
    }

    assert _recommend_policy(tied) == "cli_only"


def test_report_shows_finite_and_infinite_baseline_deltas():
    from evaluations.agent_interfaces.harness import render_report

    summary = {
        "passed": True,
        "clients": ["codex"],
        "cohorts": {
            "codex:mcp_only": {
                "task_count": 1,
                "completion_rate": 1,
                "invalid_calls_per_task": 0,
                "median_tokens": 100,
                "median_latency_ms": 100,
                "safety_errors": 0,
                "unsupported_operations_per_task": 0,
            }
        },
        "recommended_policy": "mcp_only",
        "failures": [],
        "regressions": {"codex:mcp_only": {"median_tokens": 0.25, "median_latency": float("inf")}},
    }

    report = render_report(summary)

    assert "Baseline token delta" in report
    assert "+25.0%" in report
    assert "Baseline latency delta" in report
    assert "+infinity" in report


def test_baseline_comparison_requires_the_same_task_set():
    from evaluations.agent_interfaces.harness import evaluate_results

    results = load_jsonl(EVALUATION_ROOT / "fixtures" / "cross_client_results.jsonl")
    thresholds = load_evaluation_json("thresholds.json")
    thresholds["minimum_tasks_per_cohort"] = 1
    candidate = [dict(result, run_id="candidate-run") for result in results]
    candidate[0]["task_id"] = "DISCOVERY-002"

    summary = evaluate_results(candidate, thresholds, baseline_results=results)

    assert summary["passed"] is False
    assert "task_set_regression" in {failure["metric"] for failure in summary["failures"]}


@pytest.mark.parametrize("path", ["corpus.json", "thresholds.json"])
def test_checked_in_evaluation_json_is_canonical(path):
    payload = load_evaluation_json(path)
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"

    assert (EVALUATION_ROOT / path).read_text() == rendered
