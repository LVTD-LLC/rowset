import hashlib
import io
import json
import os
import subprocess
import tarfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from deployment.backup_tools import (
    BackupIntegrityError,
    S3BackupConfig,
    _download_s3,
    _prune_s3,
    _upload_s3,
    build_manifest,
    create_media_archive,
    prune_local_backups,
    restore_backup_bundle,
    restore_media_archive,
    verify_backup_directory,
)


def test_media_archive_round_trip_replaces_existing_files(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "nested").mkdir()
    (source / "nested" / "asset.bin").write_bytes(b"restored asset")

    archive = io.BytesIO()
    create_media_archive(source, "media", archive)

    destination = tmp_path / "destination"
    destination.mkdir()
    (destination / "stale.txt").write_text("must disappear")
    archive.seek(0)
    restore_media_archive(archive, destination, "media")

    assert not (destination / "stale.txt").exists()
    assert (destination / "nested" / "asset.bin").read_bytes() == b"restored asset"


@pytest.mark.parametrize(
    "member_name",
    ["../escape", "/absolute/path", "media/../../escape", "private_media/file"],
)
def test_media_restore_rejects_unsafe_or_wrong_root_members(tmp_path, member_name):
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w:gz") as bundle:
        info = tarfile.TarInfo(member_name)
        payload = b"unsafe"
        info.size = len(payload)
        bundle.addfile(info, io.BytesIO(payload))
    archive.seek(0)

    with pytest.raises(BackupIntegrityError):
        restore_media_archive(archive, tmp_path / "destination", "media")


def test_backup_bundle_round_trip_rejects_links_and_extra_roots(tmp_path):
    bundle = io.BytesIO()
    with tarfile.open(fileobj=bundle, mode="w:gz") as archive:
        payload = b"backup"
        info = tarfile.TarInfo("rowset-backup-20260716T120000Z/database.dump")
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))
    bundle.seek(0)

    name = restore_backup_bundle(bundle, tmp_path)

    assert name == "rowset-backup-20260716T120000Z"
    assert (tmp_path / name / "database.dump").read_bytes() == b"backup"

    for unsafe_name, link_name in (
        ("rowset-backup-20260716T120001Z/link", "../../escape"),
        ("another-root/link", "target"),
    ):
        unsafe = io.BytesIO()
        with tarfile.open(fileobj=unsafe, mode="w:gz") as archive:
            info = tarfile.TarInfo(unsafe_name)
            info.type = tarfile.SYMTYPE
            info.linkname = link_name
            archive.addfile(info)
        unsafe.seek(0)
        with pytest.raises(BackupIntegrityError):
            restore_backup_bundle(unsafe, tmp_path / "unsafe")

    multiple_roots = io.BytesIO()
    with tarfile.open(fileobj=multiple_roots, mode="w:gz") as archive:
        for name in (
            "rowset-backup-20260716T120002Z/database.dump",
            "unexpected/file",
        ):
            info = tarfile.TarInfo(name)
            info.size = 1
            archive.addfile(info, io.BytesIO(b"x"))
    multiple_roots.seek(0)
    with pytest.raises(BackupIntegrityError, match="exactly one"):
        restore_backup_bundle(multiple_roots, tmp_path / "multiple")


def test_manifest_and_checksums_detect_corruption(tmp_path):
    backup = tmp_path / "rowset-backup-20260716T120000Z"
    backup.mkdir()
    payloads = {
        "database.dump": b"postgres-custom-dump",
        "media.tar.gz": b"public-media",
        "private-media.tar.gz": b"private-media",
    }
    for name, payload in payloads.items():
        (backup / name).write_bytes(payload)

    manifest = build_manifest(
        backup_id="20260716T120000Z",
        rowset_image="ghcr.io/lvtd-llc/rowset:v1.2.3",
        postgres_version="17.5",
    )
    (backup / "manifest.json").write_text(json.dumps(manifest, sort_keys=True) + "\n")
    checksum_lines = []
    for name in (*payloads, "manifest.json"):
        checksum = hashlib.sha256((backup / name).read_bytes()).hexdigest()
        checksum_lines.append(f"{checksum}  {name}")
    (backup / "SHA256SUMS").write_text("\n".join(checksum_lines) + "\n")

    verified = verify_backup_directory(backup)
    assert verified["format_version"] == 1
    assert verified["backup_id"] == "20260716T120000Z"

    (backup / "private-media.tar.gz").write_bytes(b"corrupt")
    with pytest.raises(BackupIntegrityError, match="private-media.tar.gz"):
        verify_backup_directory(backup)


