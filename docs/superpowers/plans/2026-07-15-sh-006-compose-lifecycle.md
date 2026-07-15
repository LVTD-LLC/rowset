# SH-006 Compose Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every production Compose service reliable restart and bounded-log defaults, gate application startup on authenticated Redis health, and document secret-safe diagnostics.

**Architecture:** A reusable Compose YAML extension supplies identical lifecycle and logging policy to PostgreSQL, Redis, backend, and workers. Redis reads its password only through container-side shell expansion, exposes authenticated health through `redis-cli`, and becomes a healthy dependency for application services. Focused repository tests inspect both the YAML contract and Docker Compose's rendered configuration before an isolated Redis runtime smoke check.

**Tech Stack:** Docker Compose v2+, YAML anchors, Redis 7 Alpine, Python 3.14, pytest, PyYAML, Django's Docker-backed `make test` workflow, Rowset MCP.

## Global Constraints

- Keep operational defaults in `docker-compose-prod.yml`; do not require Docker daemon-wide configuration.
- Use `restart: unless-stopped` for `db`, `redis`, `backend`, and `workers`.
- Use Docker's `json-file` logger with `max-size: 10m` and `max-file: 3` for every service.
- Do not add logging-size environment variables or new dependencies.
- Never print or commit `.env` contents, Redis passwords, Django secrets, API keys, or private data.
- Do not change Django, HTMX, templates, application logging, backups, proxy behavior, or image release policy.
- Do not claim that an unhealthy status alone triggers Docker restart behavior.
- Move SH-006 to `Review`, not `Done`, after local proof; real VPS reboot and on-disk rotation remain review checks.

---

### Task 1: Enforce Compose lifecycle, logging, and Redis readiness

**Files:**
- Modify: `rowset/tests/test_production_compose.py:1-73`
- Modify: `docker-compose-prod.yml:1-62`

**Interfaces:**
- Consumes: `.env` keys `POSTGRES_USER`, `REDIS_PASSWORD`, and `ROWSET_IMAGE` already required by production Compose.
- Produces: reusable YAML extension `x-service-defaults`; Redis Docker health status; `service_healthy` dependency contract for backend and workers.

- [ ] **Step 1: Move SH-006 to Doing through Rowset MCP**

Call `update_dataset_row_by_index` for dataset
`4939d389-6f16-4bf3-851c-b9b015655057`, index `SH-006`, with:

```json
{
  "status": "Doing",
  "updated_on": "2026-07-15",
  "notes": "Implementation started on branch rasul/sh-006-compose-lifecycle from approved design docs/superpowers/specs/2026-07-15-sh-006-compose-lifecycle-design.md. Local verification will move this task to Review; real VPS reboot and on-disk log rotation remain required before Done because the clean-room VPS was intentionally deleted."
}
```

- [ ] **Step 2: Write failing Compose contract tests**

Add these imports and tests to `rowset/tests/test_production_compose.py`:

```python
import textwrap


_PRODUCTION_SERVICES = {"db", "redis", "backend", "workers"}


def test_production_compose_applies_restart_and_bounded_logging_to_every_service():
    compose = _production_compose()

    assert set(compose["services"]) == _PRODUCTION_SERVICES
    for service in compose["services"].values():
        assert service["restart"] == "unless-stopped"
        assert service["logging"] == {
            "driver": "json-file",
            "options": {"max-size": "10m", "max-file": "3"},
        }


def test_production_compose_waits_for_authenticated_redis_health():
    compose = _production_compose()
    redis = compose["services"]["redis"]

    assert redis["command"] == [
        "sh",
        "-c",
        'exec redis-server --requirepass "$$REDIS_PASSWORD"',
    ]
    assert redis["healthcheck"]["test"] == [
        "CMD-SHELL",
        'REDISCLI_AUTH="$$REDIS_PASSWORD" redis-cli ping',
    ]
    assert redis["healthcheck"] == {
        "test": ["CMD-SHELL", 'REDISCLI_AUTH="$$REDIS_PASSWORD" redis-cli ping'],
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


def test_production_compose_renders_without_expanding_secrets(tmp_path):
    sentinel = "never-print-this-compose-secret"
    env_file = tmp_path / "compose.env"
    env_file.write_text(
        textwrap.dedent(
            f"""\
            ROWSET_IMAGE=ghcr.io/lvtd-llc/rowset:test
            POSTGRES_USER=rowset
            POSTGRES_PASSWORD={sentinel}
            REDIS_PASSWORD={sentinel}
            SECRET_KEY={sentinel}
            """
        )
    )

    result = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            str(env_file),
            "-f",
            str(_REPO_ROOT / "docker-compose-prod.yml"),
            "config",
            "--no-env-resolution",
        ],
        cwd=_REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert sentinel not in result.stdout
    assert "$REDIS_PASSWORD" in result.stdout
```

