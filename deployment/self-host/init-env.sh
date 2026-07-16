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
destination_dir=$(dirname -- "$destination")
test -d "$destination_dir" || fail ENV_FILE "parent directory does not exist"
destination_dir=$(CDPATH= cd -- "$destination_dir" && pwd)
destination="$destination_dir/$(basename -- "$destination")"
temporary_file=
lock_directory="${destination}.lock"
lock_acquired=

cleanup() {
    if test -n "$temporary_file"; then
        rm -f "$temporary_file"
    fi
    if test -n "$lock_acquired"; then
        rmdir "$lock_directory" 2>/dev/null || true
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

existing_file=
mkdir "$lock_directory" 2>/dev/null || fail ENV_FILE "initialization is already running"
lock_acquired=1

if test -e "$destination"; then
    validate_environment_file_structure "$destination"
    destination_owner=$(file_owner "$destination") || \
        fail ENV_FILE "owner cannot be read"
    test "$destination_owner" = "$(id -u)" || \
        fail ENV_FILE "must be owned by the invoking user"
    existing_file=$destination
fi

if test -n "$existing_file" && "$script_dir/validate-env.sh" "$existing_file" >/dev/null 2>&1; then
    rmdir "$lock_directory"
    lock_acquired=
    printf 'Production environment initialized.\n'
    exit 0
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

temporary_file=$(mktemp "$destination_dir/.rowset-env.XXXXXX")
chmod 600 "$temporary_file"

if test -n "$existing_file"; then
    render_source=$existing_file
else
    render_source=$template
fi

seen_rowset_image=0
seen_rowset_domain=0
seen_environment=0
seen_debug=0
seen_secret_key=0
seen_postgres_db=0
seen_postgres_user=0
seen_postgres_host=0
seen_postgres_port=0
seen_postgres_password=0
seen_redis_host=0
seen_redis_port=0
seen_redis_password=0

while IFS= read -r line || test -n "$line"; do
    case "$line" in
        ROWSET_IMAGE=*) printf 'ROWSET_IMAGE=%s\n' "$init_rowset_image"; seen_rowset_image=1 ;;
        ROWSET_DOMAIN=*) printf 'ROWSET_DOMAIN=%s\n' "$init_rowset_domain"; seen_rowset_domain=1 ;;
        ENVIRONMENT=*) printf 'ENVIRONMENT=%s\n' "$init_environment"; seen_environment=1 ;;
        DEBUG=*) printf 'DEBUG=%s\n' "$init_debug"; seen_debug=1 ;;
        SECRET_KEY=*) printf 'SECRET_KEY=%s\n' "$init_secret_key"; seen_secret_key=1 ;;
        POSTGRES_DB=*) printf 'POSTGRES_DB=%s\n' "$init_postgres_db"; seen_postgres_db=1 ;;
        POSTGRES_USER=*) printf 'POSTGRES_USER=%s\n' "$init_postgres_user"; seen_postgres_user=1 ;;
        POSTGRES_HOST=*) printf 'POSTGRES_HOST=%s\n' "$init_postgres_host"; seen_postgres_host=1 ;;
        POSTGRES_PORT=*) printf 'POSTGRES_PORT=%s\n' "$init_postgres_port"; seen_postgres_port=1 ;;
        POSTGRES_PASSWORD=*)
            printf 'POSTGRES_PASSWORD=%s\n' "$init_postgres_password"
            seen_postgres_password=1
            ;;
        REDIS_HOST=*) printf 'REDIS_HOST=%s\n' "$init_redis_host"; seen_redis_host=1 ;;
        REDIS_PORT=*) printf 'REDIS_PORT=%s\n' "$init_redis_port"; seen_redis_port=1 ;;
        REDIS_PASSWORD=*) printf 'REDIS_PASSWORD=%s\n' "$init_redis_password"; seen_redis_password=1 ;;
        *) printf '%s\n' "$line" ;;
    esac
done < "$render_source" > "$temporary_file"

test "$seen_rowset_image" = 1 || printf 'ROWSET_IMAGE=%s\n' "$init_rowset_image" >> "$temporary_file"
test "$seen_rowset_domain" = 1 || printf 'ROWSET_DOMAIN=%s\n' "$init_rowset_domain" >> "$temporary_file"
test "$seen_environment" = 1 || printf 'ENVIRONMENT=%s\n' "$init_environment" >> "$temporary_file"
test "$seen_debug" = 1 || printf 'DEBUG=%s\n' "$init_debug" >> "$temporary_file"
test "$seen_secret_key" = 1 || printf 'SECRET_KEY=%s\n' "$init_secret_key" >> "$temporary_file"
test "$seen_postgres_db" = 1 || printf 'POSTGRES_DB=%s\n' "$init_postgres_db" >> "$temporary_file"
test "$seen_postgres_user" = 1 || printf 'POSTGRES_USER=%s\n' "$init_postgres_user" >> "$temporary_file"
test "$seen_postgres_host" = 1 || printf 'POSTGRES_HOST=%s\n' "$init_postgres_host" >> "$temporary_file"
test "$seen_postgres_port" = 1 || printf 'POSTGRES_PORT=%s\n' "$init_postgres_port" >> "$temporary_file"
test "$seen_postgres_password" = 1 || \
    printf 'POSTGRES_PASSWORD=%s\n' "$init_postgres_password" >> "$temporary_file"
test "$seen_redis_host" = 1 || printf 'REDIS_HOST=%s\n' "$init_redis_host" >> "$temporary_file"
test "$seen_redis_port" = 1 || printf 'REDIS_PORT=%s\n' "$init_redis_port" >> "$temporary_file"
test "$seen_redis_password" = 1 || \
    printf 'REDIS_PASSWORD=%s\n' "$init_redis_password" >> "$temporary_file"

chmod 600 "$temporary_file"
"$script_dir/validate-env.sh" "$temporary_file" >/dev/null
mv "$temporary_file" "$destination"
temporary_file=
rmdir "$lock_directory"
lock_acquired=

printf 'Production environment initialized.\n'