def test_retention_prunes_only_expired_complete_backups(tmp_path):
    now = datetime(2026, 7, 16, 12, tzinfo=UTC)
    expired = tmp_path / "rowset-backup-20260701T120000Z"
    recent = tmp_path / "rowset-backup-20260715T120000Z"
    unrelated = tmp_path / "operator-notes"
    for path in (expired, recent, unrelated):
        path.mkdir()
    (expired / "SHA256SUMS").touch()
    (recent / "SHA256SUMS").touch()

    removed = prune_local_backups(tmp_path, retention_days=7, now=now)

    assert removed == [expired]
    assert not expired.exists()
    assert recent.exists()
    assert unrelated.exists()


def test_s3_backup_configuration_requires_complete_credentials():
    assert S3BackupConfig.from_mapping({}) is None
    assert (
        S3BackupConfig.from_mapping(
            {
                "ROWSET_BACKUP_S3_REGION": "auto",
                "ROWSET_BACKUP_S3_PREFIX": "rowset",
            }
        )
        is None
    )

    with pytest.raises(ValueError, match="ROWSET_BACKUP_S3_BUCKET"):
        S3BackupConfig.from_mapping({"ROWSET_BACKUP_S3_ENDPOINT_URL": "https://s3.example"})

    config = S3BackupConfig.from_mapping(
        {
            "ROWSET_BACKUP_S3_ENDPOINT_URL": "https://s3.example",
            "ROWSET_BACKUP_S3_BUCKET": "rowset-backups",
            "ROWSET_BACKUP_S3_ACCESS_KEY_ID": "access",
            "ROWSET_BACKUP_S3_SECRET_ACCESS_KEY": "secret",
            "ROWSET_BACKUP_S3_REGION": "auto",
            "ROWSET_BACKUP_S3_PREFIX": "production/rowset",
        }
    )

    assert config.bucket == "rowset-backups"
    assert config.object_key("20260716T120000Z") == (
        "production/rowset/rowset-backup-20260716T120000Z.tar.gz"
    )

    assert (
        config.validate_object_key("production/rowset/rowset-backup-20260716T120000Z.tar.gz")
        == "20260716T120000Z"
    )
    for invalid_key in (
        "staging/rowset/rowset-backup-20260716T120000Z.tar.gz",
        "production/rowset/nested/rowset-backup-20260716T120000Z.tar.gz",
        "production/rowset/arbitrary.tar.gz",
        "production/rowset/rowset-backup-20261340T120000Z.tar.gz",
    ):
        with pytest.raises(BackupIntegrityError):
            config.validate_object_key(invalid_key)


