# Caddy Self-Hosting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship one reusable Docker Compose self-hosting path where Caddy automatically provides
HTTPS, the Rowset backend is private, and Django is secure and proxy-aware in production.

**Architecture:** Add Caddy to the existing production Compose stack as the only public ingress,
parameterized by required `ROWSET_DOMAIN`, with persistent certificate state and an internal
`backend:80` upstream. Configure Django's production HTTPS behavior from one explicit mode switch,
and isolate temporary IP-only HTTP testing in a separately named Compose override.

**Tech Stack:** Docker Compose, Caddy 2.11.4, Django 6 security settings, pytest, PyYAML, HTMX
request middleware.

## Global Constraints

- Implement SH-004, SH-005, and SH-010 in one focused change and one PR.
- `ROWSET_DOMAIN` is the only normal self-hosted networking input; Compose derives `SITE_URL`.
- Caddy is the only service that publishes public web ports; the backend remains Compose-internal.
- Production supports `linux/amd64` and `linux/arm64` through the existing Rowset image contract.
- The maximum request body is 64 MB, which accommodates a 32 MB audio asset encoded as base64 JSON.
- Normal production uses trusted automatic HTTPS; IP-only HTTP is explicit, temporary, and insecure.
- Local development over `http://localhost:8000` remains unchanged.
- Do not add dependencies, migrations, provider-specific DNS plugins, or alternative proxy guides.
- Never log or document API keys, OAuth tokens, raw secrets, or private dataset contents.
- Run tests through the Docker-backed `make test` path.

---

### Task 1: Start the combined Rowset work items

**Files:**
- Read: `docs/superpowers/specs/2026-07-15-caddy-self-hosting-design.md`
- Read: `docker-compose-prod.yml`
- Read: `rowset/settings.py`

**Interfaces:**
- Consumes: Rowset dataset `4939d389-6f16-4bf3-851c-b9b015655057`, indexed by `task_id`.
- Produces: SH-004, SH-005, and SH-010 with status `Doing` and `updated_on=2026-07-15`.

- [ ] **Step 1: Re-read the accepted design and verify the worktree is clean except for accepted plan artifacts**

Run:

```bash
git status --short
sed -n '1,260p' docs/superpowers/specs/2026-07-15-caddy-self-hosting-design.md
```

Expected: no uncommitted product changes and the design names all three tasks.

- [ ] **Step 2: Move all three Rowset rows to Doing through MCP**

For each of `SH-004`, `SH-005`, and `SH-010`, call `update_dataset_row_by_index` with:

```json
{
  "dataset_key": "4939d389-6f16-4bf3-851c-b9b015655057",
  "index_value": "SH-004",
  "data": {"status": "Doing", "updated_on": "2026-07-15"}
}
```

Repeat with the other two stable index values. Do not change `task_id` or acceptance criteria.

- [ ] **Step 3: Verify the Rowset state through MCP**

Call `get_dataset_row_by_index` for all three rows.

Expected: every row reports `status=Doing` and retains its original acceptance criteria.

---

### Task 2: Make Caddy the only production ingress

**Files:**
- Create: `deployment/self-host/Caddyfile`
- Create: `deployment/self-host/compose.insecure-http.yml`
- Modify: `docker-compose-prod.yml`
- Modify: `rowset/tests/test_production_compose.py`

**Interfaces:**
- Consumes: required shell variables `ROWSET_IMAGE` and `ROWSET_DOMAIN`.
- Produces: Caddy site variable `ROWSET_SITE_ADDRESS`, internal upstream `backend:80`, and derived
  application variable `SITE_URL=https://${ROWSET_DOMAIN}`.

- [ ] **Step 1: Write failing Compose and Caddy contract tests**

Append helpers and tests to `rowset/tests/test_production_compose.py`:

```python
_CADDYFILE = _REPO_ROOT / "deployment" / "self-host" / "Caddyfile"
_INSECURE_OVERRIDE = (
    _REPO_ROOT / "deployment" / "self-host" / "compose.insecure-http.yml"
)


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
    assert "SITE_URL: https://${ROWSET_DOMAIN}" in compose_text
    assert "ROWSET_SITE_ADDRESS: ${ROWSET_DOMAIN" in compose_text


def test_caddyfile_supports_automatic_https_streaming_and_large_assets():
    caddyfile = _CADDYFILE.read_text()

    assert "{$ROWSET_SITE_ADDRESS}" in caddyfile
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
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
make test rowset/tests/test_production_compose.py -q
```

Expected: existing media tests pass; new tests fail because the Caddy service and files do not
exist and backend still publishes `8000:80`.

- [ ] **Step 3: Add the minimal production Caddy configuration**

Create `deployment/self-host/Caddyfile`:

