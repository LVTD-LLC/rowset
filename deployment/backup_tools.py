from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tarfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import BinaryIO

BACKUP_FORMAT_VERSION = 1
BACKUP_FILES = ("database.dump", "media.tar.gz", "private-media.tar.gz", "manifest.json")
MEDIA_PATHS = {
    "media": (Path("/app/media"), "media"),
    "private-media": (Path("/app/private_media"), "private_media"),
}
BACKUP_NAME_PATTERN = re.compile(r"rowset-backup-(\d{8}T\d{6}Z)")


class BackupIntegrityError(ValueError):
    pass


def _backup_id_from_name(name: str) -> str:
    match = BACKUP_NAME_PATTERN.fullmatch(name)
    if match is None:
        raise BackupIntegrityError("Backup has an invalid name")
    backup_id = match.group(1)
    try:
        datetime.strptime(backup_id, "%Y%m%dT%H%M%SZ")
    except ValueError as exc:
        raise BackupIntegrityError("Backup has an invalid timestamp") from exc
    return backup_id


@dataclass(frozen=True)
class S3BackupConfig:
    endpoint_url: str
    bucket: str
    access_key_id: str
    secret_access_key: str
    region: str = "auto"
    prefix: str = "rowset"

    @classmethod
    def from_mapping(cls, values: Mapping[str, str]) -> S3BackupConfig | None:
        names = {
            "endpoint_url": "ROWSET_BACKUP_S3_ENDPOINT_URL",
            "bucket": "ROWSET_BACKUP_S3_BUCKET",
            "access_key_id": "ROWSET_BACKUP_S3_ACCESS_KEY_ID",
            "secret_access_key": "ROWSET_BACKUP_S3_SECRET_ACCESS_KEY",
        }
        configured = {field: values.get(name, "").strip() for field, name in names.items()}
        if not any(configured.values()):
            return None
        missing = [names[field] for field, value in configured.items() if not value]
        if missing:
            raise ValueError(f"Missing required S3 backup setting: {', '.join(missing)}")
        return cls(
            **configured,
            region=values.get("ROWSET_BACKUP_S3_REGION", "auto").strip() or "auto",
            prefix=values.get("ROWSET_BACKUP_S3_PREFIX", "rowset").strip().strip("/") or "rowset",
        )

    def object_key(self, backup_id: str) -> str:
        return f"{self.prefix}/rowset-backup-{backup_id}.tar.gz"

    def validate_object_key(self, key: str) -> str:
        expected_prefix = f"{self.prefix}/"
        if not key.startswith(expected_prefix):
            raise BackupIntegrityError("S3 backup key is outside the configured prefix")
        name = key.removeprefix(expected_prefix)
        if "/" in name or not name.endswith(".tar.gz"):
            raise BackupIntegrityError("S3 backup key has an invalid name")
        return _backup_id_from_name(name.removesuffix(".tar.gz"))

    def client(self):
        import boto3

        return boto3.client(
            "s3",
            endpoint_url=self.endpoint_url,
            aws_access_key_id=self.access_key_id,
            aws_secret_access_key=self.secret_access_key,
            region_name=self.region,
        )


def build_manifest(*, backup_id: str, rowset_image: str, postgres_version: str) -> dict:
    return {
        "format": "rowset-coordinated-backup",
        "format_version": BACKUP_FORMAT_VERSION,
        "backup_id": backup_id,
        "created_at": datetime.strptime(backup_id, "%Y%m%dT%H%M%SZ")
        .replace(tzinfo=UTC)
        .isoformat(),
        "rowset_image": rowset_image,
        "postgres_version": postgres_version,
        "database_format": "postgresql-custom",
        "media_archives": {
            "media": "media.tar.gz",
            "private_media": "private-media.tar.gz",
        },
        "consistency": "application-writes-paused",
    }


def create_media_archive(source: Path, archive_root: str, output: BinaryIO) -> None:
    source.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=output, mode="w|gz") as archive:
        archive.add(source, arcname=archive_root, recursive=True)


def verify_media_archive(source: BinaryIO, expected_root: str) -> None:
    with tarfile.open(fileobj=source, mode="r:gz") as archive:
        _validated_members(archive, expected_root)


def _validated_members(archive: tarfile.TarFile, expected_root: str) -> list[tarfile.TarInfo]:
    members = archive.getmembers()
    for member in members:
        path = PurePosixPath(member.name)
        if path.is_absolute() or ".." in path.parts:
            raise BackupIntegrityError(f"Unsafe archive member: {member.name}")
        if not path.parts or path.parts[0] != expected_root:
            raise BackupIntegrityError(f"Unexpected archive root: {member.name}")
        if member.issym() or member.islnk() or not (member.isdir() or member.isfile()):
            raise BackupIntegrityError(f"Unsupported archive member: {member.name}")
    return members


