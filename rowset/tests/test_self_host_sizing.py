import json
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).parents[2]
_REQUIREMENTS_PATH = _REPO_ROOT / "deployment" / "self-host" / "requirements.json"
_BENCHMARKS_PATH = _REPO_ROOT / "docs" / "benchmarks" / "self-hosting"
_CHECK_REQUIREMENTS = _REPO_ROOT / "deployment" / "self-host" / "check-requirements.py"
_RESOLVE_DISK_FACTS = _REPO_ROOT / "deployment" / "self-host" / "resolve-disk-facts.sh"


def _requirements():
    return json.loads(_REQUIREMENTS_PATH.read_text())


def _benchmarks():
    return [json.loads(path.read_text()) for path in sorted(_BENCHMARKS_PATH.glob("*.json"))]


def _production_services():
    compose = yaml.safe_load((_REPO_ROOT / "docker-compose-prod.yml").read_text())
    return sorted(compose["services"])


def _production_dependency_images():
    compose = yaml.safe_load((_REPO_ROOT / "docker-compose-prod.yml").read_text())
    return {
        service["image"]
        for service in compose["services"].values()
        if not service["image"].startswith("${ROWSET_IMAGE:")
    }


def test_sizing_requirements_are_an_ordered_machine_readable_contract():
    requirements = _requirements()

    assert requirements["schema_version"] == 2
    assert requirements["supported_platforms"] == ["linux/amd64", "linux/arm64"]
    assert requirements["supported_operating_systems"] == [{"id": "ubuntu", "versions": ["24.04"]}]

    profiles = requirements["profiles"]
    assert list(profiles) == ["minimum", "tested", "recommended"]
    assert profiles == {
        "minimum": {
            "cpu_cores": 2,
            "memory_bytes": 3_750_000_000,
            "disk_capacity_bytes": 38_000_000_000,
        },
        "tested": {
            "cpu_cores": 2,
            "memory_bytes": 3_750_000_000,
            "disk_capacity_bytes": 38_000_000_000,
        },
        "recommended": {
            "cpu_cores": 4,
            "memory_bytes": 7_500_000_000,
            "disk_capacity_bytes": 75_000_000_000,
        },
    }
    for field in ("cpu_cores", "memory_bytes", "disk_capacity_bytes"):
        values = [profile[field] for profile in profiles.values()]
        assert all(isinstance(value, int) and value > 0 for value in values)
        assert values == sorted(values)

    assert profiles["minimum"] == profiles["tested"]
    assert profiles["recommended"]["memory_bytes"] > profiles["tested"]["memory_bytes"]
    assert (
        profiles["recommended"]["disk_capacity_bytes"] > profiles["tested"]["disk_capacity_bytes"]
    )
    assert requirements["runtime"] == {"minimum_free_disk_bytes": 30_000_000_000}
    assert requirements["startup"]["health_timeout_seconds"] >= 60


def test_benchmark_evidence_covers_every_supported_platform_with_one_image():
    requirements = _requirements()
    benchmarks = _benchmarks()

    cohorts = {}
    for benchmark in benchmarks:
        cohorts.setdefault(benchmark["benchmark_run_id"], []).append(benchmark)
    assert cohorts
    for cohort in cohorts.values():
        assert {benchmark["platform"] for benchmark in cohort} == set(
            requirements["supported_platforms"]
        )
        assert len({benchmark["image_digest"] for benchmark in cohort}) == 1
        assert len({benchmark["source_revision"] for benchmark in cohort}) == 1
        assert (
            len({json.dumps(benchmark["image_indexes"], sort_keys=True) for benchmark in cohort})
            == 1
        )

    tested = requirements["profiles"]["tested"]
    timeout = requirements["startup"]["health_timeout_seconds"]
    supported_os = {
        (item["id"], version)
        for item in requirements["supported_operating_systems"]
        for version in item["versions"]
    }
    for benchmark in benchmarks:
        assert benchmark["schema_version"] == 2
        image_references = {image["reference"] for image in benchmark["image_indexes"]}
        assert benchmark["image_reference"] in image_references
        assert image_references - {benchmark["image_reference"]} == _production_dependency_images()
        assert all(
            re.fullmatch(r"sha256:[0-9a-f]{64}", image["digest"])
            for image in benchmark["image_indexes"]
        )
        assert benchmark["image_digest"] in {
            image["digest"] for image in benchmark["image_indexes"]
        }
        assert re.fullmatch(r"[0-9a-f]{40}", benchmark["source_revision"])
        assert (
            benchmark["operating_system"]["id"],
            benchmark["operating_system"]["version"],
        ) in supported_os
        assert benchmark["services"] == _production_services()
        assert benchmark["host"]["cpu_cores"] >= tested["cpu_cores"]
        assert benchmark["host"]["memory_bytes"] >= tested["memory_bytes"]
        assert benchmark["host"]["disk_capacity_bytes"] >= tested["disk_capacity_bytes"]
        assert 0 < benchmark["measurements"]["cold_start_seconds"] <= timeout
        assert benchmark["measurements"]["image_logical_bytes"] > 0
        assert benchmark["measurements"]["disk_delta_bytes"] > 0
        assert benchmark["measurements"]["steady_state_memory_bytes"] > 0


def test_container_health_window_uses_the_benchmark_backed_timeout():
    requirements = _requirements()
    dockerfile = (_REPO_ROOT / "deployment" / "Dockerfile").read_text()
    match = re.search(r"HEALTHCHECK .*--start-period=(\d+)s", dockerfile)

    assert match
    assert int(match.group(1)) == requirements["startup"]["health_timeout_seconds"]


