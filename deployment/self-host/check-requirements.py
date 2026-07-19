#!/usr/bin/env python3
import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class HostFacts:
    platform: str
    os_id: str
    os_version: str
    cpu_cores: int
    memory_bytes: int
    disk_capacity_bytes: int
    disk_free_bytes: int


@dataclass(frozen=True)
class RequirementOutcome:
    id: str
    passed: bool
    message: str


def evaluate_requirements(requirements: dict, facts: HostFacts) -> list[RequirementOutcome]:
    minimum = requirements["profiles"]["minimum"]
    supported_os = {
        (item["id"], version)
        for item in requirements["supported_operating_systems"]
        for version in item["versions"]
    }
    checks = (
        (
            "OS",
            (facts.os_id, facts.os_version) in supported_os,
            f"operating system {facts.os_id} {facts.os_version}",
        ),
        (
            "ARCH",
            facts.platform in requirements["supported_platforms"],
            f"platform {facts.platform}",
        ),
        (
            "CPU",
            facts.cpu_cores >= minimum["cpu_cores"],
            f"CPU cores {facts.cpu_cores} < {minimum['cpu_cores']}",
        ),
        (
            "MEMORY",
            facts.memory_bytes >= minimum["memory_bytes"],
            f"memory bytes {facts.memory_bytes} < {minimum['memory_bytes']}",
        ),
        (
            "DISK_CAPACITY",
            facts.disk_capacity_bytes >= minimum["disk_capacity_bytes"],
            "disk capacity bytes "
            f"{facts.disk_capacity_bytes}; minimum {minimum['disk_capacity_bytes']}",
        ),
        (
            "DISK_FREE",
            facts.disk_free_bytes >= requirements["runtime"]["minimum_free_disk_bytes"],
            "free disk bytes "
            f"{facts.disk_free_bytes}; minimum "
            f"{requirements['runtime']['minimum_free_disk_bytes']}",
        ),
    )
    return [RequirementOutcome(check_id, passed, message) for check_id, passed, message in checks]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("requirements", type=Path)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--os-id", required=True)
    parser.add_argument("--os-version", required=True)
    parser.add_argument("--cpu-cores", type=int, required=True)
    parser.add_argument("--memory-bytes", type=int, required=True)
    parser.add_argument("--disk-capacity-bytes", type=int, required=True)
    parser.add_argument("--disk-free-bytes", type=int, required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    requirements = json.loads(args.requirements.read_text())
    outcomes = evaluate_requirements(
        requirements,
        HostFacts(
            platform=args.platform,
            os_id=args.os_id,
            os_version=args.os_version,
            cpu_cores=args.cpu_cores,
            memory_bytes=args.memory_bytes,
            disk_capacity_bytes=args.disk_capacity_bytes,
            disk_free_bytes=args.disk_free_bytes,
        ),
    )
    failures = [outcome for outcome in outcomes if not outcome.passed]
    if args.json:
        print(
            json.dumps(
                {
                    "checks": [asdict(outcome) for outcome in outcomes],
                    "failures": [asdict(outcome) for outcome in failures],
                    "health_timeout_seconds": requirements["startup"]["health_timeout_seconds"],
                },
                separators=(",", ":"),
            )
        )
    if failures:
        if not args.json:
            raise SystemExit(
                "Host does not meet requirements: "
                + "; ".join(failure.message for failure in failures)
            )
        raise SystemExit(1)

    if not args.json:
        print(requirements["startup"]["health_timeout_seconds"])


if __name__ == "__main__":
    main()
