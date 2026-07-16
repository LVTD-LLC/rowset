import os
import stat
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).parents[2]
_VALIDATE = _REPO_ROOT / "deployment/self-host/validate-env.sh"
_CANARY = "canary-value-that-must-never-appear-" + "x" * 64
_SECRET_KEYS = ("SECRET_KEY", "POSTGRES_PASSWORD", "REDIS_PASSWORD")


def _safe_values() -> dict[str, str]:
    return {
        "ROWSET_IMAGE": "ghcr.io/lvtd-llc/rowset:5b65d16f0a7a",
        "ROWSET_DOMAIN": "rowset.example.com",
        "ENVIRONMENT": "prod",
        "DEBUG": "off",
        "SECRET_KEY": "s" * 64,
        "POSTGRES_DB": "rowset",
        "POSTGRES_USER": "rowset",
        "POSTGRES_HOST": "db",
        "POSTGRES_PORT": "5432",
        "POSTGRES_PASSWORD": "p" * 48,
        "REDIS_HOST": "redis",
        "REDIS_PORT": "6379",
        "REDIS_PASSWORD": "r" * 48,
    }


def _write_env(path: Path, values: dict[str, str], mode: int = 0o600) -> None:
    path.write_text("".join(f"{key}={value}\n" for key, value in values.items()))
    path.chmod(mode)


def _clean_environment() -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in _SECRET_KEYS and not key.endswith("_FILE")
    }
    return environment


