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


def _fake_anonymous_registry_environment(
    tmp_path,
    monkeypatch,
    *,
    digest="sha256:expected",
    private=False,
    pull_exit="0",
    logout_exit="0",
    buildx_in_config=False,
):
    bin_dir = tmp_path / "anonymous-bin"
    bin_dir.mkdir()
    log_path = tmp_path / "anonymous-docker.log"
    original_config = tmp_path / "authenticated-docker"
    original_config.mkdir()
    (original_config / "config.json").write_text('{"auths":{"ghcr.io":{"auth":"secret"}}}')
    if buildx_in_config:
        cli_plugins = original_config / "cli-plugins"
        cli_plugins.mkdir()
        _write_executable(cli_plugins / "docker-buildx", "#!/bin/sh\nexit 0\n")
    _write_executable(
        bin_dir / "docker",
        "#!/bin/sh\n"
        'if [ "$*" = "logout ghcr.io" ]; then\n'
        '  printf "%s|%s\\n" "$DOCKER_CONFIG" "$*" >> "$FAKE_DOCKER_LOG"\n'
        '  exit "$FAKE_LOGOUT_EXIT"\n'
        "else\n"
        '  config="$(tr -d "[:space:]" < "$DOCKER_CONFIG/config.json")"\n'
        '  printf "%s|%s|%s\\n" "$DOCKER_CONFIG" "$config" '
        '"$*" >> "$FAKE_DOCKER_LOG"\n'
        "fi\n"
        'if [ "$FAKE_REQUIRE_BUILDX_PLUGIN" = "1" ] && [ "$1" = "buildx" ] '
        '&& [ ! -x "$DOCKER_CONFIG/cli-plugins/docker-buildx" ]; then exit 127; fi\n'
        'if [ "$*" = "buildx version" ]; then exit 0; fi\n'
        'if [ "$1 $2 $3" = "buildx imagetools inspect" ]; then\n'
        '  if [ "$FAKE_PRIVATE" = "1" ] '
        '&& [ "$config" = \'{"auths":{}}\' ]; then exit 1; fi\n'
        '  printf "Name: %s\\nDigest: %s\\nPlatform: linux/amd64\\n'
        'Platform: linux/arm64\\n" "$4" "$FAKE_DIGEST"\n'
        "fi\n"
        'if [ "$1" = "pull" ]; then exit "$FAKE_PULL_EXIT"; fi\n',
    )
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setenv("DOCKER_CONFIG", str(original_config))
    monkeypatch.setenv("FAKE_DOCKER_LOG", str(log_path))
    monkeypatch.setenv("FAKE_DIGEST", digest)
    monkeypatch.setenv("FAKE_PRIVATE", "1" if private else "0")
    monkeypatch.setenv("FAKE_PULL_EXIT", pull_exit)
    monkeypatch.setenv("FAKE_LOGOUT_EXIT", logout_exit)
    monkeypatch.setenv("FAKE_REQUIRE_BUILDX_PLUGIN", "1" if buildx_in_config else "0")
    return log_path, original_config


