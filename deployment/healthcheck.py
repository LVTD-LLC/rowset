#!/usr/bin/env python
from __future__ import annotations

import argparse
import http.client
import os
import sys
from urllib.parse import urlparse
from uuid import uuid4


def _site_host_header() -> str:
    site_url = os.environ.get("SITE_URL", "http://localhost")
    parsed = urlparse(site_url if "://" in site_url else f"https://{site_url}")
    host = parsed.netloc
    if not host:
        raise RuntimeError(f"Could not derive Host header from SITE_URL={site_url!r}")
    return host


def check_server() -> None:
    port = int(os.environ.get("PORT", "80"))
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=4)
    try:
        connection.request(
            "GET",
            "/",
            headers={
                "Host": _site_host_header(),
                "User-Agent": "rowset-docker-healthcheck",
            },
        )
        response = connection.getresponse()
    finally:
        connection.close()

    if response.status < 200 or response.status >= 400:
        raise RuntimeError(f"Server healthcheck returned HTTP {response.status}")

    check_dependencies()


def check_dependencies() -> None:
    """Require the configured Django app, database, and Redis to be ready."""
    if not os.environ.get("DJANGO_SETTINGS_MODULE"):
        raise RuntimeError("DJANGO_SETTINGS_MODULE must be configured for dependency checks")

    import django
    from django.conf import settings
    from django.db import connection
    from redis import Redis

    django.setup()

    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        cursor.fetchone()

    redis = Redis.from_url(
        settings.REDIS_URL,
        socket_connect_timeout=4,
        socket_timeout=4,
    )
    healthcheck_key = f"docker_healthcheck:{uuid4().hex}"
    healthcheck_value = "ok"
    try:
        if not redis.set(healthcheck_key, healthcheck_value, ex=10):
            raise RuntimeError("Redis healthcheck write failed")
        if redis.get(healthcheck_key) != healthcheck_value.encode():
            raise RuntimeError("Redis healthcheck read failed")
        redis.delete(healthcheck_key)
    finally:
        redis.close()


def check_worker() -> None:
    check_dependencies()


def main() -> int:
    parser = argparse.ArgumentParser(description="Container health checks for Rowset.")
    parser.add_argument("target", nargs="?", choices=["server", "worker"])
    args = parser.parse_args()
    target = args.target or os.environ.get("APP_PROCESS_TYPE", "server")

    try:
        if target == "server":
            check_server()
        elif target == "worker":
            check_worker()
        else:
            raise RuntimeError(f"Unsupported healthcheck target: {target!r}")
    except Exception as exc:
        print(f"Healthcheck failed: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
