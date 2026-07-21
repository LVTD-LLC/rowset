"""Run Rowset's pytest suite against a disposable PGSandbox database."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Sequence
from urllib.parse import unquote, urlsplit

import pytest


class PGSandboxTestError(RuntimeError):
    """Raised when PGSandbox cannot prepare or clean up a test database."""


def build_test_environment(connection_string: str) -> dict[str, str]:
    """Map a PGSandbox URL to Rowset's explicit test environment."""
    parsed = urlsplit(connection_string)
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise PGSandboxTestError("PGSandbox returned an unsupported database URL.")
    if not all((parsed.hostname, parsed.port, parsed.username, parsed.password, parsed.path)):
        raise PGSandboxTestError("PGSandbox returned an incomplete database URL.")

    database_name = unquote(parsed.path.lstrip("/"))
    username = unquote(parsed.username)
    password = unquote(parsed.password)

    return {
        "DATA_UPLOAD_MAX_MEMORY_SIZE": "104857600",
        "DEBUG": "0",
        "DJANGO_READ_DOT_ENV": "0",
        "ENVIRONMENT": "test",
        "PGDATABASE": database_name,
        "PGHOST": parsed.hostname,
        "PGPASSWORD": password,
        "PGPORT": str(parsed.port),
        "PGSANDBOX_DATABASE_URL": connection_string,
        "PGUSER": username,
        "POSTGRES_DB": database_name,
        "POSTGRES_HOST": parsed.hostname,
        "POSTGRES_PASSWORD": password,
        "POSTGRES_PORT": str(parsed.port),
        "POSTGRES_USER": username,
        "PYTEST_PLUGINS": "rowset.pgsandbox_tests",
        "REDIS_HOST": "127.0.0.1",
        "REDIS_PASSWORD": "",
        "REDIS_PORT": "6379",
        "SECRET_KEY": "test-secret-key",
        "SITE_URL": "https://testserver",
    }


def _pgsandbox_result(arguments: Sequence[str]) -> dict:
    pgsandbox_binary = os.environ.get("PGSANDBOX_BIN", "pgsandbox")
    try:
        completed = subprocess.run(
            [pgsandbox_binary, *arguments, "--json"],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as error:
        raise PGSandboxTestError(
            "pgsandbox is not installed or is not available on PATH."
        ) from error

    try:
        response = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise PGSandboxTestError(
            f"pgsandbox {arguments[0]} returned an invalid response."
        ) from error

    if completed.returncode != 0 or not response.get("ok"):
        summary = response.get("summary") or "The command failed without a summary."
        raise PGSandboxTestError(f"pgsandbox {arguments[0]} failed: {summary}")

    return response["result"]


def _create_database() -> dict:
    ttl_minutes = os.environ.get("PGSANDBOX_TEST_TTL_MINUTES", "60")
    return _pgsandbox_result(
        [
            "create-database",
            "--name-hint",
            "rowset-test",
            "--ttl-minutes",
            ttl_minutes,
            "--postgres-version",
            "18",
            "--owner",
            "rowset-test-runner",
            "--label",
            "purpose=rowset-host-tests",
            "--set-json",
            'extensions=["vector","pg_stat_statements"]',
        ]
    )


def _connection_string(database_id: str) -> str:
    result = _pgsandbox_result(
        [
            "get-connection-string",
            "--database-id",
            database_id,
            "--set",
            "includeCredentials=true",
        ]
    )
    return result["connectionString"]


def _delete_database(database_id: str) -> None:
    _pgsandbox_result(["delete-database", "--database-id", database_id])


def run_tests(pytest_arguments: Sequence[str]) -> int:
    database = _create_database()
    database_id = database["databaseId"]
    print(f"PGSandbox database ready: {database['databaseName']}", flush=True)

    try:
        environment = os.environ.copy()
        environment.update(build_test_environment(_connection_string(database_id)))
        completed = subprocess.run(
            ["uv", "run", "python", "-m", "pytest", *pytest_arguments],
            check=False,
            env=environment,
        )
        return completed.returncode
    finally:
        _delete_database(database_id)
        print("PGSandbox database deleted.", flush=True)


@pytest.fixture(scope="session")
def django_db_setup(django_db_blocker):
    """Migrate the existing sandbox instead of asking Django to create another database."""
    if not os.environ.get("PGSANDBOX_DATABASE_URL"):
        raise PGSandboxTestError(
            "The PGSandbox pytest plugin was loaded without a sandbox database."
        )

    from django.core.management import call_command

    with django_db_blocker.unblock():
        call_command("migrate", interactive=False, verbosity=0)
    yield


def main() -> int:
    try:
        return run_tests(sys.argv[1:])
    except PGSandboxTestError as error:
        print(f"PGSandbox test setup failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
