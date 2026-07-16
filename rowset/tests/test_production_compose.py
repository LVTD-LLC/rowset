import os
import subprocess
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).parents[2]
_MEDIA_MOUNTS = {
    "media_data:/app/media",
    "private_media_data:/app/private_media",
}
_CADDYFILE = _REPO_ROOT / "deployment" / "self-host" / "Caddyfile"
_INSECURE_OVERRIDE = _REPO_ROOT / "deployment" / "self-host" / "compose.insecure-http.yml"
_PRODUCTION_SERVICES = {"caddy", "db", "redis", "backend", "workers"}


def _production_compose():
    return yaml.safe_load((_REPO_ROOT / "docker-compose-prod.yml").read_text())


def test_production_compose_persists_media_in_shared_named_volumes():
    compose = _production_compose()

    assert _MEDIA_MOUNTS <= set(compose["services"]["backend"]["volumes"])
    assert _MEDIA_MOUNTS <= set(compose["services"]["workers"]["volumes"])
    assert {"media_data", "private_media_data"} <= set(compose["volumes"])


def test_caddy_is_the_only_public_web_ingress():
    compose = _production_compose()
    services = compose["services"]

    assert set(services["caddy"]["ports"]) == {"80:80", "443:443", "443:443/udp"}
    for service_name in {"backend", "workers", "db", "redis"}:
        assert "ports" not in services[service_name]
    assert services["backend"]["expose"] == [80]


def test_caddy_uses_persistent_state_and_the_checked_in_config():
    compose = _production_compose()
    caddy = compose["services"]["caddy"]

    assert caddy["image"] == "caddy:2.11.4-alpine"
    assert caddy["restart"] == "unless-stopped"
    assert "./deployment/self-host/Caddyfile:/etc/caddy/Caddyfile:ro" in caddy["volumes"]
    assert "caddy_data:/data" in caddy["volumes"]
    assert "caddy_config:/config" in caddy["volumes"]
    assert {"caddy_data", "caddy_config"} <= set(compose["volumes"])


def test_production_compose_requires_one_domain_and_derives_https_site_url():
    compose_text = (_REPO_ROOT / "docker-compose-prod.yml").read_text()

    assert "${ROWSET_DOMAIN:?Set ROWSET_DOMAIN" in compose_text
    assert "SITE_URL: https://${ROWSET_DOMAIN" in compose_text
    assert "ROWSET_SITE_ADDRESS: ${ROWSET_DOMAIN" in compose_text


def test_caddyfile_supports_automatic_https_streaming_and_large_assets():
    caddyfile = _CADDYFILE.read_text()

    assert "{$ROWSET_SITE_ADDRESS}" in caddyfile
    assert "\n\tlog {" not in caddyfile
    assert "max_size 64MB" in caddyfile
    assert "reverse_proxy backend:80" in caddyfile
    assert "flush_interval -1" in caddyfile


def test_ip_only_http_mode_is_an_explicit_override():
    override = yaml.safe_load(_INSECURE_OVERRIDE.read_text())

    assert override["services"]["caddy"]["environment"]["ROWSET_SITE_ADDRESS"].startswith(
        "http://${ROWSET_DOMAIN"
    )
    for service_name in {"backend", "workers"}:
        environment = override["services"][service_name]["environment"]
        assert environment["SITE_URL"].startswith("http://${ROWSET_DOMAIN")
        assert environment["ROWSET_INSECURE_HTTP"] == "true"


def test_self_hosting_docs_present_one_caddy_https_golden_path():
    self_hosting = (_REPO_ROOT / "SELF_HOSTING.md").read_text()
    readme = (_REPO_ROOT / "README.md").read_text()

    assert "ROWSET_DOMAIN" in self_hosting
    assert "Caddy" in self_hosting
    assert "compose.insecure-http.yml" in self_hosting
    assert "https://$ROWSET_DOMAIN" in self_hosting
    assert "Nginx" not in self_hosting
    assert "Certbot" not in self_hosting
    assert "http://your-server-ip:8000" not in self_hosting
    assert "SELF_HOSTING.md" in readme
    assert "Nginx, Caddy, Traefik, or CapRover" not in readme
    assert "http://server-ip:8000" not in readme


def test_environment_example_names_the_self_host_domain_input():
    environment_example = (_REPO_ROOT / ".env.example").read_text()

    assert "ROWSET_DOMAIN=" in environment_example
    assert "ROWSET_INSECURE_HTTP" not in environment_example


def test_production_compose_applies_restart_and_bounded_logging_to_every_service():
    compose = _production_compose()

    assert set(compose["services"]) == _PRODUCTION_SERVICES
    for service in compose["services"].values():
        assert service["restart"] == "unless-stopped"
        assert service["logging"] == {
            "driver": "json-file",
            "options": {"max-size": "10m", "max-file": "3"},
        }


