from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_self_host_smoke_wrapper_uses_backend_management_command_without_key_arguments():
    script = (REPO_ROOT / "deployment/self-host/smoke-test.sh").read_text()

    assert "post_deploy_smoke_test" in script
    assert "ROWSET_API_KEY" not in script
    assert "--api-key" not in script
    assert "exec -T backend" in script
