#!/bin/sh
set -eu

if test "$#" -lt 1; then
    printf 'Usage: %s BUNDLE_ROOT [REFERENCE_FILE ...]\n' "$0" >&2
    exit 2
fi

bundle_root=$1
shift
guide="$bundle_root/SELF_HOSTING.md"
compose_file="$bundle_root/docker-compose-prod.yml"
environment_template="$bundle_root/deployment/self-host/env.example"

test -f "$guide" || {
    printf 'self-host release is missing SELF_HOSTING.md\n' >&2
    exit 1
}

required_commands='deployment/self-host/version.sh
deployment/verify-image-platforms.sh
deployment/self-host/init-env.sh
deployment/self-host/validate-env.sh
deployment/self-host/preflight.sh
deployment/self-host/start.sh
deployment/self-host/doctor.sh
deployment/self-host/smoke-test.sh'

documented_commands=$(
    grep -Eo 'deployment/[A-Za-z0-9_./-]+\.sh' "$guide" | awk '!seen[$0]++'
) || true
test -n "$documented_commands" || {
    printf 'SELF_HOSTING.md does not document any deployment commands\n' >&2
    exit 1
}

for command in $documented_commands; do
    test -f "$bundle_root/$command" || {
        printf 'missing documented command: %s\n' "$command" >&2
        exit 1
    }
    test -x "$bundle_root/$command" || {
        printf 'documented command is not executable: %s\n' "$command" >&2
        exit 1
    }
done

required_command_list=$(printf '%s\n' "$required_commands" | paste -sd '|' -)
guide_required_commands=$(
    printf '%s\n' "$documented_commands" | awk -v required="$required_command_list" '
        BEGIN {
            count = split(required, commands, "|")
            for (i = 1; i <= count; i++) {
                is_required[commands[i]] = 1
            }
        }
        is_required[$0] { print }
    '
)
test "$guide_required_commands" = "$required_commands" || {
    printf 'SELF_HOSTING.md does not match the required command sequence\n' >&2
    exit 1
}

for reference_file in "$@"; do
    test -f "$reference_file" || {
        printf 'release contract reference is missing: %s\n' "$reference_file" >&2
        exit 1
    }
    referenced_commands=$(grep -Eo 'deployment/[A-Za-z0-9_./-]+\.sh' "$reference_file") || true
    test "$referenced_commands" = "$required_commands" || {
        printf 'release contract reference does not match the required command sequence: %s\n' \
            "$reference_file" >&2
        exit 1
    }
    for command in $referenced_commands; do
        test -f "$bundle_root/$command" || {
            printf 'missing documented command: %s\n' "$command" >&2
            exit 1
        }
        test -x "$bundle_root/$command" || {
            printf 'documented command is not executable: %s\n' "$command" >&2
            exit 1
        }
    done
done

for command in $required_commands; do
    printf '%s\n' "$documented_commands" | grep -Fx "$command" >/dev/null || {
        printf 'SELF_HOSTING.md is missing required release command: %s\n' "$command" >&2
        exit 1
    }
done

linked_guide_targets=$(grep -Eo '\]\([^)]+\)' "$guide" | sed 's/^](//; s/)$//' | awk '{print $1}') || true
for linked_target in $linked_guide_targets; do
    case "$linked_target" in
        http://*|https://*|mailto:*|\#*) continue ;;
    esac
    linked_file=$(printf '%s\n' "$linked_target" | sed 's/[?#].*$//')
    case "$linked_file" in
        /*|../*|*/../*)
            printf 'linked guide file escapes the release bundle: %s\n' "$linked_file" >&2
            exit 1
            ;;
    esac
    test -f "$bundle_root/$linked_file" || {
        printf 'missing linked guide file: %s\n' "$linked_file" >&2
        exit 1
    }
done

test -f "$compose_file" && test -f "$environment_template" || {
    printf 'self-host release is missing the Qdrant deployment contract\n' >&2
    exit 1
}
for required_text in 'qdrant/qdrant:v1.18.2' 'vector-search' 'qdrant_data:/qdrant/storage'; do
    grep -Fq "$required_text" "$compose_file" || {
        printf 'self-host Compose is missing Qdrant contract: %s\n' "$required_text" >&2
        exit 1
    }
done
for required_text in 'ROWSET_VECTOR_SEARCH_ENABLED=False' 'QDRANT_URL=http://qdrant:6333' 'QDRANT_API_KEY='; do
    grep -Fq "$required_text" "$environment_template" || {
        printf 'self-host environment is missing Qdrant contract: %s\n' "$required_text" >&2
        exit 1
    }
done

printf 'Self-host release contract verified (%s documented commands).\n' \
    "$(printf '%s\n' "$documented_commands" | wc -l | tr -d ' ')"