```caddyfile
{$ROWSET_SITE_ADDRESS} {
    log {
        output stdout
        format json
    }

    request_body {
        max_size 64MB
    }

    reverse_proxy backend:80 {
        flush_interval -1
    }
}
```

Modify `docker-compose-prod.yml` so it contains this ingress service and networking contract:

```yaml
services:
  caddy:
    image: caddy:2.11.4-alpine
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
      - "443:443/udp"
    environment:
      ROWSET_SITE_ADDRESS: ${ROWSET_DOMAIN:?Set ROWSET_DOMAIN to the public hostname}
    volumes:
      - ./deployment/self-host/Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
      - caddy_config:/config
    depends_on:
      backend:
        condition: service_healthy

  backend:
    image: ${ROWSET_IMAGE:?Set ROWSET_IMAGE to a verified release or SHA tag}
    working_dir: /app
    expose:
      - 80
    environment:
      APP_PROCESS_TYPE: server
      SITE_URL: https://${ROWSET_DOMAIN:?Set ROWSET_DOMAIN to the public hostname}
```

Keep the existing database dependencies, environment file, and media mounts on `backend`. Add the
same derived `SITE_URL` to `workers`. Remove `backend.ports` entirely. Add `caddy_data` and
`caddy_config` beside the existing named volumes.

Create `deployment/self-host/compose.insecure-http.yml`:

```yaml
services:
  caddy:
    environment:
      ROWSET_SITE_ADDRESS: http://${ROWSET_DOMAIN:?Set ROWSET_DOMAIN to the server IP}

  backend:
    environment:
      SITE_URL: http://${ROWSET_DOMAIN:?Set ROWSET_DOMAIN to the server IP}
      ROWSET_INSECURE_HTTP: "true"

  workers:
    environment:
      SITE_URL: http://${ROWSET_DOMAIN:?Set ROWSET_DOMAIN to the server IP}
      ROWSET_INSECURE_HTTP: "true"
```

- [ ] **Step 4: Run the focused tests and verify GREEN**

Run:

```bash
make test rowset/tests/test_production_compose.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Validate both Compose expansions and the Caddyfile**

Run:

```bash
ROWSET_IMAGE=ghcr.io/lvtd-llc/rowset:test ROWSET_DOMAIN=rowset.example.com \
  docker compose -f docker-compose-prod.yml config --quiet
ROWSET_IMAGE=ghcr.io/lvtd-llc/rowset:test ROWSET_DOMAIN=203.0.113.10 \
  docker compose -f docker-compose-prod.yml \
  -f deployment/self-host/compose.insecure-http.yml config --quiet
docker run --rm \
  -e ROWSET_SITE_ADDRESS=rowset.example.com \
  -v "$PWD/deployment/self-host/Caddyfile:/etc/caddy/Caddyfile:ro" \
  caddy:2.11.4-alpine caddy validate --config /etc/caddy/Caddyfile
```

Expected: both Compose commands exit 0; Caddy reports `Valid configuration`.

- [ ] **Step 6: Commit the ingress slice**

```bash
git add docker-compose-prod.yml deployment/self-host/Caddyfile \
  deployment/self-host/compose.insecure-http.yml rowset/tests/test_production_compose.py
git commit -m "feat(self-hosting): add automatic HTTPS with Caddy"
```

---

### Task 3: Make Django secure behind Caddy

**Files:**
- Create: `rowset/tests/test_production_security.py`
- Modify: `rowset/settings.py`

**Interfaces:**
- Consumes: `ENVIRONMENT`, `SITE_URL`, and diagnostic-only `ROWSET_INSECURE_HTTP`.
- Produces: Django `SECURE_PROXY_SSL_HEADER`, `SECURE_SSL_REDIRECT`, secure cookie flags, and HSTS
  settings.

- [ ] **Step 1: Write failing production-settings probes**

Create `rowset/tests/test_production_security.py`:

```python
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
def test_forwarded_https_full_page_and_htmx_requests_do_not_redirect(client):
    full_page = client.get("/", HTTP_X_FORWARDED_PROTO="https")
    htmx = client.get(
        "/",
        HTTP_X_FORWARDED_PROTO="https",
        HTTP_HX_REQUEST="true",
    )

    assert full_page.status_code == 200
    assert htmx.status_code == 200
```

- [ ] **Step 2: Run the settings tests and verify RED**

Run:

```bash
make test rowset/tests/test_production_security.py -q
```

Expected: production assertions fail because the secure settings are absent or false.

- [ ] **Step 3: Add minimal conditional security settings**

Add immediately after `DEBUG`, `ENVIRONMENT`, and `SITE_URL` are loaded in `rowset/settings.py`:

```python
ROWSET_INSECURE_HTTP = env.bool("ROWSET_INSECURE_HTTP", default=False)
PRODUCTION_HTTPS_ENABLED = ENVIRONMENT == "prod" and not ROWSET_INSECURE_HTTP

