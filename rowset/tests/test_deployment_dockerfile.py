import re
from pathlib import Path

from django.core.management import call_command

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


def _entrypoint_lines():
    return (_REPO_ROOT / "deployment" / "entrypoint.sh").read_text().splitlines()


def test_docker_healthcheck_uses_project_environment():
    healthcheck_lines = _dockerfile_healthcheck_lines()
    command = healthcheck_lines[-1].strip()

    assert command.startswith("CMD ")
    assert '"/opt/venv/bin/python"' in command
    assert command.endswith('"deployment/healthcheck.py"]')


def test_docker_healthcheck_allows_server_startup_window():
    healthcheck_lines = _dockerfile_healthcheck_lines()

    assert any("--start-period=180s" in line for line in healthcheck_lines)


def test_entrypoint_only_runs_expected_management_commands():
    entrypoint = "\n".join(_entrypoint_lines())
    commands = re.findall(r"python manage\.py ([\w-]+)", entrypoint)

    assert commands == ["collectstatic", "migrate", "qcluster"]
    assert "sync_blog_posts" not in commands


def test_django_startup_check_does_not_parse_blog_markdown(settings, tmp_path):
    settings.BLOG_POST_CONTENT_DIR = tmp_path
    (tmp_path / "invalid.md").write_text(
        "---\n"
        "title: Invalid post\n"
        "slug: invalid-post\n"
        "status: published\n"
        "---\n"
        "Missing required SEO description and publish date.\n",
        encoding="utf-8",
    )

    call_command("check")
