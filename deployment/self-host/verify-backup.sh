#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
root=$(CDPATH= cd -- "$script_dir/../.." && pwd)

if test "$#" -lt 1 || test "$#" -gt 2; then
    printf 'Usage: %s BACKUP_DIR [ENV_FILE]\n' "$0" >&2
    exit 2
fi

backup_dir=$(CDPATH= cd -- "$1" && pwd)
environment_file=${2:-"$root/.env"}
environment_directory=$(CDPATH= cd -- "$(dirname -- "$environment_file")" && pwd)
environment_file="$environment_directory/$(basename -- "$environment_file")"
"$script_dir/validate-env.sh" "$environment_file" >/dev/null
unset ROWSET_IMAGE ROWSET_DOMAIN POSTGRES_USER
export ROWSET_ENV_FILE=$environment_file
compose_file=${COMPOSE_FILE:-"$root/docker-compose-prod.yml"}
project_name=${COMPOSE_PROJECT_NAME:-rowset}

compose() {
    docker compose --env-file "$environment_file" -f "$compose_file" -p "$project_name" "$@"
}

compose run --rm --no-deps -T -v "$backup_dir:/backup:ro" --entrypoint python backend \
    -m deployment.backup_tools verify-directory /backup >/dev/null
compose exec -T db pg_restore --list < "$backup_dir/database.dump" >/dev/null
compose run --rm --no-deps -T --entrypoint python backend \
    -m deployment.backup_tools verify-media media < "$backup_dir/media.tar.gz"
compose run --rm --no-deps -T --entrypoint python backend \
    -m deployment.backup_tools verify-media private-media < "$backup_dir/private-media.tar.gz"

printf 'Backup integrity verified: %s\n' "$backup_dir"
