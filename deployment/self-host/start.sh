#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
root=$(CDPATH= cd -- "$script_dir/../.." && pwd)

if test "$#" -gt 1; then
    printf 'Usage: %s [ENV_FILE]\n' "$0" >&2
    exit 2
fi

environment_file=${1:-"$root/.env"}
environment_directory=$(CDPATH= cd -- "$(dirname -- "$environment_file")" && pwd)
environment_file="$environment_directory/$(basename -- "$environment_file")"
"$script_dir/validate-env.sh" "$environment_file"

unset ROWSET_IMAGE ROWSET_DOMAIN POSTGRES_USER
export ROWSET_ENV_FILE=$environment_file
exec docker compose --env-file "$environment_file" -f "$root/docker-compose-prod.yml" -p rowset \
    up -d --remove-orphans
