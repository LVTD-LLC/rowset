#!/bin/sh
set -eu

backup_dir="${1:-./backups}"
compose_file="${COMPOSE_FILE:-docker-compose-prod.yml}"
project_name="${COMPOSE_PROJECT_NAME:-rowset}"
timestamp="${ROWSET_BACKUP_TIMESTAMP:-$(date -u +%Y%m%dT%H%M%SZ)}"
archive_name="rowset-local-media-${timestamp}.tar.gz"
archive_path="${backup_dir}/${archive_name}"

umask 077
mkdir -p "$backup_dir"
temporary_path="$(mktemp "${archive_path}.tmp.XXXXXX")"
trap 'rm -f "$temporary_path"' EXIT HUP INT TERM

docker compose -f "$compose_file" -p "$project_name" run --rm --no-deps -T \
    --entrypoint python backend -c '
import sys
import tarfile

paths = (("/app/media", "media"), ("/app/private_media", "private_media"))
with tarfile.open(fileobj=sys.stdout.buffer, mode="w|gz") as archive:
    for source, archive_name in paths:
        archive.add(source, arcname=archive_name)
' > "$temporary_path"

test -s "$temporary_path"
mv "$temporary_path" "$archive_path"
chmod 600 "$archive_path"

if command -v sha256sum >/dev/null 2>&1; then
    checksum="$(sha256sum "$archive_path" | awk '{print $1}')"
else
    checksum="$(shasum -a 256 "$archive_path" | awk '{print $1}')"
fi

printf '%s  %s\n' "$checksum" "$archive_name" > "${archive_path}.sha256"
chmod 600 "${archive_path}.sha256"

printf '%s\n' "$archive_path"