SECURE_PROXY_SSL_HEADER = (
    ("HTTP_X_FORWARDED_PROTO", "https") if PRODUCTION_HTTPS_ENABLED else None
)
SECURE_SSL_REDIRECT = PRODUCTION_HTTPS_ENABLED
SESSION_COOKIE_SECURE = PRODUCTION_HTTPS_ENABLED
CSRF_COOKIE_SECURE = PRODUCTION_HTTPS_ENABLED
SECURE_HSTS_SECONDS = 31_536_000 if PRODUCTION_HTTPS_ENABLED else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
```

Keep `ACCOUNT_DEFAULT_HTTP_PROTOCOL = "https"` conditional on deployed production behavior, but
ensure the diagnostic override does not generate HTTPS URLs:

```python
if PRODUCTION_HTTPS_ENABLED:
    ACCOUNT_DEFAULT_HTTP_PROTOCOL = "https"
```

- [ ] **Step 4: Run focused tests and verify GREEN**

Run:

```bash
make test rowset/tests/test_production_security.py -q
make test apps/core/tests/test_app_shell.py apps/core/tests/test_signup_gating.py -q
```

Expected: all tests pass; both normal and HTMX forwarded-HTTPS requests return 200.

- [ ] **Step 5: Run Django's production deployment check**

Run inside the test container with production overrides:

```bash
docker compose -f docker-compose-local.yml -f docker-compose-test.yml run --rm \
  -e ENVIRONMENT=prod -e DEBUG=off -e SITE_URL=https://rowset.example.com \
  backend python manage.py check --deploy
```

Expected: exit 0 with no warnings for `security.W004`, `security.W008`, `security.W012`, or
`security.W016`. Any unrelated existing deployment warning must be recorded rather than hidden.

- [ ] **Step 6: Commit the Django security slice**

```bash
git add rowset/settings.py rowset/tests/test_production_security.py
git commit -m "fix(security): trust Caddy HTTPS in production"
```

---

### Task 4: Replace competing self-hosting paths with one reusable guide

**Files:**
- Modify: `.env.example`
- Modify: `SELF_HOSTING.md`
- Modify: `README.md`
- Modify: `rowset/tests/test_production_compose.py`

**Interfaces:**
- Consumes: production command using `docker-compose-prod.yml` and required `ROWSET_DOMAIN`.
- Produces: one canonical self-hosting workflow and one clearly insecure diagnostic command.

- [ ] **Step 1: Write failing documentation contract tests**

Append to `rowset/tests/test_production_compose.py`:

```python
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
```

- [ ] **Step 2: Run documentation tests and verify RED**

Run:

```bash
make test rowset/tests/test_production_compose.py -q
```

Expected: documentation tests fail on the current Nginx, Certbot, direct-port, and generic proxy
instructions.

- [ ] **Step 3: Rewrite the canonical Compose guide**

Rewrite `SELF_HOSTING.md` around this exact section order:

```markdown
# Self-host Rowset

## What this path supports
## Prerequisites
## 1. Prepare DNS and firewall
## 2. Fetch Rowset and verify the image
## 3. Configure the environment
## 4. Start Rowset with automatic HTTPS
## 5. Verify web, REST, and MCP
## Certificate renewal and Caddy state
## Persistent data and backups
## Updates
## Temporary insecure IP-only diagnostic mode
## Troubleshooting
## Environment reference
```

The production start command must be:

```bash
docker compose -f docker-compose-prod.yml -p rowset up -d --remove-orphans
```

The guide must require `ROWSET_DOMAIN`, explain DNS A/AAAA records and inbound TCP 80/443, identify
`caddy_data` and `caddy_config` as persistent TLS state, and verify:

```bash
curl -I "http://$ROWSET_DOMAIN"
curl -fsS "https://$ROWSET_DOMAIN/" >/dev/null
curl -fsS "https://$ROWSET_DOMAIN/api/user" \
  -H "Authorization: Bearer $ROWSET_API_KEY"
```

The temporary diagnostic command must be visibly labelled insecure and use both files:

```bash
docker compose -f docker-compose-prod.yml \
  -f deployment/self-host/compose.insecure-http.yml \
  -p rowset up -d --remove-orphans
```

State that diagnostic mode must not contain accounts, API keys, or private datasets and must be
torn down before normal production deployment. Remove Nginx, Certbot, generic proxy selection, and
direct port 8000 production instructions.

- [ ] **Step 4: Align README and environment examples**

Add beside `ROWSET_IMAGE` in `.env.example`:

```dotenv
# Required only by the production self-hosting Compose path.
# Point this hostname at the server before starting Caddy.
ROWSET_DOMAIN=
```

Keep local `SITE_URL=http://localhost:8000`. Replace README's self-hosting proxy choices and public
port 8000 text with a concise link to `SELF_HOSTING.md`, noting that the supported Compose path
uses Caddy and `ROWSET_DOMAIN` for automatic HTTPS. Preserve CapRover content only where it
describes the separate managed deployment workflow, not as an alternative proxy tutorial.

