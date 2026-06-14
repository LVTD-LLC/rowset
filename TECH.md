# TECH.md

## Stack

- Backend: Django 6, Python `>=3.14,<4.0`.
- API: Django Ninja in `apps/api`.
- MCP: FastMCP in `apps/mcp_server`.
- Auth: Django allauth, session auth, API-key auth, hosted MCP OAuth.
- Data: PostgreSQL, Redis, Django Q workers.
- Tabular processing: Python `csv`, Polars for Parquet, Google Sheets API paths.
- Frontend: Django templates, Stimulus, Webpack, Tailwind, Bootstrap.
- Local containers: Docker Compose with Postgres, Redis, backend, workers,
  frontend Node 24, Mailhog, Stripe CLI, MJML, and MinIO.
- Observability/integrations: Sentry, Logfire, PostHog, Chatwoot, Mailgun,
  Buttondown, Stripe, S3-compatible storage.

## Commands

- Copy local env: `cp .env.example .env`
- Start the app stack: `make serve`
- Run Django shell_plus: `make shell`
- Run Django management commands: `make manage <command>`
- Generate migrations: `make makemigrations`
- Apply migrations: `make migrate`
- Run all tests in Docker: `make test`
- Run focused tests: `make test apps/datasets/tests/test_csv_datasets.py`
- Pass pytest flags: `make test -- -k google_sheets -q`
- Restart workers: `make restart-worker`
- Build frontend assets: `npm run build`
- Lint frontend JS: `npm run lint`

## Runtime Configuration

Local configuration comes from `.env`, usually copied from `.env.example`.
Important required values are `ENVIRONMENT`, `SECRET_KEY`, `SITE_URL`, Postgres
settings, and Redis settings. Production should use `ENVIRONMENT=prod` and
`DEBUG=off`.

Keep secrets in environment variables only. Do not commit `.env`, API keys,
OAuth tokens, service account JSON, Stripe secrets, Sentry DSNs, or user dataset
contents.

## Architecture

- `filebridge/settings.py` wires Django apps, allauth, storage, logging, Redis,
  Django Q, observability, payments, and AI model labels.
- `apps/datasets` owns dataset parsing, preview, import, row storage, exports,
  Google Sheets behavior, and dataset-specific tests.
- `apps/api` exposes REST endpoints and keeps API schemas/auth/service wrappers.
- `apps/mcp_server` exposes hosted MCP tools and OAuth-compatible auth.
- `apps/core` owns profiles, account state, feedback, email delivery, Stripe
  webhook handling, and shared helpers.
- `apps/docs` renders Markdown docs from `apps/docs/content` and navigation YAML.
- `frontend/templates` contains Django templates for landing, authenticated app,
  datasets, docs, account flows, and shared components.
- `frontend/src/controllers` contains Stimulus controllers.
- `deployment`, Dockerfiles, Compose files, and Render config own deployment.

## Dataset Rules

- Upload parsing currently supports CSV and Parquet files.
- Google Sheets imports use CSV export for public sheets and the Sheets API for
  private OAuth-backed access.
- Source files are limited by `MAX_CSV_UPLOAD_BYTES` in
  `apps/datasets/constants.py`.
- Headers must be present, non-empty, and unique.
- Index values must be non-blank and unique unless FileBridge generated the index.
- Generated index columns use `filebridge_id` or the next available suffixed name.
- Stored row data is string-keyed by dataset headers.
- Semantic column metadata supports `text`, `integer`, `number`, `currency`,
  `boolean`, `date`, `datetime`, `email`, and `url`.

## API And MCP Rules

- REST endpoints use bearer API-key auth as the preferred private API path.
- Query-string API keys and `X-API-Key` exist for compatibility only.
- Hosted MCP should use browser-based OAuth when the client supports it.
- MCP API-key support is a compatibility fallback for older clients.
- REST and MCP row operations must enforce the authenticated profile's ownership
  boundary.
- Keep service-layer errors clear and convert them at the boundary: HTTP errors
  for REST and value errors for MCP tools.

## Frontend Rules

- Use Django templates for server-rendered pages.
- Use Stimulus controllers for interactivity; put new controllers in
  `frontend/src/controllers`.
- Global scripts or head snippets should live in shared components and be
  included by both `base_landing.html` and `base_app.html` when they apply
  globally.
- Keep long file names, headers, route paths, and API keys from breaking layout.
- Follow `DESIGN.md` for colors, typography, component style, and product feel.

## Testing Notes

- Prefer `make test` over host `pytest`.
- Dataset parser, import, API, MCP, OAuth, and Google Sheets changes need focused
  tests.
- Template-only changes can be checked with Django template loading and
  `manage.py check`, but asset-related work should also build or run the frontend
  stack.
