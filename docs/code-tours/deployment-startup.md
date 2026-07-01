# Deployment And Startup Flow

Use this tour before changing container builds, startup imports, health checks,
worker startup, static asset build behavior, or production-only settings.

## Files To Inspect

- `deployment/Dockerfile.server` - builds frontend assets, installs Python
  runtime dependencies, copies `frontend/build`, and starts the ASGI server.
- `deployment/Dockerfile.workers` - mirrors the server image but starts
  `manage.py qcluster`.
- `deployment/entrypoint.sh` - waits for the database, runs static collection
  and migrations for the server, then starts Gunicorn or workers.
- `deployment/healthcheck.py` - checks server HTTP health or worker dependency
  health through Django, Postgres, and Redis.
- `rowset/asgi.py` and `rowset/wsgi.py` - production import surfaces for server
  startup.
- `rowset/settings.py` - environment parsing, storage config, Redis/Django Q,
  observability, static files, and optional integrations.
- `.github/workflows/ci.yml`, `Makefile`, and `scripts/ci-local.sh` - quality
  gates that should catch import/startup drift before deploy.

## Commands

```bash
make quality-drift-check
make startup-smoke
make django-check
uv run python -c "import rowset.asgi; import rowset.wsgi; import rowset.settings"
uv run python deployment/healthcheck.py worker
```

Use Docker build checks only when a change touches runtime dependencies,
entrypoints, or frontend build output:

```bash
docker build -f deployment/Dockerfile.server .
docker build -f deployment/Dockerfile.workers .
```

## Startup Expectations

- Server and worker images should install the same Python runtime dependencies.
- Production-only imports must be direct dependencies in `pyproject.toml`.
- Health checks must fail when Django, Postgres, or Redis cannot initialize.
- Server startup owns `collectstatic` and migrations; worker startup should not
  run those side effects.
- CI/local quality docs must change together when adding a startup smoke check.

## Footguns

- A module can pass unit tests but still crash production startup if `rowset.asgi`,
  `rowset.wsgi`, settings, storage, or task modules import an undeclared runtime
  dependency.
- Do not require real S3, OpenRouter, Stripe, Sentry, Mailgun, or PostHog
  credentials for import smoke checks.
- Do not hide a production import failure by moving imports inside broad
  exception handlers.
- Keep worker-only failures visible; `deployment/healthcheck.py worker` should
  still import Django and check Postgres/Redis.
- If a new quality command is added, update `Makefile`, `.github/workflows/ci.yml`,
  `scripts/ci-local.sh`, and `docs/quality.md` together or
  `make quality-drift-check` should fail.