def test_s3_upload_download_and_retention_propagate_failures(monkeypatch):
    class Paginator:
        def paginate(self, **kwargs):
            assert kwargs == {"Bucket": "backups", "Prefix": "prod/rowset-backup-"}
            return [
                {
                    "Contents": [
                        {
                            "Key": "prod/rowset-backup-20200101T000000Z.tar.gz",
                            "LastModified": datetime(2020, 1, 1, tzinfo=UTC),
                        }
                    ]
                },
                {"Contents": []},
            ]

    class Client:
        def __init__(self):
            self.upload = None
            self.download = None

        def upload_fileobj(self, source, bucket, key, ExtraArgs):
            self.upload = (source, bucket, key, ExtraArgs)

        def download_fileobj(self, bucket, key, output):
            self.download = (bucket, key, output)

        def get_paginator(self, name):
            assert name == "list_objects_v2"
            return Paginator()

        def delete_objects(self, **kwargs):
            assert kwargs["Bucket"] == "backups"
            return {"Errors": [{"Key": kwargs["Delete"]["Objects"][0]["Key"]}]}

    client = Client()
    config = S3BackupConfig("https://s3.example", "backups", "access", "secret", prefix="prod")
    monkeypatch.setattr(S3BackupConfig, "client", lambda self: client)
    monkeypatch.setattr("sys.stdin", type("Input", (), {"buffer": io.BytesIO(b"bundle")})())
    output = io.StringIO()
    output.buffer = io.BytesIO()
    monkeypatch.setattr("sys.stdout", output)

    _upload_s3(config, "20260716T120000Z")
    assert client.upload[1:] == (
        "backups",
        "prod/rowset-backup-20260716T120000Z.tar.gz",
        {"ServerSideEncryption": "AES256"},
    )
    _download_s3(config, "prod/rowset-backup-20260716T120000Z.tar.gz")
    assert client.download[:2] == (
        "backups",
        "prod/rowset-backup-20260716T120000Z.tar.gz",
    )
    with pytest.raises(RuntimeError, match="rowset-backup-20200101"):
        _prune_s3(config, 7)


def _write_backup_test_environment(tmp_path: Path) -> Path:
    environment = tmp_path / "rowset.env"
    environment.write_text(
        "\n".join(
            (
                "ROWSET_IMAGE=ghcr.io/example/rowset:v1.0.0",
                "ROWSET_DOMAIN=rowset.example.com",
                "ENVIRONMENT=prod",
                "DEBUG=off",
                f"SECRET_KEY={'a' * 50}",
                "POSTGRES_DB=rowset",
                "POSTGRES_USER=rowset",
                "POSTGRES_HOST=db",
                "POSTGRES_PORT=5432",
                f"POSTGRES_PASSWORD={'b' * 32}",
                "REDIS_HOST=redis",
                "REDIS_PORT=6379",
                f"REDIS_PASSWORD={'c' * 32}",
                "ROWSET_VECTOR_SEARCH_ENABLED=False",
                "QDRANT_URL=http://qdrant:6333",
                f"QDRANT_API_KEY={'d' * 32}",
                "OPENROUTER_API_KEY=",
                "ROWSET_BACKUP_RETENTION_DAYS=7",
            )
        )
        + "\n"
    )
    environment.chmod(0o600)
    return environment


def _write_fake_backup_commands(tmp_path: Path) -> tuple[Path, Path]:
    commands = tmp_path / "commands"
    commands.mkdir()
    log = tmp_path / "docker.log"
    docker = commands / "docker"
    docker.write_text(
        """#!/usr/bin/env python3
import io
import os
from pathlib import Path
import sys
import tarfile

from deployment.backup_tools import build_manifest, verify_backup_directory, verify_media_archive

args = sys.argv[1:]
joined = " ".join(args)
with open(os.environ["FAKE_DOCKER_LOG"], "a") as output:
    output.write(joined + "\\n")
if "ps --services --status running" in joined:
    print("db\\nbackend\\nworkers")
elif "s3-status" in joined:
    print("disabled")
elif " pause backend workers" in joined and os.environ.get("FAIL_PAUSE") == "1":
    raise SystemExit(1)
elif "pg_dump" in joined:
    sys.stdout.buffer.write(b"database dump")
elif "archive-media" in joined:
    root = "private_media" if "private-media" in joined else "media"
    with tarfile.open(fileobj=sys.stdout.buffer, mode="w|gz") as archive:
        info = tarfile.TarInfo(root + "/asset")
        info.size = 5
        archive.addfile(info, io.BytesIO(b"asset"))
elif "SHOW server_version" in joined:
    print("17.5")
elif "build-manifest" in joined:
    import json
    print(json.dumps(build_manifest(
        backup_id=args[-3], rowset_image=args[-2], postgres_version=args[-1]
    )))
elif "verify-directory" in joined:
    if os.environ.get("FAIL_VERIFY") == "1":
        raise SystemExit(1)
    mount = next(value for index, value in enumerate(args) if args[index - 1] == "-v")
    verify_backup_directory(Path(mount.split(":", 1)[0]))
elif "pg_restore" in joined and "--list" in joined:
    if sys.stdin.buffer.read() != b"database dump":
        raise SystemExit(1)
elif "verify-media" in joined:
    archive_root = "private_media" if "private-media" in joined else "media"
    verify_media_archive(sys.stdin.buffer, archive_root)
elif any(command in joined for command in (" pause ", " unpause ", "prune-local")):
    pass
else:
    print("unexpected fake Docker command: " + joined, file=sys.stderr)
    raise SystemExit(64)
"""
    )
    docker.chmod(0o755)
    flock = commands / "flock"
    flock.write_text("#!/bin/sh\nexit 0\n")
    flock.chmod(0o755)
    return commands, log


