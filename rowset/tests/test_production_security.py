import json
import os
import subprocess
import sys

import pytest
from django.test import override_settings

_PROBE = """
import json
from django.conf import settings

print(json.dumps({
    "proxy": settings.SECURE_PROXY_SSL_HEADER,
    "ssl_redirect": settings.SECURE_SSL_REDIRECT,
    "session_secure": settings.SESSION_COOKIE_SECURE,
    "csrf_secure": settings.CSRF_COOKIE_SECURE,
    "hsts_seconds": settings.SECURE_HSTS_SECONDS,
    "hsts_include_subdomains": settings.SECURE_HSTS_INCLUDE_SUBDOMAINS,
    "hsts_preload": settings.SECURE_HSTS_PRELOAD,
    "data_upload_max_memory_size": settings.DATA_UPLOAD_MAX_MEMORY_SIZE,
    "silenced_system_checks": settings.SILENCED_SYSTEM_CHECKS,
    "site_url": settings.SITE_URL,
    "secret_key_fallbacks": settings.SECRET_KEY_FALLBACKS,
}))
"""


def _settings_environment(*, environment, site_url, insecure_http=False, **overrides):
    process_environment = {
        **os.environ,
        "DJANGO_SETTINGS_MODULE": "rowset.settings",
        "ENVIRONMENT": environment,
        "DEBUG": "off",
        "SITE_URL": site_url,
        "ROWSET_INSECURE_HTTP": "true" if insecure_http else "false",
        "SECRET_KEY": "active-secret-" + "s" * 64,
        "POSTGRES_PASSWORD": "postgres-secret-" + "p" * 48,
        "REDIS_PASSWORD": "redis-secret-" + "r" * 48,
        "SECRET_KEY_FALLBACKS": "",
    }
    process_environment.update(overrides)
    return process_environment


def _run_settings(*, environment, site_url, insecure_http=False, **overrides):
    return subprocess.run(
        [sys.executable, "-c", _PROBE],
        env=_settings_environment(
            environment=environment,
            site_url=site_url,
            insecure_http=insecure_http,
            **overrides,
        ),
        text=True,
        capture_output=True,
    )


def _probe_settings(*, environment, site_url, insecure_http=False, **overrides):
    result = _run_settings(
        environment=environment,
        site_url=site_url,
        insecure_http=insecure_http,
        **overrides,
    )
    result.check_returncode()
    return json.loads(result.stdout.splitlines()[-1])


def test_production_https_settings_trust_caddy_and_secure_django():
    security = _probe_settings(environment="prod", site_url="https://rowset.example.com")

    assert security == {
        "proxy": ["HTTP_X_FORWARDED_PROTO", "https"],
        "ssl_redirect": True,
        "session_secure": True,
        "csrf_secure": True,
        "hsts_seconds": 31536000,
        "hsts_include_subdomains": False,
        "hsts_preload": False,
        "data_upload_max_memory_size": 64_000_000,
        "silenced_system_checks": ["security.W005", "security.W021"],
        "site_url": "https://rowset.example.com",
        "secret_key_fallbacks": [],
    }


@pytest.mark.parametrize(
    ("environment", "site_url", "insecure_http"),
    [
        ("dev", "http://localhost:8000", False),
        ("prod", "http://203.0.113.10", True),
    ],
)
def test_http_modes_do_not_force_https(environment, site_url, insecure_http):
    security = _probe_settings(
        environment=environment,
        site_url=site_url,
        insecure_http=insecure_http,
    )

    assert security["ssl_redirect"] is False
    assert security["session_secure"] is False
    assert security["csrf_secure"] is False
    assert security["hsts_seconds"] == 0


@pytest.mark.parametrize(
    ("overrides", "variable"),
    [
        ({"DEBUG": "on"}, "DEBUG"),
        ({"SECRET_KEY": "super-secret-key"}, "SECRET_KEY"),
        ({"SECRET_KEY": "s" * 49}, "SECRET_KEY"),
        ({"POSTGRES_PASSWORD": "rowset"}, "POSTGRES_PASSWORD"),
        ({"POSTGRES_PASSWORD": "p" * 31}, "POSTGRES_PASSWORD"),
        ({"REDIS_PASSWORD": "rowset"}, "REDIS_PASSWORD"),
        ({"REDIS_PASSWORD": "r" * 31}, "REDIS_PASSWORD"),
        (
            {
                "SECRET_KEY": "shared-secret-" + "s" * 64,
                "POSTGRES_PASSWORD": "shared-secret-" + "s" * 64,
            },
            "SECRETS",
        ),
    ],
)
def test_unsafe_production_configuration_fails_without_disclosing_values(overrides, variable):
    result = _run_settings(
        environment="prod",
        site_url="https://rowset.example.com",
        **overrides,
    )

    assert result.returncode != 0
    assert "ImproperlyConfigured" in result.stderr
    assert variable in result.stderr
    for value in overrides.values():
        if value not in {"on", "rowset", "super-secret-key"}:
            assert value not in result.stdout + result.stderr


def test_production_requires_https_without_the_diagnostic_override():
    result = _run_settings(environment="prod", site_url="http://rowset.example.com")

    assert result.returncode != 0
    assert "ImproperlyConfigured" in result.stderr
    assert "SITE_URL" in result.stderr
    assert "http://rowset.example.com" not in result.stdout + result.stderr


def test_production_accepts_a_strong_secret_key_fallback():
    fallback = "previous-secret-" + "f" * 64

    security = _probe_settings(
        environment="prod",
        site_url="https://rowset.example.com",
        SECRET_KEY_FALLBACKS=fallback,
    )

    assert security["secret_key_fallbacks"] == [fallback]


@pytest.mark.parametrize("fallback", ["super-secret-key", "f" * 49])
def test_production_rejects_unsafe_secret_key_fallbacks_without_disclosure(fallback):
    result = _run_settings(
        environment="prod",
        site_url="https://rowset.example.com",
        SECRET_KEY_FALLBACKS=fallback,
    )

    assert result.returncode != 0
    assert "ImproperlyConfigured" in result.stderr
    assert "SECRET_KEY_FALLBACKS" in result.stderr
    if fallback != "super-secret-key":
        assert fallback not in result.stdout + result.stderr


@override_settings(
    SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"),
    SECURE_SSL_REDIRECT=True,
)
@pytest.mark.django_db
def test_forwarded_https_full_page_and_htmx_requests_do_not_redirect(client):
    full_page = client.get("/", HTTP_X_FORWARDED_PROTO="https")
    htmx = client.get(
        "/",
        HTTP_X_FORWARDED_PROTO="https",
        HTTP_HX_REQUEST="true",
    )

    assert full_page.status_code == 200
    assert htmx.status_code == 200
