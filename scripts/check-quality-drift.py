#!/usr/bin/env python3
"""Check that Rowset quality commands stay wired through docs, CI, and local CI."""

from __future__ import annotations

import argparse
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CommandExpectation:
    name: str
    docs: bool = True
    github_ci: bool = True
    local_ci: bool = True


EXPECTED_COMMANDS = (
    CommandExpectation("lint-python"),
    CommandExpectation("format-check"),
    CommandExpectation("quality-drift-check"),
    CommandExpectation("startup-smoke"),
    CommandExpectation("type-check"),
    CommandExpectation("frontend-install"),
    CommandExpectation("frontend-check"),
    CommandExpectation("migrations-check"),
    CommandExpectation("django-check"),
    CommandExpectation("test"),
    CommandExpectation("coverage-high-risk", local_ci=False),
)

FILES = {
    "makefile": Path("Makefile"),
    "docs": Path("docs/quality.md"),
    "github_ci": Path(".github/workflows/ci.yml"),
    "local_ci": Path("scripts/ci-local.sh"),
}


def _read(root: Path, relative_path: Path) -> str:
    path = root / relative_path
    try:
        return path.read_text()
    except FileNotFoundError:
        return ""


def _make_targets(makefile: str) -> set[str]:
    targets: set[str] = set()
    target_pattern = re.compile(r"^([A-Za-z0-9_.-]+):(?:\s|$)")
    for line in makefile.splitlines():
        if line.startswith(("\t", " ", "#", ".")):
            continue
        match = target_pattern.match(line)
        if match:
            targets.add(match.group(1))
    return targets


def _references_make_command(text: str, command: str) -> bool:
    return re.search(rf"\bmake\s+{re.escape(command)}(?:\s|$)", text) is not None


def check_root(root: Path) -> list[str]:
    makefile = _read(root, FILES["makefile"])
    docs = _read(root, FILES["docs"])
    github_ci = _read(root, FILES["github_ci"])
    local_ci = _read(root, FILES["local_ci"])
    targets = _make_targets(makefile)

    errors: list[str] = []
    for command in EXPECTED_COMMANDS:
        if command.name not in targets:
            errors.append(f"Makefile is missing target `{command.name}`")
        if command.docs and not _references_make_command(docs, command.name):
            errors.append(f"{FILES['docs']} does not reference `make {command.name}`")
        if command.github_ci and not _references_make_command(github_ci, command.name):
            errors.append(f"{FILES['github_ci']} does not run `make {command.name}`")
        if command.local_ci and not _references_make_command(local_ci, command.name):
            errors.append(f"{FILES['local_ci']} does not run `make {command.name}`")
    return errors


def run_self_test() -> int:
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        (root / "docs").mkdir()
        (root / ".github/workflows").mkdir(parents=True)
        (root / "scripts").mkdir()

        command_names = [command.name for command in EXPECTED_COMMANDS]
        (root / FILES["makefile"]).write_text(
            ".PHONY: "
            + " ".join(command_names)
            + "\n"
            + "\n".join(f"{name}:\n\t@true" for name in command_names)
            + "\n"
        )
        all_references = "\n".join(f"make {name}" for name in command_names)
        (root / FILES["docs"]).write_text(all_references.replace("make lint-python\n", ""))
        (root / FILES["github_ci"]).write_text(all_references)
        (root / FILES["local_ci"]).write_text(
            "\n".join(f"make {name}" for name in command_names if name != "coverage-high-risk")
        )

        errors = check_root(root)

    expected_error = f"{FILES['docs']} does not reference `make lint-python`"
    if expected_error not in errors:
        print("Negative fixture did not catch a missing docs command reference.", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("Negative fixture passed.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run the built-in negative fixture for the checker itself.",
    )
    args = parser.parse_args()

    if args.self_test:
        return run_self_test()

    errors = check_root(args.root)
    if errors:
        print("Quality command drift detected:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print("Quality command matrix is aligned.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
