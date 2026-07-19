from pathlib import Path

_REPO_ROOT = Path(__file__).parents[2]


def test_test_compose_supplies_safe_environment_without_dotenv():
    test_compose = (_REPO_ROOT / "docker-compose-test.yml").read_text()
    ci_local = (_REPO_ROOT / "scripts/ci-local.sh").read_text()
    makefile = (_REPO_ROOT / "Makefile").read_text()

    assert "env_file: !reset []" in test_compose
    for setting in (
        "ENVIRONMENT: test",
        'DJANGO_READ_DOT_ENV: "0"',
        'DEBUG: "0"',
        "SECRET_KEY: test-secret-key",
        'SITE_URL: "https://testserver"',
        "POSTGRES_HOST: db",
        "POSTGRES_DB: rowset",
        "POSTGRES_USER: rowset",
        "POSTGRES_PASSWORD: rowset",
        "REDIS_HOST: redis",
        "REDIS_PASSWORD: rowset",
    ):
        assert setting in test_compose

    assert "Missing .env" not in ci_local
    assert "TEST_COMPOSE_PROJECT_NAME ?=" in makefile
    assert "-p $(TEST_COMPOSE_PROJECT_NAME)" in makefile
    assert "export COMPOSE_PROJECT_NAME" in ci_local