def test_restore_drill_backup_environment_disables_s3(tmp_path):
    root = Path(__file__).parents[2]
    source = _write_backup_test_environment(tmp_path)
    with source.open("a") as output:
        output.write(
            "ROWSET_BACKUP_S3_ENDPOINT_URL=https://prod-s3.example.invalid\n"
            "ROWSET_BACKUP_S3_BUCKET=prod-rowset-backups\n"
            "ROWSET_BACKUP_S3_ACCESS_KEY_ID=production-access\n"
            "ROWSET_BACKUP_S3_SECRET_ACCESS_KEY=production-secret\n"
            "ROWSET_BACKUP_S3_REGION=us-east-1\n"
            "ROWSET_BACKUP_S3_PREFIX=production/prefix\n"
        )
    destination = tmp_path / "local-backup.env"

    subprocess.run(
        [
            "sh",
            "-c",
            '. "$1"; write_local_only_backup_environment "$2" "$3"',
            "sh",
            root / "deployment/self-host/env-lib.sh",
            source,
            destination,
        ],
        check=True,
    )

    values = dict(
        line.split("=", 1)
        for line in destination.read_text().splitlines()
        if line and not line.startswith("#")
    )
    assert S3BackupConfig.from_mapping(values) is None
    assert values["POSTGRES_PASSWORD"] == "b" * 32
    assert destination.stat().st_mode & 0o777 == 0o600


def test_backup_script_executes_cleanup_and_publishes_only_after_verification(tmp_path):
    root = Path(__file__).parents[2]
    environment = _write_backup_test_environment(tmp_path)
    commands, log = _write_fake_backup_commands(tmp_path)
    backup_root = tmp_path / "backups"
    process_environment = {
        **os.environ,
        "PATH": f"{commands}:{os.environ['PATH']}",
        "FAKE_DOCKER_LOG": str(log),
        "PYTHONPATH": str(root),
        "ROWSET_BACKUP_TIMESTAMP": "20260716T120000Z",
    }

    result = subprocess.run(
        [root / "deployment/self-host/backup.sh", backup_root, environment],
        env=process_environment,
        text=True,
        capture_output=True,
    )

    published = backup_root / "rowset-backup-20260716T120000Z"
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith(str(published))
    assert published.is_dir()
    assert not (backup_root / "rowset-backup-20260716T120000Z.tmp").exists()
    assert "pause backend workers" in log.read_text()
    assert "unpause backend workers" in log.read_text()

    process_environment["ROWSET_BACKUP_TIMESTAMP"] = "20260716T120001Z"
    process_environment["FAIL_PAUSE"] = "1"
    failed = subprocess.run(
        [root / "deployment/self-host/backup.sh", backup_root, environment],
        env=process_environment,
        text=True,
        capture_output=True,
    )
    assert failed.returncode != 0
    assert not (backup_root / "rowset-backup-20260716T120001Z").exists()
    assert not (backup_root / "rowset-backup-20260716T120001Z.tmp").exists()
    assert log.read_text().count("unpause backend workers") == 2

    process_environment.pop("FAIL_PAUSE")
    process_environment["FAIL_VERIFY"] = "1"
    process_environment["ROWSET_BACKUP_TIMESTAMP"] = "20260716T120002Z"
    failed_verification = subprocess.run(
        [root / "deployment/self-host/backup.sh", backup_root, environment],
        env=process_environment,
        text=True,
        capture_output=True,
    )
    assert failed_verification.returncode != 0
    assert not (backup_root / "rowset-backup-20260716T120002Z").exists()
    assert not (backup_root / "rowset-backup-20260716T120002Z.tmp").exists()


