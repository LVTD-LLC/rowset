from pathlib import Path

_REPO_ROOT = Path(__file__).parents[2]


def _dockerfile_healthcheck_lines():
    dockerfile = (_REPO_ROOT / "deployment" / "Dockerfile").read_text()
    lines = dockerfile.splitlines()
    start = next(index for index, line in enumerate(lines) if line.startswith("HEALTHCHECK "))

    healthcheck_lines = [lines[start]]
    for line in lines[start + 1 :]:
        healthcheck_lines.append(line)
        if line.lstrip().startswith("CMD "):
            break

    return healthcheck_lines


def test_docker_healthcheck_uses_project_environment():
    healthcheck_lines = _dockerfile_healthcheck_lines()
    command = healthcheck_lines[-1].strip()

    assert command.startswith("CMD ")
    assert '"/opt/venv/bin/python"' in command
    assert command.endswith('"deployment/healthcheck.py"]')


def test_docker_healthcheck_allows_server_startup_window():
    healthcheck_lines = _dockerfile_healthcheck_lines()

    assert any("--start-period=180s" in line for line in healthcheck_lines)
