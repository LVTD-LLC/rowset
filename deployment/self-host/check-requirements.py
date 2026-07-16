#!/usr/bin/env python3
import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("requirements", type=Path)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--os-id", required=True)
    parser.add_argument("--os-version", required=True)
    parser.add_argument("--cpu-cores", type=int, required=True)
    parser.add_argument("--memory-bytes", type=int, required=True)
    parser.add_argument("--disk-bytes", type=int, required=True)
    args = parser.parse_args()

    requirements = json.loads(args.requirements.read_text())
    minimum = requirements["profiles"]["minimum"]
    supported_os = {
        (item["id"], version)
        for item in requirements["supported_operating_systems"]
        for version in item["versions"]
    }
    failures = []
    if args.platform not in requirements["supported_platforms"]:
        failures.append(f"platform {args.platform}")
    if (args.os_id, args.os_version) not in supported_os:
        failures.append(f"operating system {args.os_id} {args.os_version}")
    for name, actual, expected in (
        ("CPU cores", args.cpu_cores, minimum["cpu_cores"]),
        ("memory bytes", args.memory_bytes, minimum["memory_bytes"]),
        ("disk bytes", args.disk_bytes, minimum["disk_bytes"]),
    ):
        if actual < expected:
            failures.append(f"{name} {actual} < {expected}")
    if failures:
        raise SystemExit("Host does not meet requirements: " + "; ".join(failures))

    print(requirements["startup"]["health_timeout_seconds"])


if __name__ == "__main__":
    main()