def test_backup_commands_and_daily_timer_are_shipped():
    root = Path(__file__).parents[2]
    backup = (root / "deployment/self-host/backup.sh").read_text()
    restore = (root / "deployment/self-host/restore.sh").read_text()
    verify = (root / "deployment/self-host/verify-backup.sh").read_text()
    drill = (root / "deployment/self-host/restore-drill.sh").read_text()
    timer = (root / "deployment/self-host/systemd/rowset-backup.timer").read_text()
    service = (root / "deployment/self-host/systemd/rowset-backup.service").read_text()

    assert "pg_dump" in backup
    assert "pause backend workers" in backup
    assert "ROWSET_BACKUP_RETENTION_DAYS" in backup
    assert "build-manifest" in backup
    assert "s3-status" in backup
    assert "prune-local" in backup
    assert "flock -n" in backup
    assert backup.index("paused=true") < backup.index("compose pause backend workers")
    assert backup.index('verify-backup.sh" "$backup_dir.tmp"') < backup.index(
        'mv "$backup_dir.tmp" "$backup_dir"'
    )
    assert backup.index("prune-local") < backup.index("s3-upload")
    assert "ROWSET_BACKUP_APP_SERVICES" not in backup
    assert "pg_restore" in restore
    assert "--confirm-destroy-data" in restore
    assert "verify-backup.sh" in restore
    assert "application services remain stopped" in restore
    assert "find /qdrant/storage -mindepth 1 -delete" in restore
    assert "Qdrant was cleared because it is a rebuildable index" in restore
    destructive_stop = restore.index(
        "compose stop caddy backend workers", restore.index("running_services=$(compose")
    )
    assert restore.index("stopped=true") < destructive_stop
    assert "restore-bundle" in restore
    assert "verify-directory" in verify
    assert "down -v" in drill
    assert 'drill_services="db redis backend workers"' in drill
    assert 'drill_services="db redis qdrant backend workers"' in drill
    assert drill.count("compose up -d $drill_services") == 2
    assert "restore_drill_state seed" in drill
    assert "restore_drill_state verify" in drill
    assert "backup_output=$(" in drill
    assert "ROWSET_BACKUP_TIMESTAMP" not in drill
    assert 'backup.sh" "$backup_root" "$environment_file" | tail' not in drill
    assert "OnCalendar=daily" in timer
    assert "Persistent=true" in timer
    assert "UMask=0077" in service
    assert "TimeoutStartSec=6h" in service
    assert "runuser" in service
    assert "ROWSET_BACKUP_USER" in service
    assert "ROWSET_ASSET_S3_ENDPOINT_URL=" in drill
    assert 'backup.sh" "$backup_root" "$backup_environment_file"' in drill

    for script in (backup, restore, verify, drill):
        assert "export ROWSET_ENV_FILE=$environment_file" in script


def test_self_hosting_docs_state_local_backup_disaster_recovery_limit():
    root = Path(__file__).parents[2]
    docs = (root / "SELF_HOSTING.md").read_text()

    assert "deployment/self-host/backup.sh" in docs
    assert "deployment/self-host/restore.sh" in docs
    assert "deployment/self-host/verify-backup.sh" in docs
    assert "deployment/self-host/restore-drill.sh" in docs
    assert "not disaster recovery" in docs.lower()
    assert "ROWSET_BACKUP_S3_ENDPOINT_URL" in docs
