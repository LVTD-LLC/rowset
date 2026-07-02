#!/usr/bin/env python3
"""Create structured run artifacts from Rowset agent eval seeds."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[1]
SEED_DOC = Path("docs/agent-evals/seed-tasks.md")
DEFAULT_RUNS_DIR = Path("docs/agent-evals/runs")
HEADING_RE = re.compile(r"^### (?P<seed_id>EVAL-\d+): (?P<title>.+)$")
FIELD_RE = re.compile(r"^- \*\*(?P<label>[^*]+):\*\*\s*(?P<value>.*)$")
CODE_SPAN_RE = re.compile(r"`([^`]+)`")


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
        "artifact_schema_version": 1,
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
        "result_status": args.status,
        "follow_up_notes": follow_up_notes,
    }


def _markdown_for_artifact(artifact: dict[str, object]) -> str:
    seed = cast(Mapping[str, object], artifact["seed"])
    required_checks = artifact["required_checks"]
    observed_checks = artifact["observed_checks"]
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
    parser.add_argument("--note", default="")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite files in an existing run directory.",
    )
    args = parser.parse_args()

    seed_doc = args.seed_doc if args.seed_doc.is_absolute() else args.root / args.seed_doc
    seeds = parse_seeds(seed_doc)
    if args.list or not args.seed_id:
        return list_seeds(seeds)
    return create_run(args, seeds)


if __name__ == "__main__":
    raise SystemExit(main())