def _extract_validated_members(
    archive: tarfile.TarFile,
    members: list[tarfile.TarInfo],
    destination: Path,
    archive_root: str,
) -> None:
    for member in members:
        relative = PurePosixPath(member.name).relative_to(archive_root)
        if not relative.parts:
            continue
        target = destination.joinpath(*relative.parts)
        if member.isdir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        extracted = archive.extractfile(member)
        if extracted is None:
            raise BackupIntegrityError(f"Could not read archive member: {member.name}")
        with target.open("wb") as output:
            shutil.copyfileobj(extracted, output)


def restore_media_archive(source: BinaryIO, destination: Path, expected_root: str) -> None:
    with tarfile.open(fileobj=source, mode="r:gz") as archive:
        members = _validated_members(archive, expected_root)
        if destination.exists():
            for child in destination.iterdir():
                shutil.rmtree(child) if child.is_dir() else child.unlink()
        destination.mkdir(parents=True, exist_ok=True)
        _extract_validated_members(archive, members, destination, expected_root)


def restore_backup_bundle(source: BinaryIO, destination: Path) -> str:
    with tarfile.open(fileobj=source, mode="r:gz") as archive:
        members = archive.getmembers()
        roots = {PurePosixPath(member.name).parts[0] for member in members if member.name}
        if len(roots) != 1:
            raise BackupIntegrityError("Bundle must contain exactly one backup directory")
        backup_name = roots.pop()
        _backup_id_from_name(backup_name)
        members = _validated_members(archive, backup_name)
        backup_destination = destination / backup_name
        if backup_destination.exists():
            raise BackupIntegrityError("Bundle destination already exists")
        backup_destination.mkdir(parents=True)
        _extract_validated_members(archive, members, backup_destination, backup_name)
        return backup_name


def _read_checksums(path: Path) -> dict[str, str]:
    checksums: dict[str, str] = {}
    for line in path.read_text().splitlines():
        parts = line.split()
        if len(parts) != 2 or len(parts[0]) != 64:
            raise BackupIntegrityError("SHA256SUMS contains an invalid entry")
        checksum, name = parts
        if name not in BACKUP_FILES or name in checksums:
            raise BackupIntegrityError(f"SHA256SUMS contains an unexpected entry: {name}")
        checksums[name] = checksum.lower()
    if set(checksums) != set(BACKUP_FILES):
        raise BackupIntegrityError("SHA256SUMS does not cover every required backup file")
    return checksums


def _validate_manifest(path: Path) -> dict:
    try:
        manifest = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        raise BackupIntegrityError("manifest.json is invalid") from exc
    if manifest.get("format") != "rowset-coordinated-backup":
        raise BackupIntegrityError("Unsupported backup format")
    if manifest.get("format_version") != BACKUP_FORMAT_VERSION:
        raise BackupIntegrityError("Unsupported backup format version")
    backup_id = manifest.get("backup_id", "")
    try:
        datetime.strptime(backup_id, "%Y%m%dT%H%M%SZ")
    except (TypeError, ValueError) as exc:
        raise BackupIntegrityError("Manifest backup_id is invalid") from exc
    return manifest


def verify_backup_directory(backup: Path) -> dict:
    if not backup.is_dir():
        raise BackupIntegrityError(f"Backup directory does not exist: {backup}")
    checksum_path = backup / "SHA256SUMS"
    if not checksum_path.is_file():
        raise BackupIntegrityError("SHA256SUMS is missing")
    checksums = _read_checksums(checksum_path)
    for name, expected in checksums.items():
        path = backup / name
        if not path.is_file():
            raise BackupIntegrityError(f"Required backup file is missing: {name}")
        with path.open("rb") as source:
            actual = hashlib.file_digest(source, "sha256").hexdigest()
        if actual != expected:
            raise BackupIntegrityError(f"Checksum mismatch for {name}")
    return _validate_manifest(backup / "manifest.json")


def prune_local_backups(
    backup_root: Path,
    *,
    retention_days: int,
    now: datetime | None = None,
) -> list[Path]:
    if retention_days < 1:
        raise ValueError("retention_days must be at least 1")
    cutoff = (now or datetime.now(UTC)) - timedelta(days=retention_days)
    removed: list[Path] = []
    for candidate in sorted(backup_root.glob("rowset-backup-*")):
        if not candidate.is_dir() or not (candidate / "SHA256SUMS").is_file():
            continue
        try:
            created_at = datetime.strptime(
                candidate.name.removeprefix("rowset-backup-"), "%Y%m%dT%H%M%SZ"
            ).replace(tzinfo=UTC)
        except ValueError:
            continue
        if created_at < cutoff:
            shutil.rmtree(candidate)
            removed.append(candidate)
    return removed


