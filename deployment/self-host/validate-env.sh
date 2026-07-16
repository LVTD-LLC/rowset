#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
root=$(CDPATH= cd -- "$script_dir/../.." && pwd)

if test "$#" -gt 1; then
    printf 'Usage: %s [ENV_FILE|--environment]\n' "$0" >&2
    exit 2
fi

# shellcheck source=deployment/self-host/env-lib.sh
. "$script_dir/env-lib.sh"

environment_source=${1:-"$root/.env"}
validate_environment_contract "$environment_source"
printf 'Production environment is valid.\n'
