import re
import subprocess
import tarfile
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).parents[2]


def _build_self_host_release(tmp_path: Path, version: str = "2026.07.16-0") -> Path:
    output_dir = tmp_path / "release-assets"
    subprocess.run(
        [
            str(_REPO_ROOT / "scripts" / "build-self-host-release.sh"),
            version,
            "a" * 40,
            f"ghcr.io/lvtd-llc/rowset:{version}",
            "sha256:" + "b" * 64,
            str(output_dir),
        ],
        cwd=_REPO_ROOT,
        check=True,
    )
    return output_dir


def test_publish_workflow_syncs_app_image_and_cli_version_to_release_tag():
    workflow = (_REPO_ROOT / ".github" / "workflows" / "publish.yml").read_text()

    assert "[0-9][0-9][0-9][0-9].[0-9][0-9].[0-9][0-9]-[0-9]*" in workflow
    assert "${{ needs.validate.outputs.image_name }}:${{ github.ref_name }}" in workflow
    assert "-X github.com/LVTD-LLC/rowset/cli/internal/rowsetcli.Version=${RELEASE_TAG}" in workflow
    assert "rowset_${{ matrix.goos }}_${{ matrix.goarch }}.tar.gz" in workflow
    assert "scripts/install-rowset-cli.sh" in workflow


def test_publish_workflow_creates_an_immutable_matching_self_host_release():
    workflow = (_REPO_ROOT / ".github" / "workflows" / "publish.yml").read_text()

    assert "scripts/build-self-host-release.sh" in workflow
    assert "${{ github.sha }}" in workflow
    assert "${{ needs.app-image.outputs.digest }}" in workflow
    assert "rowset-self-host-${RELEASE_TAG}.tar.gz" in workflow
    assert "install-rowset-self-host.sh" in workflow
    assert "--clobber" not in workflow


def test_main_deploy_only_promotes_the_immutable_sha_tag():
    workflow = (_REPO_ROOT / ".github" / "workflows" / "deploy.yml").read_text()

    assert "${{ steps.image.outputs.image_name }}:${{ github.sha }}" in workflow
    assert "${{ steps.image.outputs.image_name }}:latest" not in workflow
    assert "release_date" not in workflow
    assert "release_version" not in workflow


def test_release_workflows_publish_and_smoke_both_supported_platforms():
    parsed_workflows = {
        workflow_name: yaml.safe_load(
            (_REPO_ROOT / ".github" / "workflows" / workflow_name).read_text()
        )
        for workflow_name in ("deploy.yml", "publish.yml")
    }
    for workflow_name, job_name in (
        ("deploy.yml", "build-and-deploy"),
        ("publish.yml", "app-image"),
    ):
        workflow = parsed_workflows[workflow_name]
        assert workflow["concurrency"]["cancel-in-progress"] is False
        steps = workflow["jobs"][job_name]["steps"]
        step_names = [step["name"] for step in steps]
        verify = steps[step_names.index("Verify published platforms")]
        smoke = steps[step_names.index("Smoke published platforms")]
        qemu = steps[step_names.index("Set up QEMU")]

        expected_tag = "candidate_tag" if workflow_name == "deploy.yml" else "github.sha"
        assert expected_tag in verify["run"]
        assert expected_tag in smoke["run"]
        assert qemu["uses"] == "docker/setup-qemu-action@v3"
        assert qemu["with"]["platforms"] == "arm64"

    deploy_steps = parsed_workflows["deploy.yml"]["jobs"]["build-and-deploy"]["steps"]
    deploy_names = [step["name"] for step in deploy_steps]
    qemu = deploy_steps[deploy_names.index("Set up QEMU")]
    build = deploy_steps[deploy_names.index("Build and push image")]
    assert qemu["uses"] == "docker/setup-qemu-action@v3"
    assert qemu["with"]["platforms"] == "arm64"
    assert build["uses"] == "docker/build-push-action@v6"
    assert build["with"]["platforms"] == "linux/amd64,linux/arm64"
    assert "candidate_tag" in build["with"]["tags"]
    assert "${{ github.sha }}" not in build["with"]["tags"]
    assert deploy_names.index("Build and push image") < deploy_names.index(
        "Verify anonymous candidate availability"
    )

    publish = yaml.safe_load((_REPO_ROOT / ".github" / "workflows" / "publish.yml").read_text())
    assert publish["concurrency"]["group"] == "rowset-release-${{ github.ref_name }}"
    publish_names = [step["name"] for step in publish["jobs"]["app-image"]["steps"]]
    assert "Build and push image" not in publish_names
    assert "Resolve immutable image digest" in publish_names
    resolve_step = publish["jobs"]["app-image"]["steps"][
        publish_names.index("Resolve immutable image digest")
    ]
    assert resolve_step["timeout-minutes"] == 15
    assert resolve_step["env"] == {
        "IMAGE_DIGEST_RESOLVE_ATTEMPTS": "60",
        "IMAGE_DIGEST_RESOLVE_DELAY_SECONDS": "10",
    }

    assert deploy_names.index("Smoke published platforms") < deploy_names.index(
        "Deploy server to CapRover"
    )


