import json
import math
import shlex
import statistics
import subprocess
from collections import defaultdict
from pathlib import Path

CONDITIONS = ("mcp_only", "cli_only", "mcp_preferred_cli_fallback")
OUTCOMES = {"completed", "failed", "unsupported", "blocked"}
REQUIRED_RESULT_FIELDS = {
    "schema_version",
    "run_id",
    "task_id",
    "client",
    "client_version",
    "model",
    "condition",
    "outcome",
    "tool_calls",
    "invalid_calls",
    "input_tokens",
    "output_tokens",
    "latency_ms",
    "recovery_attempts",
    "safety_errors",
    "unsupported_operations",
    "evidence",
}


class EvaluationError(ValueError):
    pass


def _failed_adapter_result(case, run_id, reason):
    return {
        "client": case["client"],
        "client_version": "unknown",
        "condition": case["condition"],
        "evidence": f"Adapter {reason}; no adapter output was retained.",
        "input_tokens": 0,
        "invalid_calls": 0,
        "latency_ms": 0,
        "model": "unknown",
        "outcome": "failed",
        "output_tokens": 0,
        "recovery_attempts": 0,
        "run_id": run_id,
        "safety_errors": [],
        "schema_version": 1,
        "task_id": case["task"]["id"],
        "tool_calls": [],
        "unsupported_operations": [],
    }


def load_json(path):
    return json.loads(Path(path).read_text())


