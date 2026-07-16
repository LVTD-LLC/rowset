#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
root=$(CDPATH= cd -- "$script_dir/../.." && pwd)
release_file=${ROWSET_RELEASE_FILE:-"$root/.rowset-release"}
environment_file=${ROWSET_ENV_FILE:-"$root/.env"}

# shellcheck source=deployment/self-host/env-lib.sh
. "$script_dir/env-lib.sh"

test -f "$release_file" || {
    printf 'Installed release metadata is missing: %s\n' "$release_file" >&2
    exit 1
}

load_release_metadata "$release_file"
configured_image="not initialized"
if test -f "$environment_file"; then
    configured_image=$(awk -F= '$1 == "ROWSET_IMAGE" { print substr($0, 14); found = 1; exit } END { exit !found }' "$environment_file") || {
        configured_image="missing from environment"
    }
fi

printf 'Version: %s\n' "$RELEASE_VERSION"
printf 'Commit: %s\n' "$RELEASE_COMMIT"
printf 'Image: %s\n' "$RELEASE_IMAGE"
printf 'Digest: %s\n' "$RELEASE_DIGEST"
printf 'Configured image: %s\n' "$configured_image"
