#!/usr/bin/env python3
import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--os-id", required=True)
    parser.add_argument("--os-version", required=True)
    parser.add_argument("--cpu-cores", type=int, required=True)
    parser.add_argument("--memory-bytes", type=int, required=True)
    parser.add_argument("--disk-capacity-bytes", type=int, required=True)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--server-type", required=True)
    parser.add_argument("--benchmark-run-id", required=True)
    parser.add_argument("--image-reference", required=True)
    parser.add_argument("--image-digest", required=True)
    parser.add_argument("--image-indexes", type=json.loads, required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--docker-version", required=True)
    parser.add_argument("--pull-seconds", type=int, required=True)
    parser.add_argument("--cold-start-seconds", type=int, required=True)
    parser.add_argument("--image-logical-bytes", type=int, required=True)
    parser.add_argument("--disk-delta-bytes", type=int, required=True)
    parser.add_argument("--steady-state-memory-bytes", type=int, required=True)
    parser.add_argument("--available-memory-bytes", type=int, required=True)
    parser.add_argument("--measured-at", required=True)
    parser.add_argument("--services", type=json.loads, required=True)
    args = parser.parse_args()
    document = {
        "schema_version": 2,
        "benchmark_run_id": args.benchmark_run_id,
        "measured_at": args.measured_at,
        "platform": args.platform,
        "operating_system": {"id": args.os_id, "version": args.os_version},
        "host": {
            "provider": args.provider,
            "server_type": args.server_type,
            "cpu_cores": args.cpu_cores,
            "memory_bytes": args.memory_bytes,
            "disk_capacity_bytes": args.disk_capacity_bytes,
        },
        "image_reference": args.image_reference,
        "image_digest": args.image_digest,
        "image_indexes": args.image_indexes,
        "source_revision": args.source_revision,
        "docker_version": args.docker_version,
        "services": args.services,
        "measurements": {
            "image_pull_seconds": args.pull_seconds,
            "cold_start_seconds": args.cold_start_seconds,
            "image_logical_bytes": args.image_logical_bytes,
            "disk_delta_bytes": args.disk_delta_bytes,
            "steady_state_memory_bytes": args.steady_state_memory_bytes,
            "available_memory_after_start_bytes": args.available_memory_bytes,
        },
    }
    args.output.write_text(json.dumps(document, indent=2) + "\n")


if __name__ == "__main__":
    main()
