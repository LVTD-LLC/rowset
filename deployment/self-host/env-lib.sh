#!/bin/sh

fail() {
    printf 'Invalid %s: %s.\n' "$1" "$2" >&2
    exit 1
}

file_mode() {
    mode_path=$1
    stat -c '%a' "$mode_path" 2>/dev/null || stat -f '%Lp' "$mode_path" 2>/dev/null
}

file_owner() {
    owner_path=$1
    stat -c '%u' "$owner_path" 2>/dev/null || stat -f '%u' "$owner_path" 2>/dev/null
}

validate_environment_file_structure() {
    env_file=$1

    test -f "$env_file" || fail ENV_FILE "must be a regular file"
    test -r "$env_file" || fail ENV_FILE "must be readable"

    if awk '
        /^[[:space:]]*$/ || /^[[:space:]]*#/ { next }
        !/^[A-Za-z_][A-Za-z0-9_]*=/ { found = 1; exit }
        END { exit !found }
    ' "$env_file"; then
        fail ENV_FILE "contains a malformed assignment"
    fi

    duplicate_key=$(
        awk '
            /^[[:space:]]*$/ || /^[[:space:]]*#/ { next }
            {
                separator = index($0, "=")
                key = substr($0, 1, separator - 1)
                seen[key] += 1
                if (seen[key] == 2) {
                    print key
                    exit
                }
            }
        ' "$env_file"
    )
    test -z "$duplicate_key" || fail "$duplicate_key" "is assigned more than once"
}

validate_environment_file() {
    env_file=$1
    validate_environment_file_structure "$env_file"

    env_mode=$(file_mode "$env_file") || fail ENV_FILE "permissions cannot be read"
    test "$env_mode" = "600" || fail ENV_FILE "must have mode 0600"

    env_owner=$(file_owner "$env_file") || fail ENV_FILE "owner cannot be read"
    test "$env_owner" = "$(id -u)" || fail ENV_FILE "must be owned by the invoking user"
}

environment_file_value() {
    requested_key=$1
    env_file=$2
    awk -v requested_key="$requested_key" '
        /^[[:space:]]*$/ || /^[[:space:]]*#/ { next }
        {
            separator = index($0, "=")
            key = substr($0, 1, separator - 1)
            if (key == requested_key) {
                print substr($0, separator + 1)
                found = 1
                exit
            }
        }
        END { exit !found }
    ' "$env_file"
}

required_file_value() {
    requested_key=$1
    env_file=$2
    if requested_value=$(environment_file_value "$requested_key" "$env_file"); then
        test -n "$requested_value" || fail "$requested_key" "is required"
        printf '%s' "$requested_value"
        return
    fi
    fail "$requested_key" "is required"
}

required_environment_value() {
    requested_key=$1
    requested_value=$2
    test -n "$requested_value" || fail "$requested_key" "is required"
    printf '%s' "$requested_value"
}

secret_file_value() {
    secret_key=$1
    secret_path=$2
    test -f "$secret_path" || fail "$secret_key" "file input must be a regular readable file"
    test -r "$secret_path" || fail "$secret_key" "file input must be a regular readable file"
    awk 'NR > 1 || length($0) == 0 { exit 1 } END { exit !(NR == 1 && length($0) > 0) }' \
        "$secret_path" || fail "$secret_key" "file input must contain a single nonblank line"
    sed -n '1p' "$secret_path"
}

resolve_environment_secret() {
    secret_key=$1
    direct_value=$2
    secret_path=$3

    if test -n "$direct_value" && test -n "$secret_path"; then
        fail "$secret_key" "cannot use both direct and file inputs"
    fi
    if test -n "$secret_path"; then
        secret_file_value "$secret_key" "$secret_path"
        return
    fi
    required_environment_value "$secret_key" "$direct_value"
}

load_file_configuration() {
    env_file=$1
    validate_environment_file "$env_file"
    CFG_ROWSET_IMAGE=$(required_file_value ROWSET_IMAGE "$env_file")
    CFG_ROWSET_DOMAIN=$(required_file_value ROWSET_DOMAIN "$env_file")
    CFG_ENVIRONMENT=$(required_file_value ENVIRONMENT "$env_file")
    CFG_DEBUG=$(required_file_value DEBUG "$env_file")
    CFG_SECRET_KEY=$(required_file_value SECRET_KEY "$env_file")
    CFG_POSTGRES_DB=$(required_file_value POSTGRES_DB "$env_file")
    CFG_POSTGRES_USER=$(required_file_value POSTGRES_USER "$env_file")
    CFG_POSTGRES_HOST=$(required_file_value POSTGRES_HOST "$env_file")
    CFG_POSTGRES_PORT=$(required_file_value POSTGRES_PORT "$env_file")
    CFG_POSTGRES_PASSWORD=$(required_file_value POSTGRES_PASSWORD "$env_file")
    CFG_REDIS_HOST=$(required_file_value REDIS_HOST "$env_file")
    CFG_REDIS_PORT=$(required_file_value REDIS_PORT "$env_file")
    CFG_REDIS_PASSWORD=$(required_file_value REDIS_PASSWORD "$env_file")
}

