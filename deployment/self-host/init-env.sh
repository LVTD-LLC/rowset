#!/bin/sh
set -eu

umask 077
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
root=$(CDPATH= cd -- "$script_dir/../.." && pwd)
template="$script_dir/env.example"

if test "$#" -gt 1; then
    printf 'Usage: %s [ENV_FILE]\n' "$0" >&2
    exit 2
fi

# shellcheck source=deployment/self-host/env-lib.sh
. "$script_dir/env-lib.sh"

destination=${1:-"$root/.env"}
temporary_file=
assignments_file=

cleanup() {
    if test -n "$temporary_file"; then
        rm -f "$temporary_file"
    fi
    if test -n "$assignments_file"; then
        rm -f "$assignments_file"
    fi
}
trap cleanup EXIT
trap 'cleanup; exit 1' HUP INT TERM

existing_value() {
    existing_key=$1
    existing_file=$2
    if test -n "$existing_file" && existing_result=$(environment_file_value "$existing_key" "$existing_file"); then
        if test -n "$existing_result"; then
            printf '%s' "$existing_result"
            return 0
        fi
    fi
    return 1
}

value_or_default() {
    value_key=$1
    existing_file=$2
    default_value=$3
    if resolved_value=$(existing_value "$value_key" "$existing_file"); then
        printf '%s' "$resolved_value"
    else
        printf '%s' "$default_value"
    fi
}

secret_or_generate() {
    secret_key=$1
    existing_file=$2
    direct_value=$3
    secret_path=$4

    if resolved_value=$(existing_value "$secret_key" "$existing_file"); then
        printf '%s' "$resolved_value"
        return
    fi
    if test -n "$direct_value" || test -n "$secret_path"; then
        resolve_environment_secret "$secret_key" "$direct_value" "$secret_path"
        return
    fi
    od -An -N48 -tx1 /dev/urandom | tr -d ' \n'
}

set_environment_assignment() {
    assignment_key=$1
    assignment_value=$2
    input_file=$3
    output_file=$4
    awk -v assignment_key="$assignment_key" -v assignment_value="$assignment_value" '
        {
            separator = index($0, "=")
            key = separator ? substr($0, 1, separator - 1) : ""
            if (key == assignment_key) {
                print assignment_key "=" assignment_value
                replaced = 1
            } else {
                print
            }
        }
        END {
            if (!replaced) {
                print assignment_key "=" assignment_value
            }
        }
    ' "$input_file" > "$output_file"
}

existing_file=
if test -e "$destination"; then
    validate_environment_file_structure "$destination"
    destination_owner=$(file_owner "$destination") || \
        fail ENV_FILE "owner cannot be read"
    test "$destination_owner" = "$(id -u)" || \
        fail ENV_FILE "must be owned by the invoking user"
    existing_file=$destination
fi

if resolved_value=$(existing_value ROWSET_IMAGE "$existing_file"); then
    init_rowset_image=$resolved_value
else
    init_rowset_image=$(required_environment_value ROWSET_IMAGE "${ROWSET_IMAGE:-}")
fi
if resolved_value=$(existing_value ROWSET_DOMAIN "$existing_file"); then
    init_rowset_domain=$resolved_value
else
    init_rowset_domain=$(required_environment_value ROWSET_DOMAIN "${ROWSET_DOMAIN:-}")
fi

init_environment=$(value_or_default ENVIRONMENT "$existing_file" prod)
init_debug=$(value_or_default DEBUG "$existing_file" off)
init_postgres_db=$(value_or_default POSTGRES_DB "$existing_file" rowset)
init_postgres_user=$(value_or_default POSTGRES_USER "$existing_file" rowset)
init_postgres_host=$(value_or_default POSTGRES_HOST "$existing_file" db)
init_postgres_port=$(value_or_default POSTGRES_PORT "$existing_file" 5432)
init_redis_host=$(value_or_default REDIS_HOST "$existing_file" redis)
init_redis_port=$(value_or_default REDIS_PORT "$existing_file" 6379)
init_secret_key=$(
    secret_or_generate SECRET_KEY "$existing_file" "${SECRET_KEY:-}" "${SECRET_KEY_FILE:-}"
)
init_postgres_password=$(
    secret_or_generate POSTGRES_PASSWORD "$existing_file" \
        "${POSTGRES_PASSWORD:-}" "${POSTGRES_PASSWORD_FILE:-}"
)
init_redis_password=$(
    secret_or_generate REDIS_PASSWORD "$existing_file" \
        "${REDIS_PASSWORD:-}" "${REDIS_PASSWORD_FILE:-}"
)

destination_dir=$(dirname -- "$destination")
test -d "$destination_dir" || fail ENV_FILE "parent directory does not exist"
temporary_file=$(mktemp "$destination_dir/.rowset-env.XXXXXX")
chmod 600 "$temporary_file"

if test -n "$existing_file"; then
    cp "$existing_file" "$temporary_file"
else
    cp "$template" "$temporary_file"
fi

assignments_file=$(mktemp "$destination_dir/.rowset-env-assignments.XXXXXX")
cp "$temporary_file" "$assignments_file"

set_assignment() {
    set_environment_assignment "$1" "$2" "$assignments_file" "$temporary_file"
    cp "$temporary_file" "$assignments_file"
}

set_assignment ROWSET_IMAGE "$init_rowset_image"
set_assignment ROWSET_DOMAIN "$init_rowset_domain"
set_assignment ENVIRONMENT "$init_environment"
set_assignment DEBUG "$init_debug"
set_assignment SECRET_KEY "$init_secret_key"
set_assignment POSTGRES_DB "$init_postgres_db"
set_assignment POSTGRES_USER "$init_postgres_user"
set_assignment POSTGRES_HOST "$init_postgres_host"
set_assignment POSTGRES_PORT "$init_postgres_port"
set_assignment POSTGRES_PASSWORD "$init_postgres_password"
set_assignment REDIS_HOST "$init_redis_host"
set_assignment REDIS_PORT "$init_redis_port"
set_assignment REDIS_PASSWORD "$init_redis_password"

rm -f "$assignments_file"
assignments_file=
chmod 600 "$temporary_file"
"$script_dir/validate-env.sh" "$temporary_file" >/dev/null
mv "$temporary_file" "$destination"
temporary_file=

printf 'Production environment initialized.\n'