def _run_validate(
    path: Path | None = None,
    *,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    arguments = [str(_VALIDATE), str(path)] if path else [str(_VALIDATE), "--environment"]
    return subprocess.run(
        arguments,
        cwd=_REPO_ROOT,
        env={**_clean_environment(), **(environment or {})},
        text=True,
        capture_output=True,
        check=False,
    )


def test_validator_accepts_safe_production_file(tmp_path):
    env_file = tmp_path / ".env"
    _write_env(env_file, _safe_values())

    result = _run_validate(env_file)

    assert result.returncode == 0
    assert result.stdout == "Production environment is valid.\n"
    assert result.stderr == ""


@pytest.mark.parametrize(
    "key",
    [
        "ROWSET_IMAGE",
        "ROWSET_DOMAIN",
        "ENVIRONMENT",
        "DEBUG",
        "SECRET_KEY",
        "POSTGRES_DB",
        "POSTGRES_USER",
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "POSTGRES_PASSWORD",
        "REDIS_HOST",
        "REDIS_PORT",
        "REDIS_PASSWORD",
    ],
)
def test_validator_rejects_missing_required_values(tmp_path, key):
    values = _safe_values()
    del values[key]
    env_file = tmp_path / ".env"
    _write_env(env_file, values)

    result = _run_validate(env_file)

    assert result.returncode != 0
    assert key in result.stderr
    assert "required" in result.stderr


@pytest.mark.parametrize(
    ("key", "value", "reason"),
    [
        ("ENVIRONMENT", "dev", "must be prod"),
        ("DEBUG", "on", "must be off"),
        ("ROWSET_DOMAIN", "https://rowset.example.com", "must be a hostname"),
        ("ROWSET_DOMAIN", "localhost", "must be a hostname"),
        ("ROWSET_IMAGE", "ghcr.io/lvtd-llc/rowset:latest", "immutable tag"),
        ("ROWSET_IMAGE", "ghcr.io/lvtd-llc/rowset", "immutable tag"),
        ("SECRET_KEY", "super-secret-key", "unsafe development default"),
        ("SECRET_KEY", "s" * 49, "at least 50 characters"),
        ("POSTGRES_PASSWORD", "rowset", "unsafe development default"),
        ("POSTGRES_PASSWORD", "p" * 31, "at least 32 characters"),
        ("REDIS_PASSWORD", "rowset", "unsafe development default"),
        ("REDIS_PASSWORD", "r" * 31, "at least 32 characters"),
        ("POSTGRES_DB", "invalid name", "safe identifier"),
        ("POSTGRES_USER", "-invalid", "safe identifier"),
        ("POSTGRES_HOST", "localhost", "must be db"),
        ("POSTGRES_PORT", "15432", "must be 5432"),
        ("REDIS_HOST", "localhost", "must be redis"),
        ("REDIS_PORT", "16379", "must be 6379"),
    ],
)
def test_validator_rejects_unsafe_values_without_printing_them(tmp_path, key, value, reason):
    values = _safe_values()
    values[key] = value
    env_file = tmp_path / ".env"
    _write_env(env_file, values)

    result = _run_validate(env_file)

    assert result.returncode != 0
    assert key in result.stderr
    assert reason in result.stderr
    assert value not in result.stdout + result.stderr


def test_validator_rejects_duplicate_assignments(tmp_path):
    env_file = tmp_path / ".env"
    _write_env(env_file, _safe_values())
    with env_file.open("a") as file:
        file.write("DEBUG=off\n")

    result = _run_validate(env_file)

    assert result.returncode != 0
    assert "DEBUG" in result.stderr
    assert "assigned more than once" in result.stderr


def test_validator_rejects_malformed_lines_without_echoing_them(tmp_path):
    env_file = tmp_path / ".env"
    _write_env(env_file, _safe_values())
    with env_file.open("a") as file:
        file.write(f"not-an-assignment-{_CANARY}\n")

    result = _run_validate(env_file)

    assert result.returncode != 0
    assert "ENV_FILE" in result.stderr
    assert "malformed assignment" in result.stderr
    assert _CANARY not in result.stdout + result.stderr


def test_validator_rejects_non_private_permissions(tmp_path):
    env_file = tmp_path / ".env"
    _write_env(env_file, _safe_values(), mode=0o640)

    result = _run_validate(env_file)

    assert result.returncode != 0
    assert "ENV_FILE" in result.stderr
    assert "mode 0600" in result.stderr


def test_validator_rejects_reused_secrets_without_disclosing_canary(tmp_path):
    values = _safe_values()
    values["SECRET_KEY"] = values["POSTGRES_PASSWORD"] = _CANARY
    env_file = tmp_path / ".env"
    _write_env(env_file, values)

    result = _run_validate(env_file)

    assert result.returncode != 0
    assert "must be distinct" in result.stderr
    assert _CANARY not in result.stdout + result.stderr


def test_validator_accepts_environment_and_secret_file_inputs(tmp_path):
    values = _safe_values()
    environment = {key: value for key, value in values.items() if key not in _SECRET_KEYS}
    for key in _SECRET_KEYS:
        secret_file = tmp_path / key
        secret_file.write_text(values[key] + "\n")
        secret_file.chmod(0o600)
        environment[f"{key}_FILE"] = str(secret_file)

    result = _run_validate(environment=environment)

    assert result.returncode == 0
    assert result.stdout == "Production environment is valid.\n"
    for key in _SECRET_KEYS:
        assert values[key] not in result.stdout + result.stderr


def test_validator_rejects_direct_and_file_secret_inputs_together(tmp_path):
    values = _safe_values()
    secret_file = tmp_path / "secret"
    secret_file.write_text(_CANARY + "\n")
    secret_file.chmod(0o600)
    environment = {
        **values,
        "SECRET_KEY_FILE": str(secret_file),
    }

    result = _run_validate(environment=environment)

    assert result.returncode != 0
    assert "SECRET_KEY" in result.stderr
    assert "both direct and file inputs" in result.stderr
    assert values["SECRET_KEY"] not in result.stdout + result.stderr
    assert _CANARY not in result.stdout + result.stderr


@pytest.mark.parametrize("contents", ["", "first-line\nsecond-line\n"])
def test_validator_rejects_empty_or_multiline_secret_files(tmp_path, contents):
    values = _safe_values()
    secret_file = tmp_path / "secret"
    secret_file.write_text(contents)
    secret_file.chmod(0o600)
    environment = {
        **{key: value for key, value in values.items() if key != "SECRET_KEY"},
        "SECRET_KEY_FILE": str(secret_file),
    }

    result = _run_validate(environment=environment)

    assert result.returncode != 0
    assert "SECRET_KEY" in result.stderr
    assert "single nonblank line" in result.stderr
    if contents.strip():
        assert contents.strip() not in result.stdout + result.stderr