- [ ] **Step 5: Run documentation tests and verify GREEN**

Run:

```bash
make test rowset/tests/test_production_compose.py rowset/tests/test_image_platforms.py -q
```

Expected: all Compose, documentation, backup, and architecture tests pass.

- [ ] **Step 6: Commit the documentation slice**

```bash
git add .env.example SELF_HOSTING.md README.md rowset/tests/test_production_compose.py
git commit -m "docs(self-hosting): standardize the Caddy deployment path"
```

---

### Task 5: Verify the combined deployment boundary and hand off remote checks

**Files:**
- Verify: `docker-compose-prod.yml`
- Verify: `deployment/self-host/Caddyfile`
- Verify: `deployment/self-host/compose.insecure-http.yml`
- Verify: `rowset/settings.py`
- Verify: `SELF_HOSTING.md`
- Verify: `README.md`

**Interfaces:**
- Consumes: all artifacts from Tasks 2-4.
- Produces: fresh test evidence and Rowset status/notes for SH-004, SH-005, and SH-010.

- [ ] **Step 1: Run focused deployment and security tests**

```bash
make test rowset/tests/test_production_compose.py \
  rowset/tests/test_production_security.py \
  rowset/tests/test_deployment_dockerfile.py \
  rowset/tests/test_deployment_healthcheck.py \
  rowset/tests/test_image_platforms.py -q
```

Expected: all selected tests pass with zero failures.

- [ ] **Step 2: Run MCP and server-rendered request regression tests**

```bash
make test apps/mcp_server/tests/test_asgi.py \
  apps/mcp_server/tests/test_auth.py \
  apps/core/tests/test_app_shell.py \
  apps/core/tests/test_signup_gating.py -q
```

Expected: all selected tests pass; MCP ASGI and normal/HTMX pages remain functional.

- [ ] **Step 3: Run static verification**

```bash
uv run ruff check rowset/settings.py rowset/tests/test_production_compose.py \
  rowset/tests/test_production_security.py
uv run ruff format --check rowset/settings.py rowset/tests/test_production_compose.py \
  rowset/tests/test_production_security.py
git diff --check
```

Expected: every command exits 0.

- [ ] **Step 4: Re-run Compose and Caddy validation**

```bash
ROWSET_IMAGE=ghcr.io/lvtd-llc/rowset:test ROWSET_DOMAIN=rowset.example.com \
  docker compose -f docker-compose-prod.yml config --quiet
docker run --rm \
  -e ROWSET_SITE_ADDRESS=rowset.example.com \
  -v "$PWD/deployment/self-host/Caddyfile:/etc/caddy/Caddyfile:ro" \
  caddy:2.11.4-alpine caddy validate --config /etc/caddy/Caddyfile
```

Expected: Compose exits 0 and Caddy reports a valid configuration.

- [ ] **Step 5: Record remote production verification commands**

On a disposable server whose DNS resolves to the host, run:

```bash
curl -sSIL "http://$ROWSET_DOMAIN" | sed -n '1,12p'
curl -fsSvo /dev/null "https://$ROWSET_DOMAIN/"
docker compose -f docker-compose-prod.yml -p rowset logs --since=10m caddy backend
docker compose -f docker-compose-prod.yml -p rowset ps
```

Then use an authenticated MCP client to call `initialize`, `tools/list`, and one deliberately slow
read-only request, and upload a valid 32 MB audio asset through the supported REST or MCP endpoint.
From a second host, verify that ports 80 and 443 are reachable and port 8000 is closed.

Expected: one HTTP redirect to HTTPS, a trusted certificate chain, healthy containers, successful
MCP streaming and maximum-size upload, and no external backend listener.

- [ ] **Step 6: Update all three Rowset work items with honest status**

If Step 5 was executed successfully, update each row to `Done`. Otherwise update each row to
`Review`. In both cases set `updated_on=2026-07-15` and append concise notes containing:

```text
Implemented together in one change: Caddy-only ingress, private backend networking, proxy-aware
Django HTTPS settings, secure cookies/HSTS, 64 MB ingress limit, and an explicit insecure IP-only
override. Local evidence: <commands and results>. Remote evidence still required: trusted public
certificate, renewal logs, external port scan, long MCP request, and maximum-size asset upload.
```

Do not claim remote checks that were not actually run.

- [ ] **Step 7: Review final history and status**

```bash
git status --short
git log --oneline -5
```

Expected: no uncommitted changes, three focused implementation commits after the design and plan
commits, and Rowset rows accurately reflect verified evidence.
