#!/bin/sh
set -eu

compose_file="${ROWSET_COMPOSE_FILE:-docker-compose-prod.yml}"
project_name="${ROWSET_COMPOSE_PROJECT:-rowset}"

exec docker compose -f "$compose_file" -p "$project_name" \
    exec -T backend python manage.py post_deploy_smoke_test "$@"