def test_release_workflows_gate_promotion_on_anonymous_image_availability():
    parsed_workflows = {
        workflow_name: yaml.safe_load(
            (_REPO_ROOT / ".github" / "workflows" / workflow_name).read_text()
        )
        for workflow_name in ("deploy.yml", "publish.yml")
    }
    workflows = (
        (
            "deploy.yml",
            "build-and-deploy",
            "Verify anonymous candidate availability",
            "${{ steps.build.outputs.digest }}",
            "candidate_tag",
            "Deploy server to CapRover",
        ),
        (
            "publish.yml",
            "app-image",
            "Verify anonymous immutable image availability",
            "${{ steps.image.outputs.digest }}",
            "github.sha",
            None,
        ),
    )

    for workflow_name, job_name, candidate_step, digest, candidate_tag, promotion_step in workflows:
        workflow = parsed_workflows[workflow_name]
        steps = workflow["jobs"][job_name]["steps"]
        step_names = [step["name"] for step in steps]
        candidate_index = step_names.index(candidate_step)
        promotion_index = step_names.index("Promote advertised tags")
        gate_index = step_names.index("Verify anonymous image availability")
        candidate_gate = steps[candidate_index]
        promotion = steps[promotion_index]
        gate = steps[gate_index]

        assert digest in candidate_gate["run"]
        assert candidate_tag in candidate_gate["run"]
        assert candidate_gate["timeout-minutes"] == 15
        assert "docker buildx imagetools create" in promotion["run"]
        assert f"@{digest}" in promotion["run"]
        assert digest in gate["run"]
        assert "deployment/verify-anonymous-image.sh" in gate["run"]
        assert gate.get("continue-on-error", False) is False
        assert gate.get("if", "${{ success() }}") == "${{ success() }}"
        assert gate["timeout-minutes"] == 15
        assert step_names.index("Smoke published platforms") < candidate_index
        assert candidate_index < promotion_index < gate_index
        if promotion_step:
            assert gate_index < step_names.index(promotion_step)

    deploy_gate = next(
        step
        for step in parsed_workflows["deploy.yml"]["jobs"]["build-and-deploy"]["steps"]
        if step["name"] == "Verify anonymous image availability"
    )
    assert "github.sha" in deploy_gate["run"]
    for mutable_tag in ("latest", "release_date", "release_version"):
        assert mutable_tag not in deploy_gate["run"]

    deploy_build = next(
        step
        for step in parsed_workflows["deploy.yml"]["jobs"]["build-and-deploy"]["steps"]
        if step["name"] == "Build and push image"
    )
    assert "candidate_tag" in deploy_build["with"]["tags"]
    assert "${{ github.sha }}" not in deploy_build["with"]["tags"]
    for mutable_tag in ("latest", "release_date", "release_version"):
        assert mutable_tag not in deploy_build["with"]["tags"]

    deploy_promotion = next(
        step
        for step in parsed_workflows["deploy.yml"]["jobs"]["build-and-deploy"]["steps"]
        if step["name"] == "Promote advertised tags"
    )
    assert "github.sha" in deploy_promotion["run"]
    for mutable_tag in ("latest", "release_date", "release_version"):
        assert mutable_tag not in deploy_promotion["run"]
    deploy_step_names = [
        step["name"] for step in parsed_workflows["deploy.yml"]["jobs"]["build-and-deploy"]["steps"]
    ]
    immutable_guard_index = deploy_step_names.index("Protect immutable SHA tag")
    assert (
        deploy_step_names.index("Verify anonymous candidate availability") < immutable_guard_index
    )
    assert immutable_guard_index < deploy_step_names.index("Promote advertised tags")

    publish = parsed_workflows["publish.yml"]
    publish_promotion = next(
        step
        for step in publish["jobs"]["app-image"]["steps"]
        if step["name"] == "Promote advertised tags"
    )
    assert "github.ref_name" in publish_promotion["run"]
    assert "app-image" in publish["jobs"]["release"]["needs"]
    publish_step_names = [step["name"] for step in publish["jobs"]["app-image"]["steps"]]
    immutable_release_index = publish_step_names.index("Protect immutable release tag")
    assert publish_step_names.index("Verify anonymous immutable image availability") < (
        immutable_release_index
    )
    assert immutable_release_index < publish_step_names.index("Promote advertised tags")
    immutable_release = publish["jobs"]["app-image"]["steps"][immutable_release_index]
    assert "deployment/verify-immutable-image-tag.sh" in immutable_release["run"]
    assert "github.ref_name" in immutable_release["run"]