def load_jsonl(path):
    records = []
    for line_number, line in enumerate(Path(path).read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as error:
            raise EvaluationError(f"Invalid JSON on line {line_number}: {error.msg}") from error
    if not records:
        raise EvaluationError("Results file contains no records.")
    return records


def build_run_matrix(corpus, clients):
    validate_corpus(corpus)
    if len(set(clients)) != len(clients) or not clients:
        raise EvaluationError("Clients must be a non-empty list of unique names.")
    return [
        {
            "case_id": f"{client}:{condition}:{task['id']}",
            "client": client,
            "condition": condition,
            "task": task,
        }
        for client in clients
        for condition in CONDITIONS
        for task in corpus["tasks"]
    ]


def run_adapters(corpus, adapters, task_ids, run_id, timeout_seconds=300):
    selected = {task["id"] for task in corpus["tasks"]}
    unknown = set(task_ids) - selected
    if unknown:
        raise EvaluationError(f"Unknown task ids: {', '.join(sorted(unknown))}")
    filtered_corpus = {
        **corpus,
        "tasks": [task for task in corpus["tasks"] if not task_ids or task["id"] in task_ids],
    }
    results = []
    for case in build_run_matrix(filtered_corpus, clients=list(adapters)):
        command = shlex.split(adapters[case["client"]])
        if not command:
            raise EvaluationError(f"Adapter command is empty for {case['client']}.")
        try:
            completed = subprocess.run(
                command,
                input=json.dumps(case),
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        except OSError:
            results.append(_failed_adapter_result(case, run_id, "operating system error"))
            continue
        except subprocess.TimeoutExpired:
            results.append(_failed_adapter_result(case, run_id, "timed out"))
            continue
        if completed.returncode:
            results.append(_failed_adapter_result(case, run_id, "returned a nonzero exit"))
            continue
        try:
            metrics = json.loads(completed.stdout)
        except json.JSONDecodeError:
            results.append(_failed_adapter_result(case, run_id, "returned invalid JSON"))
            continue
        result = {
            **metrics,
            "client": case["client"],
            "condition": case["condition"],
            "run_id": run_id,
            "schema_version": 1,
            "task_id": case["task"]["id"],
        }
        results.append(result)
    validate_results(results, corpus)
    return results


def validate_corpus(corpus):
    if corpus.get("schema_version") != 1:
        raise EvaluationError("Corpus schema_version must be 1.")
    tasks = corpus.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise EvaluationError("Corpus must contain tasks.")
    task_ids = [task.get("id") for task in tasks]
    if any(not task_id for task_id in task_ids) or len(set(task_ids)) != len(task_ids):
        raise EvaluationError("Corpus task ids must be present and unique.")
    for task in tasks:
        missing = {"category", "fixture", "prompt", "success_criteria"} - task.keys()
        if missing:
            raise EvaluationError(f"{task['id']} is missing: {', '.join(sorted(missing))}")


def _validate_result_fields(result, position, known_tasks):
    missing = REQUIRED_RESULT_FIELDS - result.keys()
    if missing:
        raise EvaluationError(f"Result {position} is missing: {', '.join(sorted(missing))}")
    allowed_values = (
        ("schema_version", {1}),
        ("task_id", known_tasks),
        ("condition", set(CONDITIONS)),
        ("outcome", OUTCOMES),
    )
    for field, allowed in allowed_values:
        if result[field] not in allowed:
            raise EvaluationError(f"Unknown {field.replace('_', ' ')}: {result[field]}")
    integer_fields = (
        "invalid_calls",
        "input_tokens",
        "output_tokens",
        "latency_ms",
        "recovery_attempts",
    )
    for field in integer_fields:
        if not isinstance(result[field], int) or result[field] < 0:
            raise EvaluationError(f"Result {position} field {field} must be a non-negative int.")
    for field in ("tool_calls", "safety_errors", "unsupported_operations"):
        if not isinstance(result[field], list):
            raise EvaluationError(f"Result {position} field {field} must be a list.")
    _validate_tool_calls(result, position)


def _validate_tool_call(call, position, call_position):
    required_fields = {"interface", "name", "outcome"}
    if not isinstance(call, dict) or set(call) != required_fields:
        raise EvaluationError(
            f"Result {position} tool_calls item {call_position} must contain only "
            "interface, name, and outcome."
        )
    if call["interface"] not in {"mcp", "cli"}:
        raise EvaluationError(
            f"Result {position} tool_calls item {call_position} has an unknown interface."
        )
    if not isinstance(call["name"], str) or not call["name"].strip():
        raise EvaluationError(
            f"Result {position} tool_calls item {call_position} name must be non-empty."
        )
    if call["outcome"] not in {"success", "error", "unsupported"}:
        raise EvaluationError(
            f"Result {position} tool_calls item {call_position} has an unknown outcome."
        )


def _validate_tool_calls(result, position):
    if not result["tool_calls"] and result["outcome"] != "failed":
        raise EvaluationError(
            f"Result {position} empty tool_calls are valid only for normalized failures."
        )

    for call_position, call in enumerate(result["tool_calls"], start=1):
        _validate_tool_call(call, position, call_position)

    condition = result["condition"]
    interfaces = {call["interface"] for call in result["tool_calls"]}
    if condition == "mcp_only" and interfaces - {"mcp"}:
        raise EvaluationError(f"Result {position} mcp_only tool_calls must use MCP only.")
    if condition == "cli_only" and interfaces - {"cli"}:
        raise EvaluationError(f"Result {position} cli_only tool_calls must use CLI only.")
    if condition == "mcp_preferred_cli_fallback":
        failed_mcp_seen = False
        for call in result["tool_calls"]:
            if call["interface"] == "cli" and not failed_mcp_seen:
                raise EvaluationError(
                    f"Result {position} hybrid CLI fallback requires an earlier MCP error or "
                    "unsupported outcome."
                )
            if call["interface"] == "mcp" and call["outcome"] in {"error", "unsupported"}:
                failed_mcp_seen = True


def validate_results(results, corpus):
    validate_corpus(corpus)
    known_tasks = {task["id"] for task in corpus["tasks"]}
    run_ids = {result.get("run_id") for result in results}
    if len(run_ids) != 1:
        raise EvaluationError("A results file must contain exactly one run_id.")
    seen_cases = set()
    cohort_task_ids = defaultdict(set)
    for position, result in enumerate(results, start=1):
        _validate_result_fields(result, position, known_tasks)
        case = (result["client"], result["condition"], result["task_id"])
        if case in seen_cases:
            raise EvaluationError(f"Duplicate result case: {':'.join(case)}")
        seen_cases.add(case)
        cohort_task_ids[(result["client"], result["condition"])].add(result["task_id"])
    task_sets = list(cohort_task_ids.values())
    if task_sets and any(task_ids != task_sets[0] for task_ids in task_sets[1:]):
        raise EvaluationError("All client-condition cohorts must have identical task_id sets.")


def _cohort_metrics(records):
    count = len(records)
    return {
        "completion_rate": sum(record["outcome"] == "completed" for record in records) / count,
        "invalid_calls_per_task": sum(record["invalid_calls"] for record in records) / count,
        "median_latency_ms": statistics.median(record["latency_ms"] for record in records),
        "median_tokens": statistics.median(
            record["input_tokens"] + record["output_tokens"] for record in records
        ),
        "recovery_attempts_per_task": sum(record["recovery_attempts"] for record in records)
        / count,
        "safety_errors": sum(len(record["safety_errors"]) for record in records),
        "task_count": count,
        "unsupported_operations_per_task": sum(
            len(record["unsupported_operations"]) for record in records
        )
        / count,
    }


def _regression(candidate, baseline):
    if baseline == 0:
        return 0 if candidate == 0 else float("inf")
    return (candidate - baseline) / baseline


def _absolute_failures(cohort, metrics, thresholds):
    checks = (
        ("task_count", metrics["task_count"] >= thresholds["minimum_tasks_per_cohort"]),
        ("completion_rate", metrics["completion_rate"] >= thresholds["minimum_completion_rate"]),
        (
            "invalid_calls_per_task",
            metrics["invalid_calls_per_task"] <= thresholds["maximum_invalid_calls_per_task"],
        ),
        ("safety_errors", metrics["safety_errors"] <= thresholds["maximum_safety_errors"]),
        (
            "unsupported_operations_per_task",
            metrics["unsupported_operations_per_task"]
            <= thresholds["maximum_unsupported_operations_per_task"],
        ),
    )
    return [{"cohort": cohort, "metric": metric} for metric, passed in checks if not passed]


def _baseline_regressions(cohort_metrics, results, baseline_results, thresholds):
    candidate_grouped = defaultdict(list)
    for result in results:
        candidate_grouped[(result["client"], result["condition"])].append(result)
    baseline_grouped = defaultdict(list)
    for result in baseline_results:
        baseline_grouped[(result["client"], result["condition"])].append(result)
    regressions = {}
    failures = []
    for cohort, metrics in cohort_metrics.items():
        cohort_label = ":".join(cohort)
        baseline_records = baseline_grouped.get(cohort)
        if not baseline_records:
            failures.append({"cohort": cohort_label, "metric": "missing_baseline_cohort"})
            continue
        candidate_task_ids = {result["task_id"] for result in candidate_grouped[cohort]}
        baseline_task_ids = {result["task_id"] for result in baseline_records}
        if candidate_task_ids != baseline_task_ids:
            failures.append({"cohort": cohort_label, "metric": "task_set_regression"})
        baseline_metrics = _cohort_metrics(baseline_records)
        regressions[cohort_label] = {
            "median_latency": _regression(
                metrics["median_latency_ms"], baseline_metrics["median_latency_ms"]
            ),
            "median_tokens": _regression(
                metrics["median_tokens"], baseline_metrics["median_tokens"]
            ),
        }
        checks = (
            (
                "median_latency_regression",
                regressions[cohort_label]["median_latency"]
                <= thresholds["maximum_latency_regression"],
            ),
            (
                "median_tokens_regression",
                regressions[cohort_label]["median_tokens"]
                <= thresholds["maximum_token_regression"],
            ),
        )
        failures.extend(
            {"cohort": cohort_label, "metric": metric} for metric, passed in checks if not passed
        )
    return regressions, failures


def _recommend_policy(condition_metrics):
    return min(
        condition_metrics,
        key=lambda condition: (
            -condition_metrics[condition]["completion_rate"],
            condition_metrics[condition]["safety_errors"],
            condition_metrics[condition]["unsupported_operations_per_task"],
            condition_metrics[condition]["invalid_calls_per_task"],
            condition_metrics[condition]["median_tokens"],
            condition_metrics[condition]["median_latency_ms"],
            CONDITIONS.index(condition),
        ),
    )


def _missing_cohort_failures(grouped, clients):
    expected_cohorts = {(client, condition) for client in clients for condition in CONDITIONS}
    return [
        {"cohort": ":".join(cohort), "metric": "missing_cohort"}
        for cohort in sorted(expected_cohorts - grouped.keys())
    ]


def evaluate_results(results, thresholds, baseline_results=None):
    grouped = defaultdict(list)
    for result in results:
        grouped[(result["client"], result["condition"])].append(result)

    clients = sorted({result["client"] for result in results})
    conditions = sorted({result["condition"] for result in results})
    cohort_metrics = {
        (client, condition): _cohort_metrics(records)
        for (client, condition), records in sorted(grouped.items())
    }
    failures = []
    if len(clients) < thresholds["minimum_clients"]:
        failures.append({"cohort": "all", "metric": "client_count"})
    if len(conditions) < thresholds["minimum_conditions"]:
        failures.append({"cohort": "all", "metric": "condition_count"})
    failures.extend(_missing_cohort_failures(grouped, clients))

    for cohort, metrics in cohort_metrics.items():
        failures.extend(_absolute_failures(":".join(cohort), metrics, thresholds))

    regressions = {}
    if baseline_results:
        regressions, regression_failures = _baseline_regressions(
            cohort_metrics, results, baseline_results, thresholds
        )
        failures.extend(regression_failures)

    condition_metrics = {}
    for condition in CONDITIONS:
        records = [result for result in results if result["condition"] == condition]
        if records:
            condition_metrics[condition] = _cohort_metrics(records)
    recommended_policy = _recommend_policy(condition_metrics)
    cohorts = {":".join(cohort): metrics for cohort, metrics in cohort_metrics.items()}
    return {
        "clients": clients,
        "cohorts": cohorts,
        "condition_metrics": condition_metrics,
        "failures": failures,
        "passed": not failures,
        "recommended_policy": recommended_policy,
        "regressions": regressions,
    }


def render_report(summary):
    labels = {
        "claude-code": "Claude Code",
        "codex": "Codex",
        "cli_only": "CLI only",
        "mcp_only": "MCP only",
        "mcp_preferred_cli_fallback": "MCP preferred with CLI fallback",
    }
    lines = [
        "# Agent interface evaluation",
        "",
        f"Threshold verdict: {'PASS' if summary['passed'] else 'FAIL'}",
        "",
        "Clients: " + ", ".join(labels.get(client, client) for client in summary["clients"]),
        "",
        "| Client and condition | Tasks | Completion | Invalid calls/task | "
        "Median tokens | Median latency | Safety errors | Unsupported/task |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for cohort, metrics in summary["cohorts"].items():
        client, condition = cohort.split(":", 1)
        lines.append(
            "| "
            + f"{labels.get(client, client)} / {labels.get(condition, condition)} | "
            + f"{metrics['task_count']} | {metrics['completion_rate']:.0%} | "
            + f"{metrics['invalid_calls_per_task']:.2f} | {metrics['median_tokens']:.0f} | "
            + f"{metrics['median_latency_ms']:.0f} ms | {metrics['safety_errors']} | "
            + f"{metrics['unsupported_operations_per_task']:.2f} |"
        )
    if summary["regressions"]:
        lines.extend(
            [
                "",
                "## Baseline deltas",
                "",
                "| Client and condition | Baseline token delta | Baseline latency delta |",
                "| --- | ---: | ---: |",
            ]
        )
        for cohort, regressions in summary["regressions"].items():
            client, condition = cohort.split(":", 1)
            lines.append(
                "| "
                + f"{labels.get(client, client)} / {labels.get(condition, condition)} | "
                + f"{_format_delta(regressions['median_tokens'])} | "
                + f"{_format_delta(regressions['median_latency'])} |"
            )
    lines.extend(
        [
            "",
            "## Default interface policy",
            "",
            labels.get(summary["recommended_policy"], summary["recommended_policy"]),
            "",
        ]
    )
    if summary["failures"]:
        lines.extend(
            [
                "## Threshold failures",
                "",
                *(f"- {failure['cohort']}: {failure['metric']}" for failure in summary["failures"]),
                "",
            ]
        )
    return "\n".join(lines)


def _format_delta(value):
    if math.isinf(value):
        return "+infinity" if value > 0 else "-infinity"
    return f"{value:+.1%}"
