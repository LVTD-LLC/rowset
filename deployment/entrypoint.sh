#!/bin/sh
set -eu

# Default to server command if no arguments provided
if [ $# -eq 0 ]; then
    echo "No arguments provided. Defaulting to running the server."
    server=true
else
    server=false
fi

export PROJECT_NAME=filebridge
export DJANGO_SETTINGS_MODULE="filebridge.settings"

while getopts ":sw" option; do
    case "${option}" in
        s) server=true ;;
        w) server=false ;;
        *) echo "Invalid option: -$OPTARG" >&2 ;;
    esac
done
shift $((OPTIND - 1))

wait_for_database() {
    echo "Waiting for database..."
    python - <<'PY'
import os
import sys
import time

import django
from django.db import connections

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "filebridge.settings")
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

if [ "$server" = true ]; then
    echo "Starting FileBridge server..."
    python manage.py collectstatic --noinput
    python manage.py migrate --noinput
    exec gunicorn ${PROJECT_NAME}.asgi:application --bind 0.0.0.0:80 --workers 3 --worker-class uvicorn_worker.UvicornWorker
else
    echo "Starting FileBridge workers..."
    exec python manage.py qcluster
fi
