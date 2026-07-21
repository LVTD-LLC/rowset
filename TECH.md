# TECH.md

## Stack

- Backend: Django 6, Python `>=3.14,<4.0`.
- API: Django Ninja in `apps/api`.
- MCP: FastMCP in `apps/mcp_server`.
- CLI: Go `rowset` module in `cli/`, using the standard library HTTP client
  against the authenticated REST API.
- Auth: Django allauth, session auth, API-key auth, hosted MCP bearer auth.
- Data: PostgreSQL, Redis, Django Q workers, and optional Qdrant vector retrieval.
- Tabular processing: Python `csv`, `json`, `sqlite3`, and `zipfile` plus
  Polars for CSV, JSONL, XLSX, SQLite, and Parquet exports.
- Frontend: Django templates, HTMX, Alpine.js, Tailwind, and PostCSS-built
  static assets.
- Local containers: Docker Compose with Postgres, Redis, backend, workers,
  frontend Node 24, Mailhog, Stripe CLI, MJML, and MinIO.
- Observability/integrations: Sentry, PostHog, Chatwoot, Mailgun,
  Buttondown, Stripe, S3-compatible storage.

## Commands

- Copy local env: `cp .env.example .env`
- Start the app stack: `make serve`
- Run Django shell_plus: `make shell`
- Run Django management commands: `make manage <command>`
- Generate migrations: `make makemigrations`
- Apply migrations: `make migrate`
- Run all tests in Docker: `make test`
- Run focused tests: `make test apps/datasets/tests/test_dataset_creation.py`
- Pass pytest flags: `make test -- -k dataset -q`
- Run current local CI-equivalent checks: `make ci-local`
- Restart workers: `make restart-worker`
- Build frontend assets: `npm run build`
- Lint frontend JS: `npm run lint`
- Run CLI tests: `make cli-test`
- Build the `rowset` binary: `make cli-build`

## Runtime Configuration

Local configuration comes from `.env`, usually copied from `.env.example`.
Important required values are `ENVIRONMENT`, `SECRET_KEY`, `SITE_URL`, Postgres
settings, and Redis settings. Production should use `ENVIRONMENT=prod` and
`DEBUG=off`. Production uses the owner-only `.env` and direct Docker Compose
commands documented in `SELF_HOSTING.md`; it does not copy the development
template.

Keep secrets in environment variables only. Do not commit `.env`, API keys,
service account JSON, Stripe secrets, Sentry DSNs, or user dataset
contents.

## Architecture

- `rowset/settings.py` wires Django apps, allauth, storage, logging, Redis,
  Django Q, observability, payments, and AI model labels.
- `apps/datasets` owns dataset models, row storage, validation, exports, public
  previews, and dataset-specific tests.
- `apps/api` exposes REST endpoints and keeps API schemas/auth/service wrappers.
- `apps/mcp_server` exposes hosted MCP tools and bearer API-key auth.
- `apps/core` owns profiles, account state, feedback, email delivery, Stripe
  webhook handling, and shared helpers.
- `apps/pages` renders checked-in docs, tutorials, how-to guides, explanations,
  blog posts, marketing pages, and page context processors from root-level
  public routes. Blog Markdown lives in `apps/pages/content/blog`; there is no
  database-backed blog authoring path.
- `frontend/templates` contains Django templates for landing, authenticated app,
  datasets, pages content, account flows, and shared components.
- `frontend/src/js` contains Alpine component registration and small global
  browser enhancements.
- `scripts/build-assets.mjs` compiles Tailwind/PostCSS and copies vendor/static
  assets into `frontend/build`.
- `deployment`, Dockerfiles, Compose files, and Render config own deployment.

## Dataset Rules

- Agents create datasets through MCP or REST by sending headers and rows.
- Headers must be present, non-empty, and unique.
- Index values must be non-blank and unique unless Rowset generated the index.
- Generated index columns use `rowset_id` or the next available suffixed name.
- Stored row data is string-keyed by dataset headers.
- Semantic column metadata supports hidden column descriptions plus `text`,
  `tags`, `choice`, `integer`, `number`, `currency`, `boolean`, `date`, `datetime`,
  `email`, and `url` types.

## API And MCP Rules

- REST endpoints use bearer API-key auth as the preferred private API path.
- Enabled public datasets expose separate read-only metadata and row endpoints keyed by
  `public_key`; unprotected datasets need no credential, while protected requests require
  `X-Rowset-Public-Password` on every request.
- Private REST endpoints accept API keys only as `Authorization: Bearer <key>`.
- Hosted MCP uses bearer API-key auth. Configure MCP clients with
  `Authorization: Bearer <key>`, usually through a bearer-token environment
  variable such as `ROWSET_API_KEY`.
- For hosted MCP, use custom headers only when the client cannot set a bearer
  token; the custom header should still be `Authorization: Bearer <key>`.
- REST and MCP row operations must enforce the authenticated profile's ownership
  boundary.
- Public JSON responses must omit private dataset keys, ownership context, internal
  instructions and metadata, relationships, and authenticated asset URLs.
- Keep service-layer errors clear and convert them at the boundary: HTTP errors
  for REST and value errors for MCP tools.

## Frontend Rules

- Use Django templates for server-rendered pages.
- Use HTMX for server-rendered partial updates and form/list refreshes.
- Use Alpine.js for local browser state such as menus, dialogs, copy controls,
  inline toggles, and disabled/loading state.
- Put reusable Alpine components and small shared DOM enhancements in
  `frontend/src/js`.
- Global scripts or head snippets should live in shared components and be
  included by both `base_landing.html` and `base_app.html` when they apply
  globally.
- Keep long file names, headers, route paths, and API keys from breaking layout.
- Follow `DESIGN.md` for colors, typography, component style, and product feel.

## Testing Notes

- Prefer `make test` over host `pytest`.
- Use focused backend checks while iterating, then broaden to `make ci-local`
  before review when the change touches shared behavior or multiple surfaces.
- Dataset validation, API, MCP auth, export, and public-preview changes need
  focused tests.
- CLI changes need `make cli-test` and `make cli-build`, plus backend focused
  tests when the CLI requires a REST API surface change.
- Template-only changes can be checked with Django template loading and
  `manage.py check`, but asset-related work should also build or run the frontend
  stack.
