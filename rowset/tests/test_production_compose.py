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


def _production_compose():
    return yaml.safe_load((_REPO_ROOT / "docker-compose-prod.yml").read_text())


def test_production_compose_persists_media_in_shared_named_volumes():
    compose = _production_compose()

    assert _MEDIA_MOUNTS <= set(compose["services"]["backend"]["volumes"])
    assert _MEDIA_MOUNTS <= set(compose["services"]["workers"]["volumes"])
    assert {"media_data", "private_media_data"} <= set(compose["volumes"])


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
