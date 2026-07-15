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
}))
"""


def _probe_settings(*, environment, site_url, insecure_http=False):
    process_environment = {
        **os.environ,
        "DJANGO_SETTINGS_MODULE": "rowset.settings",
        "ENVIRONMENT": environment,
        "DEBUG": "off",
        "SITE_URL": site_url,
        "ROWSET_INSECURE_HTTP": "true" if insecure_http else "false",
    }
    result = subprocess.run(
        [sys.executable, "-c", _PROBE],
        env=process_environment,
        text=True,
        capture_output=True,
        check=True,
    )
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
