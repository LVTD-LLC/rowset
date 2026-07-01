#!/usr/bin/env python3
"""Production-like import smoke check for Rowset server and worker startup paths."""

from __future__ import annotations

import argparse
import importlib
import os
import sys
import warnings
from pathlib import Path

SAFE_PRODUCTION_ENV = {
    "ENVIRONMENT": "prod",
    "DJANGO_READ_DOT_ENV": "0",
    "DEBUG": "0",
    "SECRET_KEY": "startup-smoke-secret-key",
    "SITE_URL": "https://startup-smoke.local",
    "ALLOWED_HOSTS": "startup-smoke.local,localhost,127.0.0.1",
    "POSTGRES_DB": "rowset",
    "POSTGRES_USER": "rowset",
    "POSTGRES_PASSWORD": "rowset",
    "POSTGRES_HOST": "127.0.0.1",
    "POSTGRES_PORT": "5432",
    "REDIS_HOST": "127.0.0.1",
    "REDIS_PORT": "6379",
    "REDIS_PASSWORD": "",
    "REDIS_DB": "0",
    "MAILGUN_API_KEY": "",
    "MJML_URL": "",
    "AWS_S3_ENDPOINT_URL": "",
    "ROWSET_ASSET_S3_ENDPOINT_URL": "",
    "ROWSET_VECTOR_SEARCH_ENABLED": "0",
    "OPENROUTER_API_KEY": "",
    "OPENAI_API_KEY": "",
    "STRIPE_SECRET_KEY": "",
    "STRIPE_WEBHOOK_SECRET": "",
    "SENTRY_DSN": "",
    "POSTHOG_API_KEY": "",
}

IMPORT_MODULES = (
    "rowset.settings",
    "rowset.storages",
    "rowset.asgi",
    "rowset.wsgi",
    "rowset.urls",
    "deployment.healthcheck",
    "apps.core.tasks",
    "apps.datasets.tasks",
    "apps.datasets.vector_tasks",
    "apps.api.views",
    "apps.mcp_server.server",
)


def configure_environment(repo_root: Path) -> None:
    sys.path.insert(0, str(repo_root))
    warnings.filterwarnings(
        "ignore",
        message=r"No directory at: .*/static/",
        category=UserWarning,
        module=r"django\.core\.handlers\.base",
    )
    for key, value in SAFE_PRODUCTION_ENV.items():
        os.environ[key] = value
    os.environ["DJANGO_SETTINGS_MODULE"] = "rowset.settings"


def import_modules() -> list[str]:
    imported: list[str] = []
    for module_name in IMPORT_MODULES:
        try:
            importlib.import_module(module_name)
        except Exception as exc:
            raise RuntimeError(f"Failed to import {module_name}: {exc}") from exc
        imported.append(module_name)
    return imported


def check_django_runtime() -> None:
    import django
    from django.core.files.storage import storages
    from django.urls import get_resolver

    django.setup()
    storages["dataset_assets"]
    url_patterns = get_resolver().url_patterns
    if not url_patterns:
        raise RuntimeError("URL resolver returned no URL patterns.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repository root. Used only for display and future extension.",
    )
    args = parser.parse_args()

    configure_environment(args.repo_root)
    try:
        imported = import_modules()
        check_django_runtime()
    except Exception as exc:
        print(f"Startup/import smoke failed: {exc}", file=sys.stderr)
        return 1

    print(f"Startup/import smoke passed for {len(imported)} modules under {args.repo_root}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
