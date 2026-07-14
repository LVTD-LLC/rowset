import re
import subprocess
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).parents[2]


def test_publish_workflow_syncs_app_image_and_cli_version_to_release_tag():
    workflow = (_REPO_ROOT / ".github" / "workflows" / "publish.yml").read_text()

    assert "[0-9][0-9][0-9][0-9].[0-9][0-9].[0-9][0-9]-[0-9]*" in workflow
    assert "${{ needs.validate.outputs.image_name }}:${{ github.ref_name }}" in workflow
    assert "-X github.com/LVTD-LLC/rowset/cli/internal/rowsetcli.Version=${RELEASE_TAG}" in workflow
    assert "rowset_${{ matrix.goos }}_${{ matrix.goarch }}.tar.gz" in workflow
    assert "scripts/install-rowset-cli.sh" in workflow


def test_release_workflows_publish_and_smoke_both_supported_platforms():
    workflow_jobs = (("deploy.yml", "build-and-deploy"), ("publish.yml", "app-image"))
    for workflow_name, job_name in workflow_jobs:
        workflow = yaml.safe_load(
            (_REPO_ROOT / ".github" / "workflows" / workflow_name).read_text()
        )
        assert workflow["concurrency"]["cancel-in-progress"] is False
        steps = workflow["jobs"][job_name]["steps"]
        step_names = [step["name"] for step in steps]
        qemu = steps[step_names.index("Set up QEMU")]
        build = steps[step_names.index("Build and push image")]
        verify_index = step_names.index("Verify published platforms")
        smoke_index = step_names.index("Smoke published platforms")

        assert qemu["uses"] == "docker/setup-qemu-action@v3"
        assert qemu["with"]["platforms"] == "arm64"
        assert build["uses"] == "docker/build-push-action@v6"
        assert build["with"]["platforms"] == "linux/amd64,linux/arm64"
        assert step_names.index("Build and push image") < verify_index < smoke_index

        immutable_tag = (
            "${{ github.sha }}" if workflow_name == "deploy.yml" else "${{ github.ref_name }}"
        )
        assert immutable_tag in steps[verify_index]["run"]
        assert immutable_tag in steps[smoke_index]["run"]

    publish = yaml.safe_load((_REPO_ROOT / ".github" / "workflows" / "publish.yml").read_text())
    assert publish["concurrency"]["group"] == "rowset-release-${{ github.ref_name }}"
    publish_build = next(
        step
        for step in publish["jobs"]["app-image"]["steps"]
        if step["name"] == "Build and push image"
    )
    assert ":latest" not in publish_build["with"]["tags"]
    assert "release_date" not in publish_build["with"]["tags"]
    assert "github.sha" not in publish_build["with"]["tags"]

    deploy_steps = yaml.safe_load(
        (_REPO_ROOT / ".github" / "workflows" / "deploy.yml").read_text()
    )["jobs"]["build-and-deploy"]["steps"]
    deploy_names = [step["name"] for step in deploy_steps]
    assert deploy_names.index("Smoke published platforms") < deploy_names.index(
        "Deploy server to CapRover"
    )


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
