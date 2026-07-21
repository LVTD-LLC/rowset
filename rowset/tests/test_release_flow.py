import re
import subprocess
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).parents[2]


def test_publish_workflow_syncs_app_image_and_cli_version_to_release_tag():
    workflow = (_REPO_ROOT / ".github" / "workflows" / "publish.yml").read_text()

    assert "[0-9][0-9][0-9][0-9].[0-9][0-9].[0-9][0-9]-[0-9]*" in workflow
    assert (
        "${{ needs.validate.outputs.image_name }}:${{ needs.validate.outputs.release_tag }}"
        in workflow
    )
    assert (
        "${{ needs.validate.outputs.image_name }}:${{ needs.validate.outputs.release_sha }}"
        in workflow
    )
    assert "-X github.com/LVTD-LLC/rowset/cli/internal/rowsetcli.Version=${RELEASE_TAG}" in workflow
    assert "rowset_${{ matrix.goos }}_${{ matrix.goarch }}.tar.gz" in workflow
    assert "scripts/install-rowset-cli.sh" in workflow


def test_publish_workflow_releases_the_immutable_image_without_self_host_bundles():
    workflow = (_REPO_ROOT / ".github" / "workflows" / "publish.yml").read_text()
    parsed_workflow = yaml.safe_load(workflow)

    assert "release_sha: ${{ steps.release.outputs.release_sha }}" in workflow
    assert "ref: ${{ needs.validate.outputs.release_sha }}" in workflow
    assert (
        "${{ needs.validate.outputs.image_name }}:${{ needs.validate.outputs.release_tag }}"
        in workflow
    )
    assert "build-self-host-release.sh" not in workflow
    assert "verify-self-host-release-contract.sh" not in workflow
    assert "rowset-self-host-" not in workflow
    assert "install-rowset-self-host.sh" not in workflow
    assert "SELF_HOSTING.md" in workflow
    assert '--target "$RELEASE_SHA"' in workflow
    assert "--clobber" not in workflow
    validate_steps = parsed_workflow["jobs"]["validate"]["steps"]
    assert "Verify self-host release contract" not in [step["name"] for step in validate_steps]
    assert parsed_workflow["jobs"]["app-image"]["needs"] == "validate"


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

        expected_tag = "candidate_tag" if workflow_name == "deploy.yml" else "release_sha"
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
    assert publish["concurrency"]["group"] == (
        "rowset-release-${{ inputs.release_tag || github.ref_name }}"
    )
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
            "release_sha",
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
    assert "release_tag" in publish_promotion["run"]
    assert "app-image" in publish["jobs"]["release"]["needs"]
    publish_step_names = [step["name"] for step in publish["jobs"]["app-image"]["steps"]]
    immutable_release_index = publish_step_names.index("Protect immutable release tag")
    assert publish_step_names.index("Verify anonymous immutable image availability") < (
        immutable_release_index
    )
    assert immutable_release_index < publish_step_names.index("Promote advertised tags")
    immutable_release = publish["jobs"]["app-image"]["steps"][immutable_release_index]
    assert "deployment/verify-immutable-image-tag.sh" in immutable_release["run"]
    assert "release_tag" in immutable_release["run"]


def test_daily_release_cutter_skips_unchanged_main_and_requires_a_successful_deploy():
    workflow_path = _REPO_ROOT / ".github" / "workflows" / "release-cutter.yml"
    workflow = workflow_path.read_text()
    parsed_workflow = yaml.safe_load(workflow)

    assert "schedule:" in workflow
    assert "workflow_dispatch:" in workflow
    assert "gh release view" in workflow
    assert 'if [[ "$latest_release_sha" == "$head_sha" ]]' in workflow
    assert "should_release=false" in workflow
    assert "gh run list" in workflow
    assert "--workflow deploy.yml" in workflow
    assert '--commit "$head_sha"' in workflow
    assert '[[ "$deploy_status" != "completed" || "$deploy_conclusion" != "success" ]]' in workflow
    assert "scripts/next-release-tag.sh" in workflow

    publish = parsed_workflow["jobs"]["publish"]
    assert publish["needs"] == "prepare"
    assert publish["if"] == "needs.prepare.outputs.should_release == 'true'"
    assert publish["uses"] == "./.github/workflows/publish.yml"
    assert publish["with"] == {
        "release_tag": "${{ needs.prepare.outputs.release_tag }}",
        "release_sha": "${{ needs.prepare.outputs.release_sha }}",
    }


def test_publish_workflow_accepts_an_exact_scheduled_release_identity():
    workflow = (_REPO_ROOT / ".github" / "workflows" / "publish.yml").read_text()

    assert "workflow_call:" in workflow
    assert "release_tag:" in workflow
    assert "release_sha:" in workflow
    assert 'release_tag="${RELEASE_TAG_INPUT:-$GITHUB_REF_NAME}"' in workflow
    assert 'release_sha="${RELEASE_SHA_INPUT:-$GITHUB_SHA}"' in workflow


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