- [ ] **Step 3: Run the focused test and confirm the intended red state**

Run:

```bash
make test rowset/tests/test_production_compose.py -- -k "restart_and_bounded or authenticated_redis or renders_without" -q
```

Expected: failures for missing `restart`, missing `logging`, missing Redis
healthcheck, `service_started`, and host-expanded Redis credentials. The test
must not fail because Docker Compose or PyYAML is unavailable.

- [ ] **Step 4: Add the reusable Compose defaults and authenticated Redis healthcheck**

Replace the operational portions of `docker-compose-prod.yml` with this shape,
preserving the existing images, ports, env files, application environment, and
volumes:

```yaml
x-service-defaults: &service-defaults
  restart: unless-stopped
  logging:
    driver: json-file
    options:
      max-size: "10m"
      max-file: "3"

services:
  db:
    <<: *service-defaults
    image: rasulkireev/custom-postgres:17
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER}"]
      interval: 5s
      timeout: 5s
      retries: 5
    env_file:
      - .env

  redis:
    <<: *service-defaults
    image: redis:7-alpine
    command:
      - sh
      - -c
      - 'exec redis-server --requirepass "$$REDIS_PASSWORD"'
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD-SHELL", 'REDISCLI_AUTH="$$REDIS_PASSWORD" redis-cli ping']
      interval: 5s
      timeout: 3s
      retries: 12
      start_period: 30s
    env_file:
      - .env
```

Add `<<: *service-defaults` to backend and workers, and change both Redis
dependency conditions to `service_healthy`.

- [ ] **Step 5: Run the focused production Compose test file**

Run:

```bash
make test rowset/tests/test_production_compose.py
```

Expected: all tests in the file pass with no warnings or secret values in output.

- [ ] **Step 6: Commit the lifecycle and readiness slice**

```bash
git add docker-compose-prod.yml rowset/tests/test_production_compose.py
git commit -m "fix(deployment): harden compose lifecycle defaults"
```

### Task 2: Document bounds and secret-safe support rendering

**Files:**
- Modify: `rowset/tests/test_production_compose.py`
- Modify: `SELF_HOSTING.md:154-185`

**Interfaces:**
- Consumes: lifecycle/logging values defined by Task 1.
- Produces: operator documentation for automatic recovery, bounded Docker logs, and a support-safe Compose rendering command.

- [ ] **Step 1: Write the failing documentation contract test**

Add to `rowset/tests/test_production_compose.py`:

```python
def test_self_hosting_docs_explain_compose_recovery_logging_and_safe_diagnostics():
    self_hosting = (_REPO_ROOT / "SELF_HOSTING.md").read_text()

    assert "restart: unless-stopped" in self_hosting
    assert "host restart" in self_hosting
    assert "30 MB per service" in self_hosting
    assert "120 MB across the four-service stack" in self_hosting
    assert "config --no-env-resolution --no-interpolate" in self_hosting
    assert "Do not share `.env`" in self_hosting
```

- [ ] **Step 2: Run the documentation test and confirm it fails**

Run:

```bash
make test rowset/tests/test_production_compose.py -- -k safe_diagnostics -q
```

Expected: FAIL because the new operations guidance is absent.

- [ ] **Step 3: Add concise operations guidance after deployment verification**

Add this section to `SELF_HOSTING.md` immediately after “Verify deployment”:

```markdown
### Lifecycle and local Docker logs

All four services use `restart: unless-stopped`, so containers restart
automatically after a Docker daemon or host restart unless an operator stopped
them explicitly. Backend and workers wait for healthy PostgreSQL and Redis
dependencies during Compose startup.

Docker's local `json-file` logs rotate at three 10 MB files: approximately
30 MB per service and 120 MB across the four-service stack, before small Docker
metadata overhead. Application-level external logging remains separately
configurable through the optional observability settings below.

To validate or share the Compose structure without resolving `.env` values, use:

```bash
docker compose --env-file .env -f docker-compose-prod.yml -p rowset \
  config --no-env-resolution --no-interpolate
```

Do not share `.env`, ordinary fully resolved `docker compose config` output, or
container environment output; all can contain secrets.
```

Also replace the legacy `docker-compose ps` and `docker-compose logs backend`
examples in the verification section with `docker compose ps` and
`docker compose logs backend`.

- [ ] **Step 4: Run the focused production Compose tests**

Run:

