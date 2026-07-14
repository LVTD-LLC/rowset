import os
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).parents[2]


def _write_executable(path, contents):
    path.write_text(contents)
    path.chmod(0o755)


def _fake_command_environment(tmp_path, monkeypatch, *, machine, manifest="", docker_exit="0"):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "docker.log"
    _write_executable(bin_dir / "uname", f"#!/bin/sh\necho {machine}\n")
    _write_executable(
        bin_dir / "docker",
        "#!/bin/sh\n"
        'printf "%s\\n" "$*" >> "$FAKE_DOCKER_LOG"\n'
        'printf "%s\\n" "$FAKE_MANIFEST"\n'
        'exit "$FAKE_DOCKER_EXIT"\n',
    )
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_DOCKER_LOG", str(log_path))
    monkeypatch.setenv("FAKE_MANIFEST", manifest)
    monkeypatch.setenv("FAKE_DOCKER_EXIT", docker_exit)
    return log_path


@pytest.mark.parametrize(
    ("machine", "platform"),
    (("x86_64", "linux/amd64"), ("aarch64", "linux/arm64")),
)
def test_architecture_preflight_requires_the_host_platform_in_the_image_manifest(
    tmp_path, monkeypatch, machine, platform
):
    log_path = _fake_command_environment(
        tmp_path, monkeypatch, machine=machine, manifest=f"Platform: {platform}"
    )

    result = subprocess.run(
        [_REPO_ROOT / "deployment" / "verify-image-platforms.sh", "example/image:sha"],
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    assert log_path.read_text().splitlines() == [
        "buildx version",
        "buildx imagetools inspect example/image:sha",
    ]


def test_architecture_preflight_rejects_missing_manifest_platform(tmp_path, monkeypatch):
    _fake_command_environment(
        tmp_path, monkeypatch, machine="aarch64", manifest="Platform: linux/amd64"
    )

    result = subprocess.run(
        [_REPO_ROOT / "deployment" / "verify-image-platforms.sh", "example/image:sha"],
        text=True,
        capture_output=True,
    )

    assert result.returncode == 1
    assert "does not publish linux/arm64" in result.stderr


def test_architecture_preflight_rejects_unsupported_host(tmp_path, monkeypatch):
    _fake_command_environment(tmp_path, monkeypatch, machine="riscv64")

    result = subprocess.run(
        [_REPO_ROOT / "deployment" / "verify-image-platforms.sh", "example/image:sha"],
        text=True,
        capture_output=True,
    )

    assert result.returncode == 1
    assert "Unsupported host architecture: riscv64" in result.stderr


def test_architecture_preflight_rejects_invalid_platform_before_registry_access(
    tmp_path, monkeypatch
):
    log_path = _fake_command_environment(tmp_path, monkeypatch, machine="x86_64")

    result = subprocess.run(
        [
            _REPO_ROOT / "deployment" / "verify-image-platforms.sh",
            "example/image:sha",
            "linux/riscv64",
        ],
        text=True,
        capture_output=True,
    )

    assert result.returncode == 1
    assert "Unsupported Rowset image platform: linux/riscv64" in result.stderr
    assert log_path.read_text().splitlines() == ["buildx version"]


def test_platform_smoke_accepts_matching_machine(monkeypatch):
    from deployment import platform_smoke

    monkeypatch.setattr(platform_smoke.platform, "machine", lambda: "aarch64")

    platform_smoke.verify_runtime_platform("aarch64")


def test_platform_smoke_rejects_mismatched_machine(monkeypatch):
    from deployment import platform_smoke

    monkeypatch.setattr(platform_smoke.platform, "machine", lambda: "x86_64")

    with pytest.raises(RuntimeError, match="Expected aarch64, got x86_64"):
        platform_smoke.verify_runtime_platform("aarch64")


def test_multi_architecture_smoke_executes_the_published_image_on_each_platform(
    tmp_path, monkeypatch
):
    log_path = _fake_command_environment(tmp_path, monkeypatch, machine="x86_64")

    result = subprocess.run(
        [_REPO_ROOT / "deployment" / "smoke-image-platforms.sh", "example/image:sha"],
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    invocations = log_path.read_text().splitlines()
    assert len(invocations) == 2
    assert "--platform linux/amd64" in invocations[0]
    assert "example/image:sha" in invocations[0]
    assert invocations[0].endswith("x86_64")
    assert "--platform linux/arm64" in invocations[1]
    assert "example/image:sha" in invocations[1]
    assert invocations[1].endswith("aarch64")


def test_multi_architecture_smoke_propagates_docker_failure(tmp_path, monkeypatch):
    log_path = _fake_command_environment(tmp_path, monkeypatch, machine="x86_64", docker_exit="42")

    result = subprocess.run(
        [_REPO_ROOT / "deployment" / "smoke-image-platforms.sh", "example/image:sha"],
        text=True,
        capture_output=True,
    )

    assert result.returncode == 42
    assert len(log_path.read_text().splitlines()) == 1


def test_self_hosting_docs_name_supported_container_architectures_and_preflight():
    self_hosting = (_REPO_ROOT / "SELF_HOSTING.md").read_text()
    readme = (_REPO_ROOT / "README.md").read_text()

    for documentation in (self_hosting, readme):
        assert "linux/amd64" in documentation
        assert "linux/arm64" in documentation
        assert "deployment/verify-image-platforms.sh" in documentation


def test_production_compose_uses_the_preflighted_image_for_both_app_services():
    compose = (_REPO_ROOT / "docker-compose-prod.yml").read_text()

    assert compose.count("image: ${ROWSET_IMAGE:?") == 2
    assert "ghcr.io/lvtd-llc/rowset:latest" not in compose