def test_anonymous_gate_discards_credentials_and_pulls_every_supported_platform(
    tmp_path, monkeypatch
):
    log_path, original_config = _fake_anonymous_registry_environment(tmp_path, monkeypatch)

    result = subprocess.run(
        [
            _REPO_ROOT / "deployment" / "verify-anonymous-image.sh",
            "sha256:expected",
            "ghcr.io/example/rowset:stable",
            "ghcr.io/example/rowset:immutable",
        ],
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    invocations = log_path.read_text().splitlines()
    assert invocations[0] == f"{original_config}|logout ghcr.io"
    anonymous_invocations = invocations[1:]
    assert anonymous_invocations
    assert all(
        not invocation.startswith(f"{original_config}|") for invocation in anonymous_invocations
    )
    assert all('|{"auths":{}}|' in invocation for invocation in anonymous_invocations)
    for image in ("ghcr.io/example/rowset:stable", "ghcr.io/example/rowset:immutable"):
        assert (
            sum(f"buildx imagetools inspect {image}" in call for call in anonymous_invocations) == 1
        )
        for platform in ("linux/amd64", "linux/arm64"):
            assert any(
                f"pull --platform {platform} {image}@sha256:expected" in call
                for call in anonymous_invocations
            )


def test_anonymous_gate_rejects_private_package_with_remediation(tmp_path, monkeypatch):
    _fake_anonymous_registry_environment(tmp_path, monkeypatch, private=True)

    result = subprocess.run(
        [
            _REPO_ROOT / "deployment" / "verify-anonymous-image.sh",
            "sha256:expected",
            "ghcr.io/example/rowset:private",
        ],
        text=True,
        capture_output=True,
    )

    assert result.returncode == 1
    assert "not anonymously inspectable" in result.stderr
    assert "Change the GHCR package visibility to public" in result.stderr


def test_anonymous_gate_rejects_tag_digest_mismatch(tmp_path, monkeypatch):
    _fake_anonymous_registry_environment(tmp_path, monkeypatch, digest="sha256:wrong")

    result = subprocess.run(
        [
            _REPO_ROOT / "deployment" / "verify-anonymous-image.sh",
            "sha256:expected",
            "ghcr.io/example/rowset:stable",
        ],
        text=True,
        capture_output=True,
    )

    assert result.returncode == 1
    assert "resolved to sha256:wrong; expected sha256:expected" in result.stderr


def test_anonymous_gate_blocks_when_a_platform_pull_fails(tmp_path, monkeypatch):
    log_path, _ = _fake_anonymous_registry_environment(tmp_path, monkeypatch, pull_exit="42")

    result = subprocess.run(
        [
            _REPO_ROOT / "deployment" / "verify-anonymous-image.sh",
            "sha256:expected",
            "ghcr.io/example/rowset:stable",
            "ghcr.io/example/rowset:later",
        ],
        text=True,
        capture_output=True,
    )

    assert result.returncode == 1
    assert "could not be pulled anonymously for linux/amd64" in result.stderr
    assert "Change the GHCR package visibility to public" in result.stderr
    assert "ghcr.io/example/rowset:later" not in log_path.read_text()


def test_anonymous_gate_blocks_when_registry_logout_fails(tmp_path, monkeypatch):
    log_path, original_config = _fake_anonymous_registry_environment(
        tmp_path, monkeypatch, logout_exit="42"
    )

    result = subprocess.run(
        [
            _REPO_ROOT / "deployment" / "verify-anonymous-image.sh",
            "sha256:expected",
            "ghcr.io/example/rowset:stable",
        ],
        text=True,
        capture_output=True,
    )

    assert result.returncode == 1
    assert "Could not remove the GHCR login" in result.stderr
    assert log_path.read_text().splitlines() == [f"{original_config}|logout ghcr.io"]


def test_anonymous_gate_preserves_docker_cli_plugins_without_copying_credentials(
    tmp_path, monkeypatch
):
    _fake_anonymous_registry_environment(tmp_path, monkeypatch, buildx_in_config=True)

    result = subprocess.run(
        [
            _REPO_ROOT / "deployment" / "verify-anonymous-image.sh",
            "sha256:expected",
            "ghcr.io/example/rowset:stable",
        ],
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr


def test_digest_resolver_returns_the_registry_digest(tmp_path, monkeypatch):
    _fake_command_environment(
        tmp_path,
        monkeypatch,
        machine="x86_64",
        manifest=f"Digest: sha256:{'a' * 64}",
    )

    result = subprocess.run(
        [_REPO_ROOT / "deployment" / "resolve-image-digest.sh", "example/image:sha"],
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"sha256:{'a' * 64}"


def test_digest_resolver_retries_an_image_that_is_still_being_promoted(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    counter = tmp_path / "attempts"
    _write_executable(
        bin_dir / "docker",
        "#!/bin/sh\n"
        'attempt="$(cat "$FAKE_COUNTER" 2>/dev/null || echo 0)"\n'
        'attempt="$((attempt + 1))"\n'
        'printf "%s" "$attempt" > "$FAKE_COUNTER"\n'
        'if [ "$attempt" -eq 1 ]; then echo "manifest unknown"; exit 1; fi\n'
        f"echo 'Digest: sha256:{'a' * 64}'\n",
    )
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_COUNTER", str(counter))
    monkeypatch.setenv("IMAGE_DIGEST_RESOLVE_ATTEMPTS", "2")
    monkeypatch.setenv("IMAGE_DIGEST_RESOLVE_DELAY_SECONDS", "0")

    result = subprocess.run(
        [_REPO_ROOT / "deployment" / "resolve-image-digest.sh", "example/image:sha"],
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"sha256:{'a' * 64}"
    assert counter.read_text() == "2"


@pytest.mark.parametrize(
    ("manifest", "docker_exit", "expected_returncode"),
    (
        (f"Digest: sha256:{'a' * 64}", "0", 0),
        (f"Digest: sha256:{'b' * 64}", "0", 1),
        ("manifest unknown", "1", 0),
        ("registry timeout", "1", 1),
    ),
)
def test_immutable_tag_guard_only_allows_absent_or_matching_tags(
    tmp_path, monkeypatch, manifest, docker_exit, expected_returncode
):
    _fake_command_environment(
        tmp_path,
        monkeypatch,
        machine="x86_64",
        manifest=manifest,
        docker_exit=docker_exit,
    )

    result = subprocess.run(
        [
            _REPO_ROOT / "deployment" / "verify-immutable-image-tag.sh",
            f"sha256:{'a' * 64}",
            "example/image:sha",
        ],
        text=True,
        capture_output=True,
    )

    assert result.returncode == expected_returncode


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