def test_production_services_load_the_validated_environment_file():
    compose = _production_compose()

    for service_name in {"db", "redis", "backend", "workers"}:
        assert compose["services"][service_name]["env_file"] == ["${ROWSET_ENV_FILE:-.env}"]


def test_production_compose_waits_for_authenticated_redis_health():
    compose = _production_compose()
    redis = compose["services"]["redis"]

    assert redis["command"] == [
        "sh",
        "-c",
        'test -n "$$REDIS_PASSWORD" || { echo "REDIS_PASSWORD is required" >&2; exit 1; }; '
        'exec redis-server --requirepass "$$REDIS_PASSWORD"',
    ]
    assert redis["healthcheck"]["test"] == [
        "CMD-SHELL",
        'test -n "$$REDIS_PASSWORD" && REDISCLI_AUTH="$$REDIS_PASSWORD" redis-cli ping',
    ]
    assert redis["healthcheck"] == {
        "test": [
            "CMD-SHELL",
            'test -n "$$REDIS_PASSWORD" && REDISCLI_AUTH="$$REDIS_PASSWORD" redis-cli ping',
        ],
        "interval": "5s",
        "timeout": "3s",
        "retries": 12,
        "start_period": "30s",
    }
    for service_name in ("backend", "workers"):
        assert compose["services"][service_name]["depends_on"] == {
            "db": {"condition": "service_healthy"},
            "redis": {"condition": "service_healthy"},
        }


def test_production_compose_rejects_an_empty_redis_password():
    compose = _production_compose()
    redis = compose["services"]["redis"]

    for command in (redis["command"][2], redis["healthcheck"]["test"][1]):
        result = subprocess.run(
            ["sh", "-c", command.replace("$$", "$")],
            env={**os.environ, "REDIS_PASSWORD": ""},
            capture_output=True,
            text=True,
        )

        assert result.returncode != 0


def test_local_ci_validates_rendered_production_compose():
    ci_local = (_REPO_ROOT / "scripts/ci-local.sh").read_text()
    compose_verifier = (_REPO_ROOT / "deployment/verify-production-compose.sh").read_text()

    assert (
        'run_step "Production Compose config" ./deployment/verify-production-compose.sh' in ci_local
    )
    assert 'run_step "Project and deployment tests"' in ci_local
    assert "rowset/tests -q" in ci_local
    assert '"$ROOT/deployment/self-host/validate-env.sh" "$env_file"' in compose_verifier
    assert 'grep -Fq "$env_file" "$rendered_config"' in compose_verifier


def test_supported_start_command_validates_before_invoking_compose():
    start_script = (_REPO_ROOT / "deployment/self-host/start.sh").read_text()

    validation = '"$script_dir/validate-env.sh" "$environment_file"'
    compose = "exec docker compose --env-file"
    assert validation in start_script
    assert compose in start_script
    assert start_script.index(validation) < start_script.index(compose)


def test_self_hosting_docs_explain_compose_recovery_logging_and_safe_diagnostics():
    self_hosting = (_REPO_ROOT / "SELF_HOSTING.md").read_text()

    assert "restart: unless-stopped" in self_hosting
    assert "host restart" in self_hosting
    assert "30 MB per service" in self_hosting
    assert "150 MB across the five-service stack" in self_hosting
    assert "config --no-env-resolution --no-interpolate" in self_hosting
    assert "Do not share `.env`" in self_hosting


def test_self_hosting_docs_use_safe_environment_commands_and_explain_rotation():
    self_hosting = (_REPO_ROOT / "SELF_HOSTING.md").read_text()
    readme = (_REPO_ROOT / "README.md").read_text()
    tech = (_REPO_ROOT / "TECH.md").read_text()
    production_template = (_REPO_ROOT / "deployment/self-host/env.example").read_text()

    for required in (
        "deployment/self-host/env.example",
        "deployment/self-host/init-env.sh",
        "deployment/self-host/validate-env.sh",
        "deployment/self-host/start.sh",
        "SECRET_KEY_FILE",
        "POSTGRES_PASSWORD_FILE",
        "REDIS_PASSWORD_FILE",
        "mode `0600`",
        "HCLOUD_TOKEN",
        "SECRET_KEY_FALLBACKS",
        "signed sessions",
    ):
        assert required in self_hosting
    assert "cp .env.example .env" not in self_hosting
    assert "deployment/self-host/init-env.sh" in readme
    assert "deployment/self-host/env.example" in tech
    assert "HCLOUD_TOKEN" not in production_template