```bash
make test rowset/tests/test_production_compose.py
```

Expected: all tests pass.

- [ ] **Step 5: Commit the documentation slice**

```bash
git add SELF_HOSTING.md rowset/tests/test_production_compose.py
git commit -m "docs(deployment): explain compose operational defaults"
```

### Task 3: Verify the production-like boundary and update Rowset

**Files:**
- Verify: `docker-compose-prod.yml`
- Verify: `rowset/tests/test_production_compose.py`
- Verify: `SELF_HOSTING.md`
- Update through MCP: Rowset dataset `4939d389-6f16-4bf3-851c-b9b015655057`, row `SH-006`

**Interfaces:**
- Consumes: completed Compose and documentation slices.
- Produces: fresh local verification evidence and a Rowset task in `Review` with remaining VPS checks explicit.

- [ ] **Step 1: Validate canonical Compose rendering without exposing environment values**

Run with the repository's private `.env` only as input; do not print it:

```bash
docker compose --env-file .env -f docker-compose-prod.yml -p rowset \
  config --no-env-resolution --no-interpolate --quiet
```

Expected: exit 0 and no output containing secret values.

- [ ] **Step 2: Start only Redis in an isolated Compose project**

Use a unique project name and the existing private `.env`:

```bash
project="rowset-sh006-$(date +%s)"
docker compose --env-file .env -f docker-compose-prod.yml -p "$project" up -d redis
```

Expected: Redis is created without starting backend, workers, or PostgreSQL.

- [ ] **Step 3: Wait for Redis health and inspect the effective policies**

Run, substituting the project value from Step 2:

```bash
container_id="$(docker compose -f docker-compose-prod.yml -p "$project" ps -q redis)"
for attempt in $(seq 1 30); do
  status="$(docker inspect --format '{{.State.Health.Status}}' "$container_id")"
  [ "$status" = healthy ] && break
  sleep 2
done
test "$status" = healthy
docker inspect --format '{{json .Config.Healthcheck.Test}}' "$container_id"
docker inspect --format '{{.HostConfig.RestartPolicy.Name}} {{.HostConfig.LogConfig.Type}} {{index .HostConfig.LogConfig.Config "max-size"}} {{index .HostConfig.LogConfig.Config "max-file"}}' "$container_id"
```

Expected: health command contains the variable reference but not its value; the
policy line is `unless-stopped json-file 10m 3`.

- [ ] **Step 4: Recreate Redis and prove it recovers**

```bash
docker compose --env-file .env -f docker-compose-prod.yml -p "$project" restart redis
for attempt in $(seq 1 30); do
  status="$(docker inspect --format '{{.State.Health.Status}}' "$container_id")"
  [ "$status" = healthy ] && break
  sleep 2
done
test "$status" = healthy
```

Expected: Redis returns to `healthy` after restart.

- [ ] **Step 5: Remove only the isolated verification project**

```bash
docker compose --env-file .env -f docker-compose-prod.yml -p "$project" down -v
```

Expected: only resources named for the unique SH-006 project are removed.

- [ ] **Step 6: Run fresh repository verification**

Run:

```bash
make test rowset/tests/test_production_compose.py
git diff --check HEAD~2
```

Then run the local CI-equivalent path because production Compose and operator
documentation are shared deployment surfaces:

```bash
make ci-local
```

Expected: every command exits 0 with no failures.

- [ ] **Step 7: Review the final branch diff and history**

```bash
git status --short
git log --oneline origin/main..HEAD
git diff --stat origin/main...HEAD
git diff origin/main...HEAD -- docker-compose-prod.yml rowset/tests/test_production_compose.py SELF_HOSTING.md
```

Expected: only the approved spec/plan, Compose, focused tests, and self-hosting
documentation changed; no secrets or unrelated edits appear.

- [ ] **Step 8: Move SH-006 to Review through Rowset MCP**

Call `update_dataset_row_by_index` for dataset
`4939d389-6f16-4bf3-851c-b9b015655057`, index `SH-006`, setting:

```json
{
  "status": "Review",
  "updated_on": "2026-07-15",
  "notes": "Implemented on branch rasul/sh-006-compose-lifecycle. Record exact focused tests, make ci-local result, Compose render validation, isolated Redis healthy/restart evidence, and inspected restart/log settings here. Remaining before Done: verify all four services return after a real VPS reboot and generate sufficient logs on that host to observe json-file rotation at 10 MB x 3. The previous clean-room VPS was intentionally deleted, so those checks were not simulated or claimed locally."
}
```

Preserve and extend the existing notes with exact command results rather than
replacing useful context with the template text above.