load_process_configuration() {
    CFG_ROWSET_IMAGE=$(required_environment_value ROWSET_IMAGE "${ROWSET_IMAGE:-}")
    CFG_ROWSET_DOMAIN=$(required_environment_value ROWSET_DOMAIN "${ROWSET_DOMAIN:-}")
    CFG_ENVIRONMENT=$(required_environment_value ENVIRONMENT "${ENVIRONMENT:-}")
    CFG_DEBUG=$(required_environment_value DEBUG "${DEBUG:-}")
    CFG_SECRET_KEY=$(resolve_environment_secret SECRET_KEY "${SECRET_KEY:-}" "${SECRET_KEY_FILE:-}")
    CFG_POSTGRES_DB=$(required_environment_value POSTGRES_DB "${POSTGRES_DB:-}")
    CFG_POSTGRES_USER=$(required_environment_value POSTGRES_USER "${POSTGRES_USER:-}")
    CFG_POSTGRES_HOST=$(required_environment_value POSTGRES_HOST "${POSTGRES_HOST:-}")
    CFG_POSTGRES_PORT=$(required_environment_value POSTGRES_PORT "${POSTGRES_PORT:-}")
    CFG_POSTGRES_PASSWORD=$(
        resolve_environment_secret POSTGRES_PASSWORD \
            "${POSTGRES_PASSWORD:-}" "${POSTGRES_PASSWORD_FILE:-}"
    )
    CFG_REDIS_HOST=$(required_environment_value REDIS_HOST "${REDIS_HOST:-}")
    CFG_REDIS_PORT=$(required_environment_value REDIS_PORT "${REDIS_PORT:-}")
    CFG_REDIS_PASSWORD=$(
        resolve_environment_secret REDIS_PASSWORD "${REDIS_PASSWORD:-}" "${REDIS_PASSWORD_FILE:-}"
    )
}

validate_secret() {
    secret_key=$1
    secret_value=$2
    minimum_length=$3
    development_default=$4

    test "$secret_value" != "$development_default" || fail "$secret_key" "uses an unsafe development default"
    test "${#secret_value}" -ge "$minimum_length" || \
        fail "$secret_key" "must contain at least $minimum_length characters"
    case "$secret_value" in
        *'
'*) fail "$secret_key" "must be a single line" ;;
    esac
}

validate_loaded_configuration() {
    test "$CFG_ENVIRONMENT" = "prod" || fail ENVIRONMENT "must be prod"
    test "$CFG_DEBUG" = "off" || fail DEBUG "must be off"

    printf '%s\n' "$CFG_ROWSET_DOMAIN" | grep -Eq \
        '^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$' || \
        fail ROWSET_DOMAIN "must be a hostname without scheme, path, or port"

    image_segment=${CFG_ROWSET_IMAGE##*/}
    case "$image_segment" in
        *:*) image_tag=${image_segment##*:} ;;
        *) fail ROWSET_IMAGE "must use an explicit immutable tag" ;;
    esac
    printf '%s\n' "$image_tag" | grep -Eq '^([0-9a-f]{7,40}|v[0-9][A-Za-z0-9._-]*)$' || \
        fail ROWSET_IMAGE "must use an explicit immutable tag"

    printf '%s\n' "$CFG_POSTGRES_DB" | grep -Eq '^[A-Za-z_][A-Za-z0-9_-]*$' || \
        fail POSTGRES_DB "must be a safe identifier"
    printf '%s\n' "$CFG_POSTGRES_USER" | grep -Eq '^[A-Za-z_][A-Za-z0-9_-]*$' || \
        fail POSTGRES_USER "must be a safe identifier"
    test "$CFG_POSTGRES_HOST" = "db" || fail POSTGRES_HOST "must be db"
    test "$CFG_POSTGRES_PORT" = "5432" || fail POSTGRES_PORT "must be 5432"
    test "$CFG_REDIS_HOST" = "redis" || fail REDIS_HOST "must be redis"
    test "$CFG_REDIS_PORT" = "6379" || fail REDIS_PORT "must be 6379"

    validate_secret SECRET_KEY "$CFG_SECRET_KEY" 50 super-secret-key
    validate_secret POSTGRES_PASSWORD "$CFG_POSTGRES_PASSWORD" 32 rowset
    validate_secret REDIS_PASSWORD "$CFG_REDIS_PASSWORD" 32 rowset

    if test "$CFG_SECRET_KEY" = "$CFG_POSTGRES_PASSWORD" || \
        test "$CFG_SECRET_KEY" = "$CFG_REDIS_PASSWORD" || \
        test "$CFG_POSTGRES_PASSWORD" = "$CFG_REDIS_PASSWORD"; then
        fail SECRETS "must be distinct"
    fi
}

validate_environment_contract() {
    if test "${1:-}" = "--environment"; then
        load_process_configuration
    else
        load_file_configuration "$1"
    fi
    validate_loaded_configuration
}