def test_sizing_docs_publish_profiles_evidence_and_capacity_guidance():
    requirements = _requirements()
    sizing = (_REPO_ROOT / "docs" / "self-host-sizing.md").read_text()
    self_hosting = (_REPO_ROOT / "SELF_HOSTING.md").read_text()

    for heading in ("Minimum", "Tested", "Recommended"):
        assert heading in sizing
    for subject in ("PostgreSQL", "local assets", "backups", "image layers", "log rotation"):
        assert subject in sizing
    for platform in requirements["supported_platforms"]:
        assert platform in sizing
    assert "deployment/self-host/requirements.json" in sizing
    assert "docs/self-host-sizing.md" in self_hosting


def test_benchmark_command_consumes_the_checked_in_requirements():
    script = (_REPO_ROOT / "deployment" / "self-host" / "benchmark.sh").read_text()

    assert "requirements.json" in script
    assert '"$requirements_file"' in script
    assert "--disk-capacity-bytes" in script
    assert "--disk-free-bytes" in script
    assert "cold_start_seconds" in script
    assert "image_logical_bytes" in script
    assert "compose config --services" in script


def test_benchmark_disk_facts_use_one_snapshot_and_independent_overrides(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_df = fake_bin / "df"
    fake_df.write_text("#!/bin/sh\nprintf 'Size Avail\\n39964635136 36244299776\\n'\n")
    fake_df.chmod(0o755)
    base_environment = {"PATH": f"{fake_bin}:{os.environ['PATH']}"}
    cases = (
        ({}, "39964635136 36244299776"),
        (
            {
                "ROWSET_BENCHMARK_DISK_CAPACITY_BYTES": "50000000000",
                "ROWSET_BENCHMARK_DISK_FREE_BYTES": "45000000000",
            },
            "50000000000 45000000000",
        ),
        ({"ROWSET_BENCHMARK_DISK_CAPACITY_BYTES": "50000000000"}, "50000000000 36244299776"),
        ({"ROWSET_BENCHMARK_DISK_FREE_BYTES": "45000000000"}, "39964635136 45000000000"),
    )

    for overrides, expected in cases:
        result = subprocess.run(
            ["sh", str(_RESOLVE_DISK_FACTS), "/var/lib/docker"],
            env={**base_environment, **overrides},
            check=True,
            capture_output=True,
            text=True,
        )

        assert result.stdout.strip() == expected


def test_requirement_checker_accepts_the_published_minimum():
    requirements = _requirements()
    minimum = requirements["profiles"]["minimum"]

    result = subprocess.run(
        [
            sys.executable,
            str(_CHECK_REQUIREMENTS),
            str(_REQUIREMENTS_PATH),
            "--platform",
            "linux/amd64",
            "--os-id",
            "ubuntu",
            "--os-version",
            "24.04",
            "--cpu-cores",
            str(minimum["cpu_cores"]),
            "--memory-bytes",
            str(minimum["memory_bytes"]),
            "--disk-capacity-bytes",
            str(minimum["disk_capacity_bytes"]),
            "--disk-free-bytes",
            str(requirements["runtime"]["minimum_free_disk_bytes"]),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert int(result.stdout) == requirements["startup"]["health_timeout_seconds"]


def test_requirement_checker_accepts_observed_minimum_host_after_prerequisites():
    requirements = _requirements()
    result = subprocess.run(
        [
            sys.executable,
            str(_CHECK_REQUIREMENTS),
            str(_REQUIREMENTS_PATH),
            "--platform",
            "linux/amd64",
            "--os-id",
            "ubuntu",
            "--os-version",
            "24.04",
            "--cpu-cores",
            "2",
            "--memory-bytes",
            "3_750_000_000",
            "--disk-capacity-bytes",
            "39_964_635_136",
            "--disk-free-bytes",
            "36_244_299_776",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert int(result.stdout) == requirements["startup"]["health_timeout_seconds"]


def test_requirement_checker_distinguishes_capacity_from_current_free_space():
    requirements = _requirements()
    minimum = requirements["profiles"]["minimum"]
    free_floor = requirements["runtime"]["minimum_free_disk_bytes"]
    cases = (
        (minimum["disk_capacity_bytes"] - 1, free_floor, "DISK_CAPACITY"),
        (minimum["disk_capacity_bytes"], free_floor - 1, "DISK_FREE"),
    )

    for capacity, free, expected_failure in cases:
        result = subprocess.run(
            [
                sys.executable,
                str(_CHECK_REQUIREMENTS),
                str(_REQUIREMENTS_PATH),
                "--platform",
                "linux/amd64",
                "--os-id",
                "ubuntu",
                "--os-version",
                "24.04",
                "--cpu-cores",
                str(minimum["cpu_cores"]),
                "--memory-bytes",
                str(minimum["memory_bytes"]),
                "--disk-capacity-bytes",
                str(capacity),
                "--disk-free-bytes",
                str(free),
                "--json",
            ],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 1
        payload = json.loads(result.stdout)
        assert [failure["id"] for failure in payload["failures"]] == [expected_failure]


def test_requirement_checker_reports_every_undersized_or_unsupported_field():
    result = subprocess.run(
        [
            sys.executable,
            str(_CHECK_REQUIREMENTS),
            str(_REQUIREMENTS_PATH),
            "--platform",
            "linux/riscv64",
            "--os-id",
            "debian",
            "--os-version",
            "13",
            "--cpu-cores",
            "1",
            "--memory-bytes",
            "1000",
            "--disk-capacity-bytes",
            "1000",
            "--disk-free-bytes",
            "1000",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    for failure in (
        "platform",
        "operating system",
        "CPU cores",
        "memory bytes",
        "disk capacity bytes",
        "free disk bytes",
    ):
        assert failure in result.stderr
