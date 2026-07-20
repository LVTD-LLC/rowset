#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
root=$(CDPATH= cd -- "$script_dir/../.." && pwd)

if test "$#" -lt 1 || test "$#" -gt 2 || test "$1" != "--confirm-destroy-isolated-stack"; then
    printf 'Usage: %s --confirm-destroy-isolated-stack [ENV_FILE]\n' "$0" >&2
    exit 2
fi

environment_file=${2:-"$root/.env"}
environment_directory=$(CDPATH= cd -- "$(dirname -- "$environment_file")" && pwd)
environment_file="$environment_directory/$(basename -- "$environment_file")"
# shellcheck source=deployment/self-host/env-lib.sh
. "$script_dir/env-lib.sh"
validate_environment_contract "$environment_file"
configure_compose_profiles
drill_services="db redis backend workers"
if test "$CFG_ROWSET_VECTOR_SEARCH_ENABLED" = "True"; then
    drill_services="db redis qdrant backend workers"
fi
unset ROWSET_IMAGE ROWSET_DOMAIN POSTGRES_USER QDRANT_API_KEY ROWSET_VECTOR_SEARCH_ENABLED
export ROWSET_ENV_FILE=$environment_file
project_name="rowset-restore-drill-$$"
compose_file=${COMPOSE_FILE:-"$root/docker-compose-prod.yml"}
work_dir=$(mktemp -d)
backup_root="$work_dir/backups"
expected="$work_dir/expected.json"
backup_environment_file="$work_dir/local-backup.env"
write_local_only_backup_environment "$environment_file" "$backup_environment_file"

compose() {
    docker compose --env-file "$environment_file" -f "$compose_file" -p "$project_name" "$@"
}

cleanup() {
    compose down -v --remove-orphans >/dev/null 2>&1 || true
    rm -rf "$work_dir"
}
trap cleanup EXIT HUP INT TERM

wait_for_backend() {
    attempt=1
    while test "$attempt" -le 120; do
        if compose exec -T backend python manage.py check >/dev/null 2>&1; then
            return
        fi
        sleep 1
        attempt=$((attempt + 1))
    done
    printf 'Isolated backend did not become ready.\n' >&2
    compose logs --tail 100 backend >&2 || true
    exit 1
}

printf 'Starting isolated restore-drill stack.\n'
compose up -d $drill_services >/dev/null
wait_for_backend
compose exec -T -e ROWSET_RESTORE_DRILL=1 -e ROWSET_ASSET_S3_ENDPOINT_URL= backend \
    python manage.py restore_drill_state seed > "$expected"

backup_output=$(
    COMPOSE_PROJECT_NAME="$project_name" \
        "$script_dir/backup.sh" "$backup_root" "$backup_environment_file"
)
backup_dir=$(printf '%s\n' "$backup_output" | tail -1)

# This is intentionally destructive, but the unique Compose project keeps production out of scope.
compose down -v --remove-orphans >/dev/null
compose up -d db >/dev/null
COMPOSE_PROJECT_NAME="$project_name" \
    "$script_dir/restore.sh" --confirm-destroy-data "$backup_dir" "$environment_file"
compose up -d $drill_services >/dev/null
wait_for_backend
compose exec -T -e ROWSET_RESTORE_DRILL=1 -e ROWSET_ASSET_S3_ENDPOINT_URL= backend \
    python manage.py restore_drill_state verify < "$expected"

printf 'Restore drill passed: users, datasets, rows, relationships, and assets survived.\n'