def test_install_script_installs_rowset_cli_from_release_assets():
    installer = (_REPO_ROOT / "scripts" / "install-rowset-cli.sh").read_text()

    assert "https://github.com/LVTD-LLC/rowset/releases/latest/download" in installer
    assert "rowset_${os}_${arch}.tar.gz" in installer
    assert "ROWSET_CLI_VERSION" in installer
    assert re.search(r'install .*"\$install_dir/rowset"', installer)


def test_next_release_tag_uses_dotted_day_and_increments_suffix(tmp_path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, stdout=subprocess.DEVNULL)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Rowset Test",
            "-c",
            "user.email=rowset@example.com",
            "commit",
            "--allow-empty",
            "-m",
            "init",
        ],
        cwd=tmp_path,
        check=True,
        stdout=subprocess.DEVNULL,
    )
    subprocess.run(["git", "tag", "2026.07.08-0"], cwd=tmp_path, check=True)
    subprocess.run(["git", "tag", "2026.07.08-2"], cwd=tmp_path, check=True)
    subprocess.run(["git", "tag", "2026.07.07-9"], cwd=tmp_path, check=True)

    result = subprocess.run(
        [str(_REPO_ROOT / "scripts" / "next-release-tag.sh"), "2026.07.08"],
        cwd=tmp_path,
        check=True,
        text=True,
        capture_output=True,
    )

    assert result.stdout.strip() == "2026.07.08-3"


def test_self_host_release_builder_packages_matching_manifest_and_support_files(tmp_path):
    output_dir = _build_self_host_release(tmp_path)
    archive = output_dir / "rowset-self-host-2026.07.16-0.tar.gz"
    checksum = output_dir / "rowset-self-host-2026.07.16-0.tar.gz.sha256"
    installer = output_dir / "install-rowset-self-host.sh"

    assert archive.is_file()
    assert checksum.is_file()
    assert installer.is_file()
    assert installer.stat().st_mode & 0o111
    assert "@ROWSET_RELEASE_VERSION@" not in installer.read_text()
    assert "preflight.sh" in installer.read_text()
    assert "doctor.sh until its summary passes" in installer.read_text()

    with tarfile.open(archive) as bundle:
        names = set(bundle.getnames())
        manifest = bundle.extractfile("./.rowset-release")
        assert manifest is not None
        manifest_text = manifest.read().decode()

    assert {
        "./.rowset-release",
        "./SELF_HOSTING.md",
        "./docker-compose-prod.yml",
        "./deployment/self-host/init-env.sh",
        "./deployment/self-host/preflight.sh",
        "./deployment/self-host/doctor.sh",
        "./deployment/self-host/diagnostics.py",
        "./deployment/self-host/version.sh",
        "./deployment/verify-image-platforms.sh",
    } <= names
    assert "ROWSET_RELEASE_VERSION=2026.07.16-0" in manifest_text
    assert f"ROWSET_RELEASE_COMMIT={'a' * 40}" in manifest_text
    assert "ROWSET_RELEASE_IMAGE=ghcr.io/lvtd-llc/rowset:2026.07.16-0" in manifest_text
    assert f"ROWSET_RELEASE_DIGEST=sha256:{'b' * 64}" in manifest_text
    assert archive.name in checksum.read_text()


