#!/usr/bin/env python
from __future__ import annotations

import argparse
import http.client
import json
import os
import sys
from urllib.parse import urlparse


def _site_host_header() -> str:
    site_url = os.environ.get("SITE_URL", "http://localhost")
    parsed = urlparse(site_url if "://" in site_url else f"https://{site_url}")
    host = parsed.netloc
    if not host:
        raise RuntimeError(f"Could not derive Host header from SITE_URL={site_url!r}")
    return host


def check_server() -> None:
    connection = http.client.HTTPConnection("127.0.0.1", 80, timeout=5)
    try:
        connection.request(
            "GET",
            "/api/healthcheck",
            headers={
                "Host": _site_host_header(),
                "User-Agent": "rowset-docker-healthcheck",
            },
        )
        response = connection.getresponse()
        body = response.read(4096)
    finally:
        connection.close()

    if response.status != 200:
        raise RuntimeError(f"Server healthcheck returned HTTP {response.status}: {body!r}")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Server healthcheck returned invalid JSON: {body!r}") from exc

    if payload.get("healthy") is not True:
        raise RuntimeError(f"Server healthcheck returned unhealthy payload: {payload!r}")


def check_worker() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "filebridge.settings")

    import django
    from django.core.cache import cache
    from django.db import connection

    django.setup()

    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        cursor.fetchone()

    cache_key = "docker_healthcheck"
    cache_value = "ok"
    cache.set(cache_key, cache_value, timeout=10)
    if cache.get(cache_key) != cache_value:
        raise RuntimeError("Redis cache healthcheck round trip failed")
    cache.delete(cache_key)


def main() -> int:
    parser = argparse.ArgumentParser(description="Container health checks for Rowset.")
    parser.add_argument("target", choices=["server", "worker"])
    args = parser.parse_args()

    try:
        if args.target == "server":
            check_server()
        else:
            check_worker()
    except Exception as exc:
        print(f"Healthcheck failed: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
