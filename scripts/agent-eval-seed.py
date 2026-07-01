#!/usr/bin/env python3
"""Create structured run artifacts from Rowset agent eval seeds."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib import parse, request
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parents[1]
SEED_DOC = Path("docs/agent-evals/seed-tasks.md")
DEFAULT_RUNS_DIR = Path("docs/agent-evals/runs")
HEADING_RE = re.compile(r"^### (?P<seed_id>EVAL-\d+): (?P<title>.+)$")
FIELD_RE = re.compile(r"^- \*\*(?P<label>[^*]+):\*\*\s*(?P<value>.*)$")
CODE_SPAN_RE = re.compile(r"`([^`]+)`")
ROWSET_RESULT_CHOICES = ["dry_run", "pending", "pass", "fail", "blocked"]
ROWSET_EVAL_RESULT_HEADERS = [
    "run_id",
    "seed_id",
    "seed_title",
    "created_at",
    "agent",
    "model",
    "base_sha",
    "head_sha",
    "result",
    "checks_passed",
    "checks_failed",
    "observed_checks",
    "changed_files",
    "duration_seconds",
    "cost_usd",
    "failure_mode",
    "notes",
    "artifact_url",
]
ROWSET_EVAL_RESULT_INSTRUCTIONS = "\n".join(
    (
        "Use this dataset for Rowset agent-eval run summaries created by the eval harness.",
        "Keep run_id stable and unique; update the existing row when refreshing a run.",
        "Store check lists and changed_files as JSON arrays in their text cells.",
        "Do not store API keys, OAuth tokens, raw secrets, private dataset contents, or full logs.",
        "Use artifact_url only for a private artifact location or leave it blank.",
        "Use notes for concise follow-up context, not raw command output or private data.",
    )
)
ROWSET_EVAL_RESULT_COLUMN_TYPES = {
    "run_id": {"type": "text", "description": "Stable run id. Dataset index."},
    "seed_id": {"type": "text", "description": "Eval seed id, such as EVAL-001."},
    "seed_title": "text",
    "created_at": "datetime",
    "agent": "text",
    "model": "text",
    "base_sha": "text",
    "head_sha": "text",
    "result": {
        "type": "choice",
        "choices": ROWSET_RESULT_CHOICES,
        "description": "Run outcome status.",
    },
    "checks_passed": {"type": "text", "description": "JSON array of checks that passed."},
    "checks_failed": {"type": "text", "description": "JSON array of checks that failed."},
    "observed_checks": {"type": "text", "description": "JSON array of checks observed."},
    "changed_files": {"type": "text", "description": "JSON array of changed repo files."},
    "duration_seconds": "number",
    "cost_usd": "currency",
    "failure_mode": "text",
    "notes": "text",
    "artifact_url": "url",
}


class RowsetApiError(RuntimeError):
    def __init__(self, status_code: int, method: str, path: str, detail: str):
        self.status_code = status_code
        self.method = method
        self.path = path
        self.detail = detail
        super().__init__(f"Rowset API request failed ({status_code}) {method} {path}: {detail}")


@dataclass(frozen=True)
class Seed:
    seed_id: str
    title: str
    prompt: str
    expected_files: list[str]
    fail_to_pass_check: str
    pass_to_pass_checks: list[str]
    trace_notes: str


def _compact_markdown_lines(lines: list[str]) -> str:
    text = " ".join(line.strip() for line in lines if line.strip())
    return re.sub(r"\s+", " ", text).strip()


def _extract_code_spans(text: str) -> list[str]:
    return [match.group(1) for match in CODE_SPAN_RE.finditer(text)]


def _parse_fields(section_lines: list[str]) -> dict[str, str]:
    fields: dict[str, list[str]] = {}
    current_label: str | None = None

    for line in section_lines:
        if line.startswith("### "):
            continue
        match = FIELD_RE.match(line)
        if match:
            current_label = match.group("label").strip()
            fields[current_label] = [match.group("value")]
            continue
        if current_label and (line.startswith("  ") or not line.startswith("- ")):
            fields[current_label].append(line)

    return {label: _compact_markdown_lines(lines) for label, lines in fields.items()}


def parse_seeds(path: Path) -> dict[str, Seed]:
    text = path.read_text()
    seeds: dict[str, Seed] = {}
    current_header: tuple[str, str] | None = None
    current_lines: list[str] = []

    def flush_current() -> None:
        if current_header is None:
            return
        seed_id, title = current_header
        fields = _parse_fields(current_lines)
        expected_files_text = fields.get("Expected files", "")
        pass_to_pass_text = fields.get("Pass-to-pass checks", "")
        seeds[seed_id] = Seed(
            seed_id=seed_id,
            title=title,
            prompt=fields.get("Prompt", ""),
            expected_files=_extract_code_spans(expected_files_text),
            fail_to_pass_check=fields.get("Fail-to-pass check", ""),
            pass_to_pass_checks=_extract_code_spans(pass_to_pass_text),
            trace_notes=fields.get("Trace notes", ""),
        )

    for line in text.splitlines():
        match = HEADING_RE.match(line)
        if match:
            flush_current()
            current_header = (match.group("seed_id"), match.group("title"))
            current_lines = [line]
        elif current_header:
            current_lines.append(line)

    flush_current()
    return seeds


def _git_output(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode != 0:
        return "unknown"
    return result.stdout.strip() or "unknown"


def _default_run_id(seed: Seed, now: datetime) -> str:
    timestamp = now.strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{seed.seed_id.lower()}"


def _existing_result(run_dir: Path) -> dict[str, object] | None:
    path = run_dir / "result.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _preserved_base_sha(existing_result: dict[str, object] | None) -> str | None:
    if not existing_result:
        return None
    base_sha = existing_result.get("base_sha")
    return str(base_sha).strip() if base_sha else None


def _json_cell(value: object) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value)
    return str(value)


def rowset_eval_result_schema_payload(
    *,
    name: str = "Rowset Agent Eval Results",
    project_key: str | None = None,
    section_key: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": name,
        "description": (
            "Structured Rowset agent-eval run results for comparing agent behavior over time."
        ),
        "instructions": ROWSET_EVAL_RESULT_INSTRUCTIONS,
        "metadata": {
            "dataset_kind": "agent_eval_results",
            "created_by": "scripts/agent-eval-seed.py",
            "artifact_schema_version": 2,
            "privacy": "Store summaries only; keep secrets and private data out of rows.",
        },
        "headers": ROWSET_EVAL_RESULT_HEADERS,
        "index_column": "run_id",
        "column_types": ROWSET_EVAL_RESULT_COLUMN_TYPES,
    }
    if project_key:
        payload["project_key"] = project_key
    if section_key:
        payload["section_key"] = section_key
    return payload


def rowset_eval_result_row(artifact: dict[str, object]) -> dict[str, str]:
    return {
        "run_id": _json_cell(artifact.get("run_id")),
        "seed_id": _json_cell(artifact.get("seed_id")),
        "seed_title": _json_cell(artifact.get("seed_title")),
        "created_at": _json_cell(artifact.get("created_at")),
        "agent": _json_cell(artifact.get("agent")),
        "model": _json_cell(artifact.get("model")),
        "base_sha": _json_cell(artifact.get("base_sha")),
        "head_sha": _json_cell(artifact.get("head_sha")),
        "result": _json_cell(artifact.get("result_status") or artifact.get("status")),
        "checks_passed": _json_cell(artifact.get("checks_passed") or []),
        "checks_failed": _json_cell(artifact.get("checks_failed") or []),
        "observed_checks": _json_cell(artifact.get("observed_checks") or []),
        "changed_files": _json_cell(artifact.get("changed_files") or []),
        "duration_seconds": _json_cell(artifact.get("duration_seconds")),
        "cost_usd": _json_cell(artifact.get("cost_usd")),
        "failure_mode": _json_cell(artifact.get("failure_mode")),
        "notes": _json_cell(artifact.get("follow_up_notes")),
        "artifact_url": _json_cell(artifact.get("artifact_url")),
    }


def _normalized_api_base(api_base: str) -> str:
    normalized = api_base.strip()
    if not normalized:
        raise ValueError("Rowset REST API base is required for Rowset writeback.")
    return normalized.rstrip("/") + "/"


def _rowset_api_request(
    *,
    api_base: str,
    api_key: str,
    method: str,
    path: str,
    payload: dict[str, object],
) -> dict[str, object]:
    url = parse.urljoin(_normalized_api_base(api_base), path)
    body = json.dumps(payload).encode()
    api_request = request.Request(
        url,
        data=body,
        method=method,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with request.urlopen(api_request, timeout=30) as response:
            response_body = response.read().decode()
    except HTTPError as exc:
        detail = exc.read().decode(errors="replace").strip()
        raise RowsetApiError(exc.code, method, path, detail) from exc
    except URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise RowsetApiError(0, method, path, f"Unable to reach Rowset API: {reason}") from exc
    return json.loads(response_body or "{}")


def write_rowset_eval_result_row(
    *,
    api_base: str,
    api_key: str,
    dataset_key: str,
    row: dict[str, str],
) -> dict[str, object]:
    run_id = row.get("run_id", "").strip()
    if not run_id:
        raise ValueError("Rowset eval result rows require a non-blank run_id.")

    index_query = parse.urlencode({"index_value": run_id})
    by_index_path = f"datasets/{parse.quote(dataset_key)}/rows/by-index?{index_query}"
    row_path = f"datasets/{parse.quote(dataset_key)}/rows"
    try:
        return _rowset_api_request(
            api_base=api_base,
            api_key=api_key,
            method="PATCH",
            path=by_index_path,
            payload={"data": row},
        )
    except RowsetApiError as exc:
        if exc.status_code != 404:
            raise

    return _rowset_api_request(
        api_base=api_base,
        api_key=api_key,
        method="POST",
        path=row_path,
        payload={"data": row},
    )


def _rowset_api_base_from_args(args: argparse.Namespace) -> str:
    return (
        args.rowset_api_base
        or os.environ.get("ROWSET_REST_API_BASE", "")
        or os.environ.get("ROWSET_API_BASE", "")
    )


def _rowset_api_key_from_env(env_name: str) -> str:
    api_key = os.environ.get(env_name, "").strip()
    if not api_key:
        raise ValueError(f"{env_name} must contain a Rowset API key for Rowset writeback.")
    return api_key


def _build_artifact(
    args: argparse.Namespace,
    seed: Seed,
    root: Path,
    *,
    run_id: str,
    created_at: datetime,
    existing_result: dict[str, object] | None,
) -> dict[str, object]:
    current_head_sha = _git_output(root, "rev-parse", "HEAD")
    base_sha = args.base_sha or _preserved_base_sha(existing_result) or current_head_sha
    head_sha = args.head_sha or current_head_sha
    changed_files = args.changed_file or ["TODO: record changed files after the run"]
    follow_up_notes = args.note or "Dry-run artifact created; no agent execution invoked."

    return {
        "artifact_schema_version": 2,
        "run_id": run_id,
        "seed_id": seed.seed_id,
        "seed_title": seed.title,
        "created_at": created_at.isoformat().replace("+00:00", "Z"),
        "status": args.status,
        "agent": args.agent,
        "model": args.model,
        "base_sha": base_sha,
        "head_sha": head_sha,
        "changed_files": changed_files,
        "seed": {
            "prompt": seed.prompt,
            "expected_files": seed.expected_files,
            "fail_to_pass_check": seed.fail_to_pass_check,
            "pass_to_pass_checks": seed.pass_to_pass_checks,
            "trace_notes": seed.trace_notes,
        },
        "required_checks": seed.pass_to_pass_checks,
        "observed_checks": args.observed_check,
        "checks_passed": args.check_passed,
        "checks_failed": args.check_failed,
        "duration_seconds": args.duration_seconds,
        "cost_usd": args.cost_usd,
        "failure_mode": args.failure_mode,
        "artifact_url": args.artifact_url,
        "result_status": args.status,
        "follow_up_notes": follow_up_notes,
    }


def _markdown_for_artifact(artifact: dict[str, object]) -> str:
    seed = artifact["seed"]
    assert isinstance(seed, dict)
    required_checks = artifact["required_checks"]
    observed_checks = artifact["observed_checks"]
    checks_passed = artifact["checks_passed"]
    checks_failed = artifact["checks_failed"]
    changed_files = artifact["changed_files"]

    def bullet_list(values: object, fallback: str) -> str:
        if not values:
            return f"- {fallback}"
        assert isinstance(values, list)
        return "\n".join(f"- {value}" for value in values)

    return (
        f"# {artifact['seed_id']} Run {artifact['run_id']}\n\n"
        f"- Status: {artifact['status']}\n"
        f"- Agent: {artifact['agent']}\n"
        f"- Model: {artifact['model']}\n"
        f"- Base SHA: `{artifact['base_sha']}`\n"
        f"- Head SHA: `{artifact['head_sha']}`\n\n"
        "## Prompt\n\n"
        f"{seed['prompt']}\n\n"
        "## Changed Files\n\n"
        f"{bullet_list(changed_files, 'TODO: record changed files after the run')}\n\n"
        "## Required Checks\n\n"
        f"{bullet_list(required_checks, 'No required checks parsed')}\n\n"
        "## Observed Checks\n\n"
        f"{bullet_list(observed_checks, 'No observed checks recorded yet')}\n\n"
        "## Checks Passed\n\n"
        f"{bullet_list(checks_passed, 'No passed checks recorded yet')}\n\n"
        "## Checks Failed\n\n"
        f"{bullet_list(checks_failed, 'No failed checks recorded')}\n\n"
        "## Follow-Up Notes\n\n"
        f"{artifact['follow_up_notes']}\n"
    )


def create_run(args: argparse.Namespace, seeds: dict[str, Seed]) -> int:
    seed_id = args.seed_id.upper()
    if seed_id not in seeds:
        print(f"Unknown seed id `{args.seed_id}`.", file=sys.stderr)
        return 1

    root = args.root.resolve()
    seed = seeds[seed_id]
    now = datetime.now(UTC)
    run_id = args.run_id or _default_run_id(seed, now)
    runs_dir = (root / args.runs_dir).resolve()
    run_dir = runs_dir / run_id
    if run_dir.exists() and not args.force:
        print(f"Run directory already exists: {run_dir}", file=sys.stderr)
        return 1

    artifact = _build_artifact(
        args,
        seed,
        root,
        run_id=run_id,
        created_at=now,
        existing_result=_existing_result(run_dir),
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "result.json").write_text(json.dumps(artifact, indent=2) + "\n")
    (run_dir / "result.md").write_text(_markdown_for_artifact(artifact))
    try:
        display_path = run_dir.relative_to(root)
    except ValueError:
        display_path = run_dir
    print(f"Created eval run artifact: {display_path}")
    if args.rowset_dataset_key:
        try:
            response = write_rowset_eval_result_row(
                api_base=_rowset_api_base_from_args(args),
                api_key=_rowset_api_key_from_env(args.rowset_api_key_env),
                dataset_key=args.rowset_dataset_key,
                row=rowset_eval_result_row(artifact),
            )
        except (RowsetApiError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        row = response.get("row")
        row_id = row.get("id") if isinstance(row, dict) else "unknown"
        print(f"Recorded eval run in Rowset dataset {args.rowset_dataset_key} row {row_id}.")
    return 0


def list_seeds(seeds: dict[str, Seed]) -> int:
    for seed in seeds.values():
        print(f"{seed.seed_id}\t{seed.title}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("seed_id", nargs="?", help="Seed id to instantiate, such as EVAL-001.")
    parser.add_argument("--list", action="store_true", help="List available seeds and exit.")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--seed-doc", type=Path, default=SEED_DOC)
    parser.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS_DIR)
    parser.add_argument("--run-id", help="Override the generated run id.")
    parser.add_argument(
        "--base-sha",
        help=(
            "Base commit for the run. Defaults to the existing artifact base_sha when "
            "overwriting, otherwise current HEAD."
        ),
    )
    parser.add_argument(
        "--head-sha",
        help="Head commit for the run. Defaults to current HEAD.",
    )
    parser.add_argument(
        "--status",
        default="dry_run",
        choices=["dry_run", "pending", "pass", "fail", "blocked"],
    )
    parser.add_argument("--agent", default="manual-or-agent")
    parser.add_argument("--model", default="unknown")
    parser.add_argument("--changed-file", action="append", default=[])
    parser.add_argument("--observed-check", action="append", default=[])
    parser.add_argument("--check-passed", action="append", default=[])
    parser.add_argument("--check-failed", action="append", default=[])
    parser.add_argument("--duration-seconds", default="")
    parser.add_argument("--cost-usd", default="")
    parser.add_argument("--failure-mode", default="")
    parser.add_argument("--artifact-url", default="")
    parser.add_argument("--note", default="")
    parser.add_argument(
        "--print-rowset-schema",
        action="store_true",
        help="Print the create_dataset payload for the Rowset eval results dataset.",
    )
    parser.add_argument(
        "--rowset-dataset-key",
        help="Existing Rowset eval results dataset key to upsert the run row into.",
    )
    parser.add_argument(
        "--rowset-api-base",
        default="",
        help="Rowset REST API base. Defaults to ROWSET_REST_API_BASE or ROWSET_API_BASE.",
    )
    parser.add_argument(
        "--rowset-api-key-env",
        default="ROWSET_API_KEY",
        help="Environment variable containing the Rowset API key for writeback.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite files in an existing run directory.",
    )
    args = parser.parse_args()

    if args.print_rowset_schema and not args.seed_id:
        print(json.dumps(rowset_eval_result_schema_payload(), indent=2))
        return 0

    seed_doc = args.seed_doc if args.seed_doc.is_absolute() else args.root / args.seed_doc
    seeds = parse_seeds(seed_doc)
    if args.list or not args.seed_id:
        return list_seeds(seeds)
    return create_run(args, seeds)


if __name__ == "__main__":
    raise SystemExit(main())
