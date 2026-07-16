#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
root=$(CDPATH= cd -- "$script_dir/../.." && pwd)

if test "$#" -gt 2; then
    printf 'Usage: %s [BACKUP_DIR] [ENV_FILE]\n' "$0" >&2
    exit 2
fi

backup_root=${1:-/var/backups/rowset}
environment_file=${2:-"$root/.env"}
environment_directory=$(CDPATH= cd -- "$(dirname -- "$environment_file")" && pwd)
environment_file="$environment_directory/$(basename -- "$environment_file")"

# shellcheck source=deployment/self-host/env-lib.sh
. "$script_dir/env-lib.sh"
validate_environment_contract "$environment_file"
unset ROWSET_IMAGE ROWSET_DOMAIN POSTGRES_USER
export ROWSET_ENV_FILE=$environment_file

retention_days=$(environment_file_value ROWSET_BACKUP_RETENTION_DAYS "$environment_file" || true)
retention_days=${ROWSET_BACKUP_RETENTION_DAYS:-${retention_days:-7}}
case "$retention_days" in
    ""|*[!0-9]*|0) fail ROWSET_BACKUP_RETENTION_DAYS "must be a positive integer" ;;
esac

timestamp=${ROWSET_BACKUP_TIMESTAMP:-$(date -u +%Y%m%dT%H%M%SZ)}
printf '%s\n' "$timestamp" | grep -Eq '^[0-9]{8}T[0-9]{6}Z$' || \
    fail ROWSET_BACKUP_TIMESTAMP "must use YYYYMMDDTHHMMSSZ"

compose_file=${COMPOSE_FILE:-"$root/docker-compose-prod.yml"}
project_name=${COMPOSE_PROJECT_NAME:-rowset}
app_services="backend workers"
backup_root=$(mkdir -p "$backup_root" && CDPATH= cd -- "$backup_root" && pwd)
backup_dir="$backup_root/rowset-backup-$timestamp"
lock_file="$backup_root/.rowset-backup.lock"

umask 077
chmod 700 "$backup_root"
command -v flock >/dev/null 2>&1 || fail BACKUP "flock is required"
exec 9>"$lock_file"
chmod 600 "$lock_file"
if ! flock -n 9; then
    printf 'Another Rowset backup is already running: %s\n' "$lock_file" >&2
    exit 1
fi
paused=false
bundle=
cleanup() {
    if test "$paused" = true; then
        docker compose --env-file "$environment_file" -f "$compose_file" -p "$project_name" \
            unpause $app_services >/dev/null 2>&1 || true
    fi
    rm -rf "$backup_dir.tmp"
    test -z "$bundle" || rm -f "$bundle"
}
trap cleanup EXIT HUP INT TERM

mkdir "$backup_dir.tmp"
chmod 700 "$backup_dir.tmp"

compose() {
    docker compose --env-file "$environment_file" -f "$compose_file" -p "$project_name" "$@"
}

running_services=$(compose ps --services --status running)
for service in db $app_services; do
    printf '%s\n' "$running_services" | grep -Fxq "$service" || {
        printf 'Required service is not running: %s\n' "$service" >&2
        exit 1
    }
done
s3_status=$(compose run --rm --no-deps -T --entrypoint python backend \
    -m deployment.backup_tools s3-status)

# Pausing every writer makes the database and both local media snapshots one coordinated point.
paused=true
compose pause backend workers >/dev/null

compose exec -T db sh -c \
    'exec pg_dump -U "$POSTGRES_USER" --format=custom --compress=6 "$POSTGRES_DB"' \
    > "$backup_dir.tmp/database.dump"
compose run --rm --no-deps -T --entrypoint python backend \
    -m deployment.backup_tools archive-media media > "$backup_dir.tmp/media.tar.gz"
compose run --rm --no-deps -T --entrypoint python backend \
    -m deployment.backup_tools archive-media private-media \
    > "$backup_dir.tmp/private-media.tar.gz"

postgres_version=$(compose exec -T db sh -c \
    'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SHOW server_version"')
compose run --rm --no-deps -T --entrypoint python backend \
    -m deployment.backup_tools build-manifest \
    "$timestamp" "$CFG_ROWSET_IMAGE" "$postgres_version" > "$backup_dir.tmp/manifest.json"

checksum_file() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | awk '{print $1}'
    else
        shasum -a 256 "$1" | awk '{print $1}'
    fi
}

: > "$backup_dir.tmp/SHA256SUMS"
for name in database.dump media.tar.gz private-media.tar.gz manifest.json; do
    test -s "$backup_dir.tmp/$name" || fail BACKUP "generated $name is empty"
    printf '%s  %s\n' "$(checksum_file "$backup_dir.tmp/$name")" "$name" \
        >> "$backup_dir.tmp/SHA256SUMS"
    chmod 600 "$backup_dir.tmp/$name"
done
chmod 600 "$backup_dir.tmp/SHA256SUMS"
compose unpause $app_services >/dev/null
paused=false
"$script_dir/verify-backup.sh" "$backup_dir.tmp" "$environment_file" >/dev/null
test ! -e "$backup_dir" || fail BACKUP "backup already exists: $backup_dir"
mv "$backup_dir.tmp" "$backup_dir"

compose run --rm --no-deps -T -v "$backup_root:/backups" --entrypoint python backend \
    -m deployment.backup_tools prune-local /backups "$retention_days"

if test "$s3_status" = enabled; then
    bundle="$backup_root/rowset-backup-$timestamp.tar.gz"
    tar -C "$backup_root" -czf "$bundle" "rowset-backup-$timestamp"
    chmod 600 "$bundle"
    compose run --rm --no-deps -T --entrypoint python backend \
        -m deployment.backup_tools s3-upload "$timestamp" < "$bundle"
    rm -f "$bundle"
    bundle=
    compose run --rm --no-deps -T --entrypoint python backend \
        -m deployment.backup_tools s3-prune "$retention_days"
else
    printf '%s\n' \
        'WARNING: this backup exists only on the Rowset host and is not disaster recovery.' >&2
fi

printf '%s\n' "$backup_dir"
