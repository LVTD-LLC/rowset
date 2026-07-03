#!/bin/sh
set -eu

export PROJECT_NAME=rowset
export DJANGO_SETTINGS_MODULE="rowset.settings"
APP_PORT="${PORT:-80}"
process_type="${APP_PROCESS_TYPE:-}"

while getopts ":sw" option; do
    case "${option}" in
        s) process_type="server" ;;
        w) process_type="worker" ;;
        *)
            echo "Invalid option: -$OPTARG" >&2
            exit 1
            ;;
    esac
done
shift $((OPTIND - 1))

if [ -z "$process_type" ]; then
    if [ "${ENVIRONMENT:-}" = "prod" ]; then
        echo "APP_PROCESS_TYPE must be set to 'server' or 'worker' when ENVIRONMENT=prod." >&2
        exit 1
    fi

    process_type="server"
fi

wait_for_database() {
    echo "Waiting for database..."
    uv run --no-sync python - <<'PY'
import os
import sys
import time

import django
from django.db import connections

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "rowset.settings")
django.setup()

last_error = None
for attempt in range(1, 61):
    try:
        connections["default"].ensure_connection()
        print("Database is ready.")
        sys.exit(0)
    except Exception as exc:
        last_error = exc
        print(f"Database unavailable, retrying ({attempt}/60): {exc}", flush=True)
        time.sleep(2)

print(f"Database did not become ready: {last_error}", file=sys.stderr)
sys.exit(1)
PY
}

wait_for_database

case "$process_type" in
    server)
        echo "Starting Rowset server..."
        uv run --no-sync python manage.py collectstatic --noinput
        uv run --no-sync python manage.py migrate --noinput
        uv run --no-sync python manage.py sync_blog_posts
        exec uv run --no-sync gunicorn "${PROJECT_NAME}.asgi:application" \
            --bind "0.0.0.0:${APP_PORT}" \
            --workers 3 \
            --worker-class uvicorn_worker.UvicornWorker
        ;;
    worker)
        echo "Starting Rowset workers..."
        exec uv run --no-sync python manage.py qcluster
        ;;
    *)
        echo "Invalid APP_PROCESS_TYPE: $process_type. Expected 'server' or 'worker'." >&2
        exit 1
        ;;
esac
