from pathlib import Path


def test_docker_healthcheck_uses_project_environment():
    dockerfile = Path("deployment/Dockerfile").read_text()

    assert 'CMD ["/opt/venv/bin/python", "deployment/healthcheck.py"]' in dockerfile


def test_docker_healthcheck_allows_server_startup_window():
    dockerfile = Path("deployment/Dockerfile").read_text()

    assert "--start-period=180s" in dockerfile