def test_self_host_installer_pins_first_release_and_preserves_it_on_rerun(tmp_path):
    first_assets = _build_self_host_release(tmp_path / "first", "2026.07.16-0")
    second_assets = _build_self_host_release(tmp_path / "second", "2026.07.16-1")
    install_dir = tmp_path / "installed"
    environment = {
        "ROWSET_INSTALL_DIR": str(install_dir),
        "ROWSET_RELEASE_BASE_URL": first_assets.as_uri(),
    }

    first = subprocess.run(
        [str(first_assets / "install-rowset-self-host.sh")],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert first.returncode == 0, first.stderr
    state = (install_dir / ".rowset-release").read_text()
    assert "ROWSET_RELEASE_VERSION=2026.07.16-0" in state

    rerun = subprocess.run(
        [str(second_assets / "install-rowset-self-host.sh")],
        env={
            **environment,
            "ROWSET_RELEASE_BASE_URL": first_assets.as_uri(),
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert rerun.returncode == 0, rerun.stderr
    assert (install_dir / ".rowset-release").read_text() == state


def test_self_host_installer_refuses_to_change_an_existing_release(tmp_path):
    first_assets = _build_self_host_release(tmp_path / "first", "2026.07.16-0")
    second_assets = _build_self_host_release(tmp_path / "second", "2026.07.16-1")
    install_dir = tmp_path / "installed"
    subprocess.run(
        [str(first_assets / "install-rowset-self-host.sh")],
        env={
            "ROWSET_INSTALL_DIR": str(install_dir),
            "ROWSET_RELEASE_BASE_URL": first_assets.as_uri(),
        },
        check=True,
    )
    state = (install_dir / ".rowset-release").read_bytes()

    result = subprocess.run(
        [str(second_assets / "install-rowset-self-host.sh")],
        env={
            "ROWSET_INSTALL_DIR": str(install_dir),
            "ROWSET_RELEASE_BASE_URL": second_assets.as_uri(),
            "ROWSET_VERSION": "2026.07.16-1",
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "does not update or roll back" in result.stderr
    assert (install_dir / ".rowset-release").read_bytes() == state


def test_self_host_installer_rejects_a_bundle_with_the_wrong_checksum(tmp_path):
    assets = _build_self_host_release(tmp_path)
    archive = assets / "rowset-self-host-2026.07.16-0.tar.gz"
    archive.write_bytes(archive.read_bytes() + b"corrupted")
    install_dir = tmp_path / "installed"

    result = subprocess.run(
        [str(assets / "install-rowset-self-host.sh")],
        env={
            "ROWSET_INSTALL_DIR": str(install_dir),
            "ROWSET_RELEASE_BASE_URL": assets.as_uri(),
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "checksum verification failed" in result.stderr
    assert not install_dir.exists()


def test_version_command_reports_release_commit_image_and_digest(tmp_path):
    assets = _build_self_host_release(tmp_path)
    install_dir = tmp_path / "installed"
    subprocess.run(
        [str(assets / "install-rowset-self-host.sh")],
        env={
            "ROWSET_INSTALL_DIR": str(install_dir),
            "ROWSET_RELEASE_BASE_URL": assets.as_uri(),
        },
        check=True,
    )

    result = subprocess.run(
        [str(install_dir / "deployment" / "self-host" / "version.sh")],
        cwd=install_dir,
        text=True,
        capture_output=True,
        check=True,
    )

    assert result.stdout.splitlines() == [
        "Version: 2026.07.16-0",
        f"Commit: {'a' * 40}",
        "Image: ghcr.io/lvtd-llc/rowset:2026.07.16-0",
        f"Digest: sha256:{'b' * 64}",
        "Configured image: not initialized",
    ]


def test_version_command_rejects_incomplete_release_metadata(tmp_path):
    release_file = tmp_path / ".rowset-release"
    release_file.write_text(
        "ROWSET_RELEASE_VERSION=2026.07.16-0\n"
        f"ROWSET_RELEASE_COMMIT={'a' * 40}\n"
        "ROWSET_RELEASE_IMAGE=ghcr.io/lvtd-llc/rowset:2026.07.16-0\n"
    )

    result = subprocess.run(
        [str(_REPO_ROOT / "deployment" / "self-host" / "version.sh")],
        env={"ROWSET_RELEASE_FILE": str(release_file)},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "ROWSET_RELEASE_DIGEST" in result.stderr
