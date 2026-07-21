from pathlib import Path

from rowset.pgsandbox_tests import build_test_environment


def test_build_test_environment_maps_pgsandbox_connection_to_rowset_settings():
    environment = build_test_environment(
        "postgres://sandbox_user:p%40ssword@127.0.0.1:65432/sandbox_db?sslmode=disable"
    )

    assert environment == {
        "DATA_UPLOAD_MAX_MEMORY_SIZE": "104857600",
        "DEBUG": "0",
        "DJANGO_READ_DOT_ENV": "0",
        "ENVIRONMENT": "test",
        "PGDATABASE": "sandbox_db",
        "PGHOST": "127.0.0.1",
        "PGPASSWORD": "p@ssword",
        "PGPORT": "65432",
        "PGSANDBOX_DATABASE_URL": (
            "postgres://sandbox_user:p%40ssword@127.0.0.1:65432/sandbox_db?sslmode=disable"
        ),
        "PGUSER": "sandbox_user",
        "POSTGRES_DB": "sandbox_db",
        "POSTGRES_HOST": "127.0.0.1",
        "POSTGRES_PASSWORD": "p@ssword",
        "POSTGRES_PORT": "65432",
        "POSTGRES_USER": "sandbox_user",
        "PYTEST_PLUGINS": "rowset.pgsandbox_tests",
        "REDIS_HOST": "127.0.0.1",
        "REDIS_PASSWORD": "",
        "REDIS_PORT": "6379",
        "SECRET_KEY": "test-secret-key",
        "SITE_URL": "https://testserver",
    }


def test_makefile_exposes_pgsandbox_test_target():
    makefile = (Path(__file__).resolve().parents[2] / "Makefile").read_text()

    assert "test-pgsandbox:" in makefile
    assert "$(UV_RUN) python -m rowset.pgsandbox_tests" in makefile
