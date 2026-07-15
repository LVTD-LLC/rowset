import hashlib
import os
import stat
import subprocess
import tarfile
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).parents[2]
_MEDIA_MOUNTS = {
    "media_data:/app/media",
    "private_media_data:/app/private_media",
}
_PRODUCTION_SERVICES = {"db", "redis", "backend", "workers"}


def _production_compose():
    return yaml.safe_load((_REPO_ROOT / "docker-compose-prod.yml").read_text())


def test_production_compose_persists_media_in_shared_named_volumes():
    compose = _production_compose()

    assert _MEDIA_MOUNTS <= set(compose["services"]["backend"]["volumes"])
    assert _MEDIA_MOUNTS <= set(compose["services"]["workers"]["volumes"])
    assert {"media_data", "private_media_data"} <= set(compose["volumes"])


def test_production_compose_applies_restart_and_bounded_logging_to_every_service():
    compose = _production_compose()

    assert set(compose["services"]) == _PRODUCTION_SERVICES
    for service in compose["services"].values():
        assert service["restart"] == "unless-stopped"
        assert service["logging"] == {
            "driver": "json-file",
            "options": {"max-size": "10m", "max-file": "3"},
        }


def test_production_compose_waits_for_authenticated_redis_health():
    compose = _production_compose()
    redis = compose["services"]["redis"]

    assert redis["command"] == [
        "sh",
        "-c",
        'test -n "$$REDIS_PASSWORD" || { echo "REDIS_PASSWORD is required" >&2; exit 1; }; '
        'exec redis-server --requirepass "$$REDIS_PASSWORD"',
    ]
    assert redis["healthcheck"]["test"] == [
        "CMD-SHELL",
        'test -n "$$REDIS_PASSWORD" && REDISCLI_AUTH="$$REDIS_PASSWORD" redis-cli ping',
    ]
    assert redis["healthcheck"] == {
        "test": [
            "CMD-SHELL",
            'test -n "$$REDIS_PASSWORD" && REDISCLI_AUTH="$$REDIS_PASSWORD" redis-cli ping',
        ],
        "interval": "5s",
        "timeout": "3s",
        "retries": 12,
        "start_period": "30s",
    }
    for service_name in ("backend", "workers"):
        assert compose["services"][service_name]["depends_on"] == {
            "db": {"condition": "service_healthy"},
            "redis": {"condition": "service_healthy"},
        }


def test_production_compose_rejects_an_empty_redis_password():
    compose = _production_compose()
    redis = compose["services"]["redis"]

    for command in (redis["command"][2], redis["healthcheck"]["test"][1]):
        result = subprocess.run(
            ["sh", "-c", command.replace("$$", "$")],
            env={**os.environ, "REDIS_PASSWORD": ""},
            capture_output=True,
            text=True,
        )

        assert result.returncode != 0


def test_local_ci_validates_rendered_production_compose():
    ci_local = (_REPO_ROOT / "scripts/ci-local.sh").read_text()

    assert (
        'run_step "Production Compose config" ./deployment/verify-production-compose.sh' in ci_local
    )


def test_self_hosting_docs_explain_compose_recovery_logging_and_safe_diagnostics():
    self_hosting = (_REPO_ROOT / "SELF_HOSTING.md").read_text()

    assert "restart: unless-stopped" in self_hosting
    assert "host restart" in self_hosting
    assert "30 MB per service" in self_hosting
    assert "120 MB across the four-service stack" in self_hosting
    assert "config --no-env-resolution --no-interpolate" in self_hosting
    assert "Do not share `.env`" in self_hosting


def test_local_media_backup_archives_both_paths_with_restricted_permissions(tmp_path):
    source_archive = tmp_path / "source.tar.gz"
    payload = tmp_path / "payload.txt"
    payload.write_text("durable media")
    with tarfile.open(source_archive, "w:gz") as archive:
        archive.add(payload, arcname="media/public.txt")
        archive.add(payload, arcname="private_media/private.txt")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker_log = tmp_path / "docker.log"
    fake_docker = fake_bin / "docker"
    fake_docker.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$*" > "$FAKE_DOCKER_LOG"\ncat "$FAKE_ARCHIVE"\n'
    )
    fake_docker.chmod(0o755)

    backup_dir = tmp_path / "backups"
    environment = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "FAKE_ARCHIVE": str(source_archive),
        "FAKE_DOCKER_LOG": str(docker_log),
        "ROWSET_BACKUP_TIMESTAMP": "20260714T120000Z",
    }
    subprocess.run(
        [str(_REPO_ROOT / "deployment/self-host/backup-local-media.sh"), str(backup_dir)],
        cwd=_REPO_ROOT,
        env=environment,
        check=True,
    )

    archive = backup_dir / "rowset-local-media-20260714T120000Z.tar.gz"
    checksum = Path(f"{archive}.sha256")
    assert stat.S_IMODE(archive.stat().st_mode) == 0o600
    assert stat.S_IMODE(checksum.stat().st_mode) == 0o600
    assert hashlib.sha256(archive.read_bytes()).hexdigest() in checksum.read_text()

    docker_command = docker_log.read_text()
    assert (
        "compose -f docker-compose-prod.yml -p rowset run --rm --no-deps -T "
        "--entrypoint python backend -c" in docker_command
    )
    assert "/app/media" in docker_command
    assert "/app/private_media" in docker_command
