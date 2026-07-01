from pathlib import Path

_REPO_ROOT = Path(__file__).parents[2]


def test_docker_healthcheck_uses_project_environment():
    dockerfile = (_REPO_ROOT / "deployment" / "Dockerfile").read_text()

    assert 'CMD ["/opt/venv/bin/python", "deployment/healthcheck.py"]' in dockerfile


def test_docker_healthcheck_allows_server_startup_window():
    dockerfile = (_REPO_ROOT / "deployment" / "Dockerfile").read_text()

    assert "--start-period=180s" in dockerfile
