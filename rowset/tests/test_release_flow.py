import re
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).parents[2]


def test_publish_workflow_syncs_app_image_and_cli_version_to_release_tag():
    workflow = (_REPO_ROOT / ".github" / "workflows" / "publish.yml").read_text()

    assert "[0-9][0-9][0-9][0-9].[0-9][0-9].[0-9][0-9]-[0-9]*" in workflow
    assert "${{ needs.validate.outputs.image_name }}:${{ github.ref_name }}" in workflow
    assert "-X github.com/LVTD-LLC/rowset/cli/internal/rowsetcli.Version=${RELEASE_TAG}" in workflow
    assert "rowset-cli_${{ matrix.goos }}_${{ matrix.goarch }}.tar.gz" in workflow
    assert "scripts/install-rowset-cli.sh" in workflow


def test_install_script_installs_rowset_cli_from_release_assets():
    installer = (_REPO_ROOT / "scripts" / "install-rowset-cli.sh").read_text()

    assert "https://github.com/LVTD-LLC/rowset/releases/latest/download" in installer
    assert "rowset-cli_${os}_${arch}.tar.gz" in installer
    assert "ROWSET_CLI_VERSION" in installer
    assert re.search(r'install .*"\$install_dir/rowset-cli"', installer)


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