def _upload_s3(config: S3BackupConfig, backup_id: str) -> None:
    key = config.object_key(backup_id)
    config.client().upload_fileobj(
        sys.stdin.buffer,
        config.bucket,
        key,
        ExtraArgs={"ServerSideEncryption": "AES256"},
    )
    print(f"s3://{config.bucket}/{key}")


def _download_s3(config: S3BackupConfig, key: str) -> None:
    config.validate_object_key(key)
    config.client().download_fileobj(config.bucket, key, sys.stdout.buffer)


def _prune_s3(config: S3BackupConfig, retention_days: int) -> None:
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    client = config.client()
    paginator = client.get_paginator("list_objects_v2")
    pages = paginator.paginate(
        Bucket=config.bucket,
        Prefix=f"{config.prefix}/rowset-backup-",
    )
    for response in pages:
        expired = [
            {"Key": item["Key"]}
            for item in response.get("Contents", [])
            if item["LastModified"] < cutoff
        ]
        if expired:
            response = client.delete_objects(
                Bucket=config.bucket,
                Delete={"Objects": expired, "Quiet": True},
            )
            errors = response.get("Errors", [])
            if errors:
                failed_keys = ", ".join(error.get("Key", "<unknown>") for error in errors)
                raise RuntimeError(f"S3 retention failed for: {failed_keys}")


def _parse_args():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    media_parser = subparsers.add_parser("archive-media")
    media_parser.add_argument("kind", choices=MEDIA_PATHS)
    restore_parser = subparsers.add_parser("restore-media")
    restore_parser.add_argument("kind", choices=MEDIA_PATHS)
    bundle_parser = subparsers.add_parser("restore-bundle")
    bundle_parser.add_argument("path", type=Path)
    media_verify_parser = subparsers.add_parser("verify-media")
    media_verify_parser.add_argument("kind", choices=MEDIA_PATHS)
    verify_parser = subparsers.add_parser("verify-directory")
    verify_parser.add_argument("path", type=Path)
    manifest_parser = subparsers.add_parser("build-manifest")
    manifest_parser.add_argument("backup_id")
    manifest_parser.add_argument("rowset_image")
    manifest_parser.add_argument("postgres_version")
    prune_local_parser = subparsers.add_parser("prune-local")
    prune_local_parser.add_argument("path", type=Path)
    prune_local_parser.add_argument("retention_days", type=int)
    subparsers.add_parser("s3-status")
    upload_parser = subparsers.add_parser("s3-upload")
    upload_parser.add_argument("backup_id")
    download_parser = subparsers.add_parser("s3-download")
    download_parser.add_argument("object_key")
    prune_parser = subparsers.add_parser("s3-prune")
    prune_parser.add_argument("retention_days", type=int)
    return parser.parse_args()


def _run_local_command(args) -> bool:
    if args.command == "archive-media":
        path, root = MEDIA_PATHS[args.kind]
        create_media_archive(path, root, sys.stdout.buffer)
    elif args.command == "restore-media":
        path, root = MEDIA_PATHS[args.kind]
        restore_media_archive(sys.stdin.buffer, path, root)
    elif args.command == "restore-bundle":
        print(restore_backup_bundle(sys.stdin.buffer, args.path))
    elif args.command == "verify-media":
        _, root = MEDIA_PATHS[args.kind]
        verify_media_archive(sys.stdin.buffer, root)
    elif args.command == "verify-directory":
        print(json.dumps(verify_backup_directory(args.path), sort_keys=True))
    elif args.command == "build-manifest":
        print(
            json.dumps(
                build_manifest(
                    backup_id=args.backup_id,
                    rowset_image=args.rowset_image,
                    postgres_version=args.postgres_version,
                ),
                sort_keys=True,
            )
        )
    elif args.command == "prune-local":
        prune_local_backups(args.path, retention_days=args.retention_days)
    else:
        return False
    return True


def main() -> None:
    args = _parse_args()
    if _run_local_command(args):
        return
    config = S3BackupConfig.from_mapping(os.environ)
    if args.command == "s3-status":
        print("enabled" if config else "disabled")
        return
    if config is None:
        raise SystemExit("S3 backup configuration is not enabled")
    if args.command == "s3-upload":
        _upload_s3(config, args.backup_id)
    elif args.command == "s3-download":
        _download_s3(config, args.object_key)
    else:
        _prune_s3(config, args.retention_days)


if __name__ == "__main__":
    main()
