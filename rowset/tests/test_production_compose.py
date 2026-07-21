import os
import subprocess
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).parents[2]
_MEDIA_MOUNTS = {
    "media_data:/app/media",
    "private_media_data:/app/private_media",
}
_PRODUCTION_SERVICES = {"caddy", "db", "redis", "qdrant", "backend", "workers"}


def _production_compose():
    return yaml.safe_load((_REPO_ROOT / "docker-compose-prod.yml").read_text())


def test_self_hosting_surface_is_one_compose_file_and_one_guide():
    assert (_REPO_ROOT / "docker-compose-prod.yml").is_file()
    assert (_REPO_ROOT / "SELF_HOSTING.md").is_file()
    assert not (_REPO_ROOT / "deployment" / "self-host").exists()
    assert not list((_REPO_ROOT / "scripts").glob("*self-host*"))


def test_production_compose_persists_user_data_in_named_volumes():
    compose = _production_compose()

    assert _MEDIA_MOUNTS <= set(compose["services"]["backend"]["volumes"])
    assert _MEDIA_MOUNTS <= set(compose["services"]["workers"]["volumes"])
    assert {
        "postgres_data",
        "media_data",
        "private_media_data",
        "caddy_data",
        "caddy_config",
    } <= set(compose["volumes"])


def test_caddy_is_the_only_public_ingress_and_uses_inline_configuration():
    compose = _production_compose()
    services = compose["services"]
    caddy = services["caddy"]

    assert set(caddy["ports"]) == {"80:80", "443:443", "443:443/udp"}
    for service_name in {"backend", "workers", "db", "redis", "qdrant"}:
        assert "ports" not in services[service_name]
    assert services["backend"]["expose"] == [80]
    assert caddy["configs"] == [{"source": "rowset_caddyfile", "target": "/etc/caddy/Caddyfile"}]
    caddyfile = compose["configs"]["rowset_caddyfile"]["content"]
    assert "${ROWSET_DOMAIN:?Set ROWSET_DOMAIN" in caddyfile
    assert "max_size 64MB" in caddyfile
    assert "reverse_proxy backend:80" in caddyfile
    assert "flush_interval -1" in caddyfile


def test_production_compose_requires_a_domain_and_release_image():
    compose_text = (_REPO_ROOT / "docker-compose-prod.yml").read_text()

    assert "${ROWSET_DOMAIN:?Set ROWSET_DOMAIN" in compose_text
    assert "${ROWSET_IMAGE:?Set ROWSET_IMAGE" in compose_text
    assert "SITE_URL: https://${ROWSET_DOMAIN" in compose_text


def test_production_compose_applies_restart_and_bounded_logging_to_every_service():
    compose = _production_compose()

    assert set(compose["services"]) == _PRODUCTION_SERVICES
    for service in compose["services"].values():
        assert service["restart"] == "unless-stopped"
        assert service["logging"] == {
            "driver": "json-file",
            "options": {"max-size": "10m", "max-file": "3"},
        }


def test_production_services_load_the_same_environment_file():
    compose = _production_compose()

    for service_name in {"db", "redis", "backend", "workers"}:
        assert compose["services"][service_name]["env_file"] == [".env"]


def test_qdrant_is_private_persistent_authenticated_and_opt_in():
    compose = _production_compose()
    qdrant = compose["services"]["qdrant"]

    assert qdrant["image"] == "qdrant/qdrant:v1.18.2"
    assert qdrant["profiles"] == ["vector-search"]
    assert "ports" not in qdrant
    assert qdrant["environment"] == {
        "QDRANT__SERVICE__API_KEY": "${QDRANT_API_KEY:?Set QDRANT_API_KEY in .env}"
    }
    assert qdrant["volumes"] == ["qdrant_data:/qdrant/storage"]
    assert "qdrant_data" in compose["volumes"]


def test_production_compose_waits_for_authenticated_redis_health():
    compose = _production_compose()
    redis = compose["services"]["redis"]

    assert redis["command"] == [
        "sh",
        "-c",
        'test -n "$$REDIS_PASSWORD" || { echo "REDIS_PASSWORD is required" >&2; exit 1; }; '
        'exec redis-server --requirepass "$$REDIS_PASSWORD"',
    ]
    for service_name in ("backend", "workers"):
        assert compose["services"][service_name]["depends_on"] == {
            "db": {"condition": "service_healthy"},
            "redis": {"condition": "service_healthy"},
        }


def test_production_compose_rejects_an_empty_redis_password():
    redis = _production_compose()["services"]["redis"]

    for command in (redis["command"][2], redis["healthcheck"]["test"][1]):
        result = subprocess.run(
            ["sh", "-c", command.replace("$$", "$")],
            env={**os.environ, "REDIS_PASSWORD": ""},
            capture_output=True,
            text=True,
        )

        assert result.returncode != 0


def test_self_hosting_guide_uses_direct_compose_commands_and_safe_secrets():
    guide = (_REPO_ROOT / "SELF_HOSTING.md").read_text()

    for required in (
        'git checkout "$ROWSET_VERSION"',
        "ROWSET_IMAGE=ghcr.io/lvtd-llc/rowset:$ROWSET_VERSION",
        "umask 077",
        "openssl rand -hex 32",
        "docker compose -p rowset -f docker-compose-prod.yml config --quiet",
        "docker compose -p rowset -f docker-compose-prod.yml up -d",
        "docker compose -p rowset -f docker-compose-prod.yml ps",
        "python manage.py check --deploy",
        'curl -fsS "https://$ROWSET_DOMAIN/"',
        "docker compose -p rowset -f docker-compose-prod.yml logs --tail=100",
        "docker compose -p rowset -f docker-compose-prod.yml pull",
        "Do not run `docker compose down -v`",
    ):
        assert required in guide
    assert "deployment/self-host/" not in guide
    assert "install-rowset-self-host.sh" not in guide


def test_local_ci_validates_compose_without_a_custom_wrapper():
    ci_local = (_REPO_ROOT / "scripts" / "ci-local.sh").read_text()

    assert 'run_step "Production Compose config" docker compose' in ci_local
    assert "config --no-interpolate --quiet" in ci_local
    assert "verify-production-compose.sh" not in ci_local
