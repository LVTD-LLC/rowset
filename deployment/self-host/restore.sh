#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
root=$(CDPATH= cd -- "$script_dir/../.." && pwd)

if test "$#" -lt 2 || test "$#" -gt 3 || test "$1" != "--confirm-destroy-data"; then
    printf 'Usage: %s --confirm-destroy-data BACKUP_DIR_OR_S3_URI [ENV_FILE]\n' "$0" >&2
    exit 2
fi

source=$2
environment_file=${3:-"$root/.env"}
environment_directory=$(CDPATH= cd -- "$(dirname -- "$environment_file")" && pwd)
environment_file="$environment_directory/$(basename -- "$environment_file")"
compose_file=${COMPOSE_FILE:-"$root/docker-compose-prod.yml"}
project_name=${COMPOSE_PROJECT_NAME:-rowset}
temporary_root=
running_services=
stopped=false
destructive_started=false

# shellcheck source=deployment/self-host/env-lib.sh
. "$script_dir/env-lib.sh"
validate_environment_contract "$environment_file"
unset ROWSET_IMAGE ROWSET_DOMAIN POSTGRES_USER
export ROWSET_ENV_FILE=$environment_file

compose() {
    docker compose --env-file "$environment_file" -f "$compose_file" -p "$project_name" "$@"
}

cleanup() {
    if test "$stopped" = true && test -n "$running_services"; then
        if test "$destructive_started" = false; then
            compose up -d $running_services >/dev/null 2>&1 || true
        else
            compose stop caddy backend workers >/dev/null 2>&1 || true
            echo "Restore failed after data replacement began; application services remain stopped." >&2
        fi
    fi
    test -z "$temporary_root" || rm -rf "$temporary_root"
}
trap cleanup EXIT HUP INT TERM

case "$source" in
    s3://*)
        configured_bucket=$(environment_file_value ROWSET_BACKUP_S3_BUCKET "$environment_file" || true)
        bucket_and_key=${source#s3://}
        bucket=${bucket_and_key%%/*}
        key=${bucket_and_key#*/}
        test -n "$configured_bucket" && test "$bucket" = "$configured_bucket" || \
            fail BACKUP_SOURCE "S3 bucket does not match ROWSET_BACKUP_S3_BUCKET"
        temporary_root=$(mktemp -d)
        compose run --rm --no-deps -T --entrypoint python backend \
            -m deployment.backup_tools s3-download "$key" > "$temporary_root/backup.tar.gz"
        source="$temporary_root/backup.tar.gz"
        ;;
esac

case "$source" in
    *.tar.gz)
        test -f "$source" || fail BACKUP_SOURCE "bundle does not exist"
        test -n "$temporary_root" || temporary_root=$(mktemp -d)
        backup_name=$(compose run --rm --no-deps -T -v "$temporary_root:/restore" \
            --entrypoint python backend \
            -m deployment.backup_tools restore-bundle /restore < "$source")
        backup_dir="$temporary_root/$backup_name"
        ;;
    *) backup_dir=$source ;;
esac

test -n "${backup_dir:-}" || fail BACKUP_SOURCE "bundle has no Rowset backup directory"
"$script_dir/verify-backup.sh" "$backup_dir" "$environment_file"

running_services=$(compose ps --services --status running | tr '\n' ' ')
test -n "$running_services" || fail STACK "no Rowset services are running"
stopped=true
compose stop caddy backend workers >/dev/null

destructive_started=true
compose exec -T db sh -c \
    'dropdb --force --if-exists -U "$POSTGRES_USER" "$POSTGRES_DB" && createdb -U "$POSTGRES_USER" "$POSTGRES_DB"'
compose exec -T db sh -c \
    'exec pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --no-privileges --exit-on-error' \
    < "$backup_dir/database.dump"
compose run --rm --no-deps -T --entrypoint python backend \
    -m deployment.backup_tools restore-media media < "$backup_dir/media.tar.gz"
compose run --rm --no-deps -T --entrypoint python backend \
    -m deployment.backup_tools restore-media private-media \
    < "$backup_dir/private-media.tar.gz"

compose up -d $running_services >/dev/null
stopped=false
printf 'Restore complete from %s\n' "$backup_dir"
