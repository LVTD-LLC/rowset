# Rowset

Rowset is a private MCP and REST backend for structured datasets that trusted AI
agents can create, inspect, update, export, and share. Users sign in, copy an
agent setup prompt, authorize a scoped API key, and let the agent work with
owned datasets through stable programmatic interfaces instead of browser
automation.

## Key Features

- Hosted Streamable HTTP MCP server for AI-agent workflows.
- Authenticated REST API for account checks, projects, datasets, rows, exports,
  relationships, image assets, and public preview settings.
- Go `rowset` under `cli/` for the same authenticated REST operations.
- API-backed datasets with stable headers, semantic column metadata, persistent
  agent instructions, JSON metadata, and an explicit index column.
- Row CRUD by internal Rowset row id or by dataset index value.
- Projects and project sections for organizing related datasets without changing
  authentication boundaries.
- Choice, reference, image, date, datetime, currency, number, boolean, email,
  URL, and text column metadata.
- Read-only public previews with optional password protection for human review.
- CSV, JSONL, XLSX, SQLite, and dashboard-oriented Parquet export paths.
- Private image asset storage on local disk or S3-compatible storage such as
  Cloudflare R2.
- Optional Qdrant-backed hybrid vector and lexical search for dataset rows.

## Table of Contents

- [Tech Stack](#tech-stack)
- [Product Boundaries](#product-boundaries)
- [Prerequisites](#prerequisites)
- [Getting Started](#getting-started)
- [Agent Golden Path](#agent-golden-path)
- [REST API Quick Start](#rest-api-quick-start)
- [CLI Quick Start](#cli-quick-start)
- [Architecture](#architecture)
- [Data Model](#data-model)
- [Environment Variables](#environment-variables)
- [Available Commands](#available-commands)
- [Testing](#testing)
- [Deployment](#deployment)
- [Troubleshooting](#troubleshooting)
- [Contributor Notes](#contributor-notes)

## Tech Stack

| Area | Technology |
| --- | --- |
| Language | Python 3.14.2 (`.python-version`, `pyproject.toml`) and Go for `cli/` |
| Backend | Django 6 |
| REST API | Django Ninja |
| MCP | FastMCP mounted through Starlette in `rowset/asgi.py` |
| Auth | Django allauth, session auth, API-key auth, hosted MCP bearer auth |
| Data stores | PostgreSQL, Redis |
| Background jobs | Django Q2 workers |
| Tabular work | Python `csv`, `json`, `sqlite3`, `zipfile`, plus Polars |
| Frontend | Django templates, HTMX, Alpine.js, Tailwind, PostCSS |
| Assets | Custom Node 24 build script in `scripts/build-assets.mjs` |
| Local stack | Docker Compose with Postgres, Redis, backend, workers, frontend, Mailhog, Stripe CLI, MJML, and MinIO |
| Observability | Sentry and PostHog |
| Integrations | Mailgun, Buttondown, Stripe, Chatwoot, S3-compatible storage, Qdrant/OpenRouter for optional vector search |
| Active deployment path | Docker images plus CapRover GitHub Actions |

## Product Boundaries

Rowset is intentionally centered on agent-managed datasets.

In scope:

- A signed-in user copies a Rowset setup prompt into a trusted agent.
- The agent stores the API key privately and connects to Rowset MCP with
  `Authorization: Bearer <key>`.
- The agent creates or discovers datasets, inspects schema/context, mutates rows,
  manages projects, exports snapshots, or enables a public preview when asked.
- The dashboard helps humans with setup, settings, recent dataset state, schema
  review, exports, public preview review, and account recovery.

Out of scope for the current product path:

- Rowset-owned source connectors, sync, or write-back.
- Public previews as authentication or as a substitute for REST/MCP access.
- Browser automation as the preferred agent integration.
- Broad BI, warehouse, or ETL orchestration promises.

Agents can still read local files, Google Sheets, databases, or other upstream
sources with their own capabilities, then send structured rows into Rowset
through MCP or REST.

## Prerequisites

For the supported local workflow:

- Docker Desktop or Docker Engine with Docker Compose.
- Git.
- A shell that can run `make`.

For host-side debugging outside Docker:

- Python 3.14.2.
- `uv`.
- Node.js 24.11 or newer and npm 11 or newer.
- Go 1.26 or newer when building the `rowset` CLI from source.
- PostgreSQL and Redis reachable from your environment.

Most contributors should start with Docker Compose. The local Compose stack
builds the Python image, installs Node dependencies in the frontend service, and
runs Postgres and Redis for you.

## Getting Started

### 1. Clone the repository

```bash
git clone https://github.com/LVTD-LLC/rowset.git
cd rowset
```

### 2. Create local environment configuration

```bash
cp .env.example .env
```

The checked-in defaults are designed for the local Docker Compose stack:

- Postgres host: `db`
- Postgres database/user/password: `rowset`
- Redis host: `redis`
- Redis password: `rowset`
- Site URL: `http://localhost:8000`
- Environment: `dev`
- Debug: `on`

Do not commit `.env`.

### 3. Start the full local stack

```bash
make serve
```

This runs:

- `docker compose -f docker-compose-local.yml up -d --build`
- backend logs for the `backend` service

The local stack includes:

| Service | Purpose | Local port |
| --- | --- | --- |
| `backend` | Django app and ASGI server | `8000` |
| `workers` | Django Q worker process | internal |
| `frontend` | PostCSS/Tailwind/asset watcher | internal |
| `db` | PostgreSQL | `5432` |
| `redis` | Redis | `6379` |
| `mailhog` | Local email capture | `1025`, `8025` |
| `stripe` | Optional Stripe webhook forwarding | internal |
| `mjml` | MJML HTTP renderer | `15500` |
| `minio` | Local S3-compatible storage | `9000`, `9001` |

Open the app at:

```text
http://localhost:8000
```

Mailhog is available at:

```text
http://localhost:8025
```

MinIO's console is available at:

```text
http://localhost:9001
```

### 4. Create an account

Use the local app UI to sign up. Email verification is non-blocking in the
current app: local confirmation links are captured by Mailhog or printed through
the configured email backend.

### 5. Create an agent API key

In the app:

1. Go to `Settings`.
2. Create an agent API key.
3. Use the smallest permission level that fits the agent:
   - `Read` for inspection and exports.
   - `Read + write` for dataset, row, project, relationship, and public preview
     changes.
   - `Admin` only when automation must create more agent API keys.

The dashboard and settings pages generate a copyable agent setup prompt. The
preview masks the key; the copy endpoint returns the full key and uses
`Cache-Control: no-store`.

### 6. Verify the golden path

For local development, the setup values are:

```text
Rowset MCP URL: http://localhost:8000/mcp/
Rowset REST API base: http://localhost:8000/api/
Rowset skill: http://localhost:8000/SKILL.md
```

Store the copied API key in a private environment variable:

```bash
export ROWSET_API_KEY="replace-with-your-copied-key"
```

Verify REST authentication:

```bash
curl -H "Authorization: Bearer $ROWSET_API_KEY" \
  http://localhost:8000/api/user
```

## Agent Golden Path

Rowset's primary workflow is agent handoff, not manual row editing.

Recommended agent startup order:

1. Read the Rowset setup prompt.
2. Store the full API key privately as `ROWSET_API_KEY`.
3. Configure the remote MCP server with bearer-token auth.
4. Discover live MCP tools and schemas from the connected server.
5. Call `get_user_info` to verify authentication.
6. Call `get_rowset_capabilities` for the current feature guide.
7. Call `get_all_datasets`, `get_archived_datasets`, or `search_datasets`
   before creating duplicates.
8. Call `get_dataset` before row operations so the agent sees headers, index
   column, semantic schema, dataset instructions, metadata, and relationships.

For Codex/OpenClaw-compatible clients:

```bash
codex mcp add rowset \
  --url http://localhost:8000/mcp/ \
  --bearer-token-env-var ROWSET_API_KEY
```

For production, replace the URL with:

```text
https://rowset.lvtd.dev/mcp/
```

Do not put the raw API key in the MCP server config. Store the key in the
agent's private runtime environment or secret store and configure the client to
send:

```http
Authorization: Bearer <key>
```

### MCP tool groups

The live MCP server is the exact source for tool schemas. The current workflow
groups are:

| Workflow | Representative MCP tools |
| --- | --- |
| Account and setup | `get_user_info`, `get_rowset_capabilities` |
| API keys | `create_agent_api_key` |
| Dataset discovery | `get_all_datasets`, `get_archived_datasets`, `search_datasets`, `get_dataset` |
| Dataset creation/context | `create_dataset`, `update_dataset_metadata`, `update_dataset_column_types` |
| Projects | `get_all_projects`, `search_projects`, `create_project`, `get_project`, `get_project_sections`, `create_project_section`, `update_project`, `update_project_metadata`, `update_project_section`, `archive_project_section`, `archive_project`, `update_dataset_project` |
| Rows | `list_dataset_rows`, `search_dataset_rows`, `get_dataset_row`, `get_dataset_row_by_index`, `create_dataset_row`, `update_dataset_row`, `update_dataset_row_by_index`, `delete_dataset_row` |
| Schema changes | `add_column`, `rename_column`, `drop_column`, `reorder_columns` |
| Relationships | `list_dataset_relationships`, `create_dataset_relationship`, `resolve_dataset_relationship`, `delete_dataset_relationship` |
| Image assets | `attach_image_to_dataset_row`, `get_dataset_image_asset` |
| Public previews | `update_dataset_public_preview` |
| Archive/restore | `archive_dataset`, `restore_dataset` |

Agents should ask before destructive actions such as row deletion, dataset
archive, project archive, or clearing a public preview password unless the user
explicitly requested that action.

### Canonical task-board example

A useful Rowset dogfood pattern is a task board indexed by `task_id`:

```json
{
  "name": "Agent Task Board",
  "description": "Durable task board for one agent workflow",
  "instructions": "Keep task_id stable. Move status to done only after definition_of_done is satisfied.",
  "metadata": {
    "status_order": ["todo", "doing", "blocked", "review", "done"],
    "priority_meaning": {
      "P0": "Highest leverage or blocking",
      "P1": "Important current-cycle work"
    }
  },
  "headers": [
    "task_id",
    "status",
    "priority",
    "task",
    "definition_of_done",
    "owner",
    "updated_on",
    "notes"
  ],
  "index_column": "task_id",
  "column_types": {
    "task_id": "text",
    "status": {
      "type": "choice",
      "choices": ["todo", "doing", "blocked", "review", "done"]
    },
    "priority": {
      "type": "choice",
      "choices": ["P0", "P1", "P2", "P3"]
    },
    "updated_on": "date"
  }
}
```

That shape demonstrates the Rowset core: stable index, choice metadata,
persistent instructions, JSON conventions, and updates by index.

## REST API Quick Start

The REST API base is:

```text
http://localhost:8000/api/
```

In production, it is:

```text
https://rowset.lvtd.dev/api/
```

Generated API docs are served from:

```text
/api/docs
```

Use bearer auth for private REST requests:

```http
Authorization: Bearer <key>
```

`X-API-Key` and `?api_key=` are compatibility fallbacks for clients that cannot
send bearer tokens.

### Verify a key

```bash
curl -H "Authorization: Bearer $ROWSET_API_KEY" \
  http://localhost:8000/api/user
```

### Create a dataset

```bash
curl -X POST http://localhost:8000/api/datasets \
  -H "Authorization: Bearer $ROWSET_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Products",
    "description": "Supplier catalog managed by an agent",
    "instructions": "Keep sku stable. Treat price as USD unless a row says otherwise.",
    "headers": ["sku", "name", "price", "status"],
    "index_column": "sku",
    "column_types": {
      "sku": "text",
      "name": "text",
      "price": "currency",
      "status": {
        "type": "choice",
        "choices": ["draft", "active", "retired"]
      }
    },
    "rows": [
      {"sku": "A-1", "name": "Adapter", "price": "19.99", "status": "active"}
    ]
  }'
```

### List rows

```bash
curl -H "Authorization: Bearer $ROWSET_API_KEY" \
  "http://localhost:8000/api/datasets/{dataset_key}/rows"
```

### Update a row by index

```bash
curl -X PATCH \
  "http://localhost:8000/api/datasets/{dataset_key}/rows/by-index?index_value=A-1" \
  -H "Authorization: Bearer $ROWSET_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"data": {"status": "retired"}}'
```

### Export a snapshot

```bash
curl -H "Authorization: Bearer $ROWSET_API_KEY" \
  "http://localhost:8000/api/datasets/{dataset_key}/export.csv" \
  -o dataset.csv
```

REST export endpoints include:

- `GET /api/datasets/{dataset_key}/export.csv`
- `GET /api/datasets/{dataset_key}/export.jsonl`
- `GET /api/datasets/{dataset_key}/export.xlsx`
- `GET /api/datasets/{dataset_key}/export.sqlite`

Parquet export is available from the authenticated dashboard export menu, not
through the REST API endpoints above.

## CLI Quick Start

The Go CLI lives under `cli/` and uses the same bearer-authenticated REST API
paths as the docs above. Install the latest published CLI in one command:

```bash
curl -fsSL https://github.com/LVTD-LLC/rowset/releases/latest/download/install-rowset-cli.sh | sh
```

The installed command is `rowset`. It defaults to production:

```text
https://rowset.lvtd.dev/api/
```

Store your private API key and verify authentication:

```bash
export ROWSET_API_KEY="replace-with-your-copied-key"
rowset user info
rowset capabilities
```

For local development, override the API base:

```bash
export ROWSET_API_BASE="http://localhost:8000/api/"
rowset user info
```

Create a dataset and patch a row by index:

```bash
rowset dataset create \
  --name Products \
  --headers sku,name,price,status \
  --index-column sku \
  --row '{"sku":"A-1","name":"Adapter","price":"19.99","status":"active"}'

rowset row update-by-index "{dataset_key}" A-1 \
  --data '{"status":"retired"}'
```

Build or test it from the repo root:

```bash
make cli-test
make cli-build
```

See [`cli/README.md`](cli/README.md) for the full command list and examples.

## Architecture

### Directory structure

```text
.
|-- rowset/                    # Django settings, URLs, ASGI/WSGI, storage, logging, sitemap
|-- apps/
|   |-- core/                  # Profiles, agent API keys, setup prompt, billing, feedback, email
|   |-- api/                   # Django Ninja API, auth, schemas, thin REST views, API services
|   |-- mcp_server/            # FastMCP server, MCP bearer auth, MCP tools and tests
|   |-- datasets/              # Dataset models, services, views, exports, assets, vector search
|   |-- docs/                  # In-app Markdown docs and navigation
|   |-- pages/                 # Landing, pricing, legal, use-case pages
|   `-- blog/                  # Markdown-backed blog posts, services, views, and checks
|-- frontend/
|   |-- templates/             # Django templates for public and authenticated pages
|   |-- src/js/                # Alpine component registration and browser enhancements
|   |-- src/styles/            # Tailwind/PostCSS source CSS
|   `-- vendors/               # Vendored frontend assets copied into the build
|-- cli/                       # Go rowset module and tests
|-- scripts/build-assets.mjs   # Frontend asset build and watch script
|-- deployment/                # CapRover Dockerfile, entrypoint, and healthcheck
|-- docker-compose-local.yml   # Local development stack
|-- docker-compose-prod.yml    # Production Compose stack using GHCR images
|-- docker-compose-test.yml    # Compose overrides for test runs
|-- pyproject.toml             # Python dependencies and tooling config
|-- package.json               # Frontend build/lint dependencies
|-- Makefile                   # Supported local commands
`-- .github/workflows/         # CI, ReviewGate, CapRover deploy workflows
```

### Request lifecycle

1. HTTP traffic enters the ASGI app in `rowset/asgi.py`.
2. `/mcp` redirects to `/mcp/`.
3. `/mcp/` is handled by the FastMCP HTTP app.
4. All other paths are mounted into Django.
5. Django routes public pages, account views, dataset UI, docs, and `/api/`.
6. REST requests hit Django Ninja routes in `apps/api/views.py`.
7. Views authenticate the user/profile and call shared services.
8. Shared dataset behavior lives in `apps/api/services.py` and
   `apps/datasets/services.py`.
9. Responses are serialized for REST, MCP, or templates at the boundary.

### MCP flow

```text
Agent
  -> Streamable HTTP MCP client
  -> /mcp/ with Authorization: Bearer <ROWSET_API_KEY>
  -> apps.mcp_server.auth
  -> apps.mcp_server.server tool
  -> shared API/dataset services
  -> PostgreSQL/Redis/storage
```

MCP tool bodies should stay thin: authenticate, call services, convert service
errors, and return structured data.

### REST flow

```text
Client or agent
  -> /api/... with Authorization: Bearer <ROWSET_API_KEY>
  -> apps.api.auth
  -> apps.api.views endpoint
  -> apps.api.services and apps.datasets.services
  -> PostgreSQL/Redis/storage
```

REST and MCP should reuse service functions so dataset validation, ownership,
row rules, and error handling stay aligned.

### Frontend flow

```text
Browser
  -> Django template view
  -> frontend/templates
  -> static assets from frontend/build
  -> HTMX for partial server round trips
  -> Alpine.js for local browser state
```

The asset build:

1. Reads `frontend/src/styles/index.css`.
2. Runs PostCSS import, Tailwind, Autoprefixer, and cssnano in production.
3. Copies `frontend/src/js`.
4. Copies vendored assets and Alpine.
5. Writes `frontend/build/manifest.json`.

## Data Model

Core entities:

| Model | Purpose |
| --- | --- |
| `Profile` | Rowset account state for a Django user. Owns datasets, projects, keys, feedback, and billing state. |
| `AgentApiKey` | Scoped API key record. Stores a prefix, token hash, encrypted token ciphertext, access level, and revocation state. |
| `Project` | User-owned grouping for related datasets. Carries description and JSON metadata. |
| `ProjectSection` | Optional grouping inside one project. Does not affect access control. |
| `Dataset` | The central object: headers, column schema, index column, context, rows, preview settings, project link, and archive state. |
| `DatasetRow` | One row of data. Stores `row_number`, `index_value`, and JSON data keyed by dataset headers. |
| `DatasetRelationship` | Simple foreign-key-style link from one source dataset column to another dataset's index values. |
| `DatasetAsset` | Private image asset attached to one image column on one row. Row cells store `asset:{key}` references. |
| `DatasetMutation` | Audit-style record of dataset, row, schema, asset, and public preview changes. |

Important rules:

- Headers must be present, non-empty, and unique.
- If an index column is supplied, index values must be non-blank and unique.
- If no reliable index exists, omit `index_column`; Rowset generates `rowset_id`.
- Stored row data is string-keyed by dataset headers.
- Choice cells can be blank, but non-blank values must match configured choices.
- Reference columns store canonical Rowset dataset or project keys.
- Relationships point to active datasets in the same account.
- Public previews are read-only browser views, not API authentication.
- Archived datasets keep rows and schema metadata recoverable.

## Environment Variables

Copy `.env.example` to `.env` for local development:

```bash
cp .env.example .env
```

### Required

| Variable | Description | Local default |
| --- | --- | --- |
| `ENVIRONMENT` | `dev` locally, `prod` in production. | `dev` |
| `DEBUG` | Use `on`/truthy locally and `off`/false in production. | `on` |
| `SECRET_KEY` | Django signing secret. Generate a strong value for production. | `super-secret-key` |
| `SITE_URL` | Absolute public site URL used for links, CSRF, docs, MCP URL, and setup prompt. | `http://localhost:8000` |
| `POSTGRES_DB` | PostgreSQL database name. | `rowset` |
| `POSTGRES_USER` | PostgreSQL username. | `rowset` |
| `POSTGRES_PASSWORD` | PostgreSQL password. | `rowset` |
| `POSTGRES_HOST` | PostgreSQL host. Use `db` inside Compose. | `db` |
| `POSTGRES_PORT` | PostgreSQL port. | `5432` |
| `REDIS_HOST` | Redis host. Use `redis` inside Compose. | `redis` |
| `REDIS_PASSWORD` | Redis password. | `rowset` |
| `REDIS_PORT` | Redis port. | `6379` |

### Account and auth

| Variable | Description |
| --- | --- |
| `ALLOW_SIGNUPS` | Set to `False` to pause new signups while keeping existing logins available. |
| `GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET` | Optional GitHub social login. |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | Optional Google social login. |

### Dataset assets

Leave `ROWSET_ASSET_S3_ENDPOINT_URL` blank to store private dataset image assets
on the production Compose host's `private_media_data` volume. The backend and
workers share that volume. Django's default media storage uses the separate
`media_data` volume.

| Variable | Description |
| --- | --- |
| `ROWSET_ASSET_S3_ENDPOINT_URL` | S3-compatible endpoint, such as Cloudflare R2. |
| `ROWSET_ASSET_STORAGE_BUCKET_NAME` | Bucket name for private dataset image assets. Required when endpoint is set. |
| `ROWSET_ASSET_ACCESS_KEY_ID` | S3/R2 access key id. Required when endpoint is set. |
| `ROWSET_ASSET_SECRET_ACCESS_KEY` | S3/R2 secret access key. Required when endpoint is set. |
| `ROWSET_ASSET_REGION_NAME` | Region name. Use `auto` for Cloudflare R2. |

### Email, support, and marketing

| Variable | Description |
| --- | --- |
| `MAILGUN_API_KEY` | Enables Mailgun transactional email. Empty uses console email fallback outside local SMTP. |
| `MAILGUN_SENDER_DOMAIN` | Optional Mailgun sender domain. Defaults to `mg.lvtd.dev` in settings. |
| `BUTTONDOWN_API_KEY` | Optional Buttondown integration. |
| `ROWSET_FEEDBACK_APPRISE_URLS` | Optional comma-separated Apprise URLs for feedback notifications. |
| `ROWSET_FEEDBACK_APPRISE_TITLE` | Optional Apprise notification title for feedback submissions. |
| `CHATWOOT_BASE_URL` | Optional Chatwoot support widget base URL. |
| `CHATWOOT_WEBSITE_TOKEN` | Optional Chatwoot website inbox token. |
| `CHATWOOT_HMAC_SECRET` | Optional Chatwoot identity validation secret. |

### Billing

| Variable | Description |
| --- | --- |
| `STRIPE_SECRET_KEY` | Stripe secret key for Checkout, Portal, and webhooks. |
| `STRIPE_CONTEXT` | Optional Stripe Organization account context. |
| `STRIPE_WEBHOOK_SECRET` | Stripe webhook signing secret. |
| `STRIPE_PRICE_ID_ROWSET_PRO_MONTHLY` | Price id for the Rowset Pro monthly plan. |
| `WEBHOOK_UUID` | Read into settings as `STRIPE_WEBHOOK_UUID`, but currently not used by routing; the Stripe webhook path is fixed at `/stripe-webhook/`. |
| `STRIPE_PUBLISHABLE_KEY` | Present in `.env.example`; only needed if client-side Stripe.js is wired in. |

### Vector search

Vector search is optional. PostgreSQL remains the source of truth; Qdrant is a
rebuildable retrieval index.

| Variable | Description |
| --- | --- |
| `ROWSET_VECTOR_SEARCH_ENABLED` | Set to `True` only after Qdrant and embeddings are configured. |
| `QDRANT_URL` | Qdrant HTTP URL. |
| `QDRANT_API_KEY` | Qdrant API key, if required. |
| `QDRANT_COLLECTION_PREFIX` | Prefix for Rowset-managed Qdrant collections. |
| `QDRANT_TIMEOUT_SECONDS` | Qdrant request timeout. |
| `ROWSET_EMBEDDING_MODEL` | Embedding model. Default is `openai/text-embedding-3-small`. |
| `ROWSET_EMBEDDING_DIMENSIONS` | Embedding dimension count. Default is `1536`. |
| `OPENROUTER_BASE_URL` | OpenRouter API base URL for embeddings. |
| `OPENROUTER_API_KEY` | Required when vector search is enabled. |
| `OPENAI_API_KEY` | Optional key for code paths that use OpenAI directly. |

Backfill an existing active dataset after vector search is configured:

```bash
make manage backfill_dataset_vectors <dataset_key> --dry-run
make manage backfill_dataset_vectors <dataset_key>
```

### Observability and runtime

| Variable | Description |
| --- | --- |
| `SENTRY_DSN` | Enables Sentry in production. |
| `SENTRY_RELEASE` | Optional release identifier. |
| `SENTRY_TRACES_SAMPLE_RATE` | Sentry trace sample rate. |
| `SENTRY_PROFILE_SESSION_SAMPLE_RATE` | Sentry profiling sample rate. |
| `SENTRY_ENABLE_LOGS` | Enables Sentry structured logs. |
| `SENTRY_ENABLE_METRICS` | Enables Sentry request metrics middleware. |
| `SENTRY_SEND_DEFAULT_PII` | Defaults false. Only enable if your privacy policy allows it. |
| `SENTRY_INCLUDE_LOCAL_VARIABLES` | Defaults false to avoid capturing secrets. |
| `SENTRY_MAX_BREADCRUMBS` | Max Sentry breadcrumbs. |
| `POSTHOG_API_KEY` | PostHog `phc_` project token for analytics and log ingestion. |
| `POSTHOG_HOST` | PostHog regional ingestion host. Defaults to the US host. |
| `POSTHOG_LOGS_ENABLED` | Enables batched OTLP log export; production defaults on when a token exists. |
| `POSTHOG_LOG_LEVEL` | Minimum level exported to PostHog. Defaults to `INFO`. |
| `POSTHOG_SERVICE_NAME` | Optional OTel service-name override for PostHog facets. |
| `APP_PROCESS_TYPE` | Set to `worker` when process auto-detection is unavailable. |
| `DJANGO_LOG_LEVEL` | Production logger level for the `rowset` logger. |
| `MJML_URL` | MJML HTTP server URL, local default `http://mjml:15500`. |
| `REDIS_DB` | Redis database number. Defaults to `0` in settings. |

#### Structured application logs

Rowset uses structlog key-value calls internally. Keep the event name stable and attach queryable
scalar attributes as keyword arguments:

```python
logger.info(
    "dataset.search.completed",
    dataset_id=dataset.id,
    duration_ms=duration_ms,
    outcome="success",
)
```

Standard-library loggers are supported too. Use Python's `extra` argument (not `extra_data`) so
OpenTelemetry exports the values as log attributes:

```python
logger.info(
    "dataset search completed",
    extra={"event": "dataset.search.completed", "dataset_id": dataset.id},
)
```

PostHog receives a string body plus flat OTel attributes in both cases. Only strings, booleans,
integers, finite floats, enums, and UUIDs are exported. Never log credentials, request or response
bodies, query text, email addresses, or user-owned dataset contents.

## Available Commands

Use the Makefile commands unless you are intentionally debugging the host
environment.

| Command | Description |
| --- | --- |
| `make serve` | Build and start the local Docker Compose stack, then follow backend logs. |
| `make shell` | Open Django `shell_plus` inside the backend container. |
| `make manage <command>` | Run a Django management command inside the backend container. |
| `make makemigrations` | Run Django migration generation in the backend container. |
| `make migrate` | Apply migrations in the backend container. |
| `make test` | Run pytest through Docker Compose. |
| `make test apps/datasets/tests/test_csv_datasets.py` | Run a focused test file. |
| `make test -- -k dataset -q` | Pass pytest flags through the Makefile. |
| `make cli-test` | Run Go tests for the Rowset CLI. |
| `make cli-build` | Build the Go `rowset` binary under `cli/bin/`. |
| `make restart-worker` | Recreate the `workers` service. |
| `npm run build` | Build frontend assets on the host. |
| `npm run start` | Watch and rebuild frontend assets on the host. |
| `npm run watch` | Alias for the asset watcher. |
| `npm run lint` | Lint frontend JS and build scripts. |

Useful direct Docker commands:

```bash
docker compose -f docker-compose-local.yml ps
docker compose -f docker-compose-local.yml logs backend
docker compose -f docker-compose-local.yml logs workers
docker compose -f docker-compose-local.yml down
```

## Testing

The supported test path is Docker-backed:

```bash
make test
```

Run focused tests while iterating:

```bash
make test apps/mcp_server/tests/test_server.py
make test apps/api/tests.py
make test apps/datasets/tests/test_csv_datasets.py
make test -- -k public_preview -q
```

Before PRs that touch backend behavior, run at least:

```bash
make test
```

For frontend changes:

```bash
npm run build
npm run lint
```

For CLI changes:

```bash
make cli-test
make cli-build
```

### Verification

- Current local CI-equivalent path: `make ci-local`
- Focused backend tests: `make test apps/datasets/tests/test_csv_datasets.py`
- Focused pytest flags: `make test -- -k dataset -q`
- Migration check: `make migrations-check`
- Django system checks: `make django-check`
- Python lint and format checks: `make lint-python` and `make format-check`
- Frontend checks: `make frontend-install`, then `make frontend-check`
- CLI checks: `make cli-test` and `make cli-build`
- Optional coverage inspection: `make coverage -- <pytest args>`

### CI

GitHub Actions at `.github/workflows/ci.yml` runs on pull requests.

It boots Postgres + Redis, creates the dummy frontend manifest needed by tests,
then runs the same Makefile targets as local verification with host-runner
overrides. CI keeps the backend test suite in one process; `make ci-local`
splits the same suite by app to reduce Docker memory pressure:

- `make migrations-check CHECK_PYTHON_RUN="uv run python"`
- `make django-check CHECK_PYTHON_RUN="uv run python"`
- `make test PYTEST_RUN="uv run pytest" -- -q`

CI tests against PostgreSQL 18 (`rasulkireev/custom-postgres:18`), while
`docker-compose-prod.yml` currently uses PostgreSQL 17
(`rasulkireev/custom-postgres:17`). Keep that version split in mind for
database behavior until the stacks are aligned.

ReviewGate is present but temporarily disabled.

## Deployment

### Docker Compose production

`docker-compose-prod.yml` runs five services:

- `caddy`
- `db`
- `redis`
- `backend`
- `workers`

On a server, fetch the repository files first so `docker-compose-prod.yml` and the production
environment commands are present:

```bash
git clone https://github.com/LVTD-LLC/rowset.git
cd rowset
```

Published Rowset images support `linux/amd64` and `linux/arm64`. Select a
release or full Git SHA tag, then verify that its manifest contains the current
server architecture. Docker Buildx is required for this inspection.

```bash
export ROWSET_IMAGE=ghcr.io/lvtd-llc/rowset:<release-or-sha-tag>
deployment/verify-image-platforms.sh "$ROWSET_IMAGE"
```

The command rejects unsupported host architectures and image tags whose manifest does not contain
the host platform. Set the hostname, then initialize and validate the protected production file:

```bash
export ROWSET_DOMAIN=rowset.example.com
deployment/self-host/init-env.sh
deployment/self-host/validate-env.sh
```

The initializer uses `deployment/self-host/env.example`, generates independent strong secrets, and
preserves them on reruns. Start through the validation gate:

```bash
deployment/self-host/start.sh
```

The production stack mounts the named `media_data` and `private_media_data`
volumes into both the backend and workers. They survive container recreation,
but `docker compose down -v` deletes them. Back up both local volumes with:

```bash
deployment/self-host/backup-local-media.sh /var/backups/rowset
```

The resulting archive is media-only; pair it with a PostgreSQL backup and copy
both off the host. See [SELF_HOSTING.md](SELF_HOSTING.md#persistent-media-and-backups)
for local-versus-S3 storage details and recovery cautions.

Caddy is the only public ingress on ports 80 and 443. It obtains and renews the
certificate for `ROWSET_DOMAIN`, redirects HTTP to HTTPS, and proxies to the
backend over the private Compose network. Compose derives the production
`SITE_URL`; backend port 8000 is not published.

Follow [SELF_HOSTING.md](SELF_HOSTING.md) for DNS and firewall prerequisites,
automatic HTTPS verification, REST/MCP smoke checks, backups, updates, and the
explicit temporary IP-only diagnostic override.

### CapRover production

The active push-to-main deployment path is:

- `.github/workflows/deploy.yml`

The tag-based publishing path is:

- `.github/workflows/publish.yml`

Use a UTC dotted-day tag with an incrementing suffix:

```bash
release_tag="$(scripts/next-release-tag.sh)"
git tag "$release_tag"
git push origin "$release_tag"
```

For example, the first release on July 8, 2026 is `2026.07.08-0`; a second
release that day is `2026.07.08-1`.

Publishing a tag builds the app Docker image for `linux/amd64` and
`linux/arm64`, publishes one multi-platform manifest, and builds CLI artifacts
with the same release tag. The image is pushed to GHCR as:

```text
ghcr.io/lvtd-llc/rowset:2026.07.08-0
```

The workflow also creates or updates the matching GitHub Release with:

- `rowset_linux_amd64.tar.gz`
- `rowset_linux_arm64.tar.gz`
- `rowset_darwin_amd64.tar.gz`
- `rowset_darwin_arm64.tar.gz`
- `install-rowset-cli.sh`
- `checksums.txt`

The release workflow verifies the manifest and executes the published release
image on both architectures. The main-branch deployment workflow performs the
same checks before deploying the full Git SHA tag to the `rowset` and
`rowset-workers` CapRover apps:

- `ghcr.io/lvtd-llc/rowset:<full-git-sha>`

Each push to `main` also publishes:

- a UTC date alias such as `2026-07-01`
- an immutable run-number tag such as `2026-07-01.123`
- the full Git commit SHA traceability tag

The plain date tag is a daily alias and can move if there is more than one
release on the same UTC day. Pin the run-number tag, publish tag, or SHA tag for
rollbacks and reproducible self-hosted deployments. CapRover production deploys
the current build's full Git commit SHA tag.

CapRover pulls the published image from GHCR during deployment. Before
switching production to these workflows, make sure either:

- the `ghcr.io/lvtd-llc/rowset` package is public after its first publish, or
- the CapRover host has a `ghcr.io` registry credential with package read access
  configured.

The `rowset` and `rowset-workers` CapRover apps run the same image. Production
apps must set `APP_PROCESS_TYPE`:

- `rowset`: `APP_PROCESS_TYPE=server`
- `rowset-workers`: `APP_PROCESS_TYPE=worker`

Required GitHub secrets:

| Secret | Used by | Description |
| --- | --- | --- |
| `CAPROVER_SERVER` | server and workers | CapRover server URL. |
| `APP_TOKEN` | server | CapRover deploy token for the `rowset` app. |
| `WORKERS_APP_TOKEN` | workers | CapRover deploy token for the `rowset-workers` app. |

The workflow deploys on pushes to `main`.

The production Dockerfile:

1. Build frontend assets with Node 24.
2. Build a Python 3.14 runtime.
3. Install Python dependencies with `uv sync --locked --no-dev --no-install-project`.
4. Copy `frontend/build` from the Node build stage.
5. Run `deployment/entrypoint.sh`.

The server entrypoint waits for the database, collects static files, runs
migrations, then starts:

```bash
gunicorn rowset.asgi:application \
  --bind 0.0.0.0:80 \
  --workers 3 \
  --worker-class uvicorn_worker.UvicornWorker
```

The worker entrypoint waits for the database, then starts:

```bash
python manage.py qcluster
```

### Render blueprint

The repository includes `render.yaml`, but the current blueprint still
references `requirements.txt`, while
the repository now uses `pyproject.toml` and `uv`. Treat the Render blueprint as
present but not the primary verified deployment path until it is updated and
tested against the current Python 3.14/uv setup.

### Manual host deployment

Manual host deployment is useful for debugging but is not the preferred
production path.

Install dependencies:

```bash
uv sync --no-dev
npm ci
npm run build
```

Run setup commands:

```bash
uv run python manage.py collectstatic --noinput
uv run python manage.py migrate
```

Run the server:

```bash
uv run gunicorn rowset.asgi:application \
  --bind 0.0.0.0:8000 \
  --workers 3 \
  --worker-class uvicorn_worker.UvicornWorker
```

Run workers separately:

```bash
uv run python manage.py qcluster
```

You must also provide PostgreSQL, Redis, HTTPS termination, static/media
storage, process supervision, and secret management.

## Troubleshooting

### `make serve` starts but the page has missing CSS

The backend waits for `frontend/build/manifest.json`, but local volumes can
still get into a stale state. Rebuild assets:

```bash
docker compose -f docker-compose-local.yml restart frontend
docker compose -f docker-compose-local.yml logs frontend
```

Or build on the host:

```bash
npm install
npm run build
```

### Database connection errors

Check the Postgres service:

```bash
docker compose -f docker-compose-local.yml ps db
docker compose -f docker-compose-local.yml logs db
```

For local Compose, `.env` should use:

```text
POSTGRES_HOST=db
POSTGRES_DB=rowset
POSTGRES_USER=rowset
POSTGRES_PASSWORD=rowset
```

### Redis connection errors

Check the Redis service:

```bash
docker compose -f docker-compose-local.yml ps redis
docker compose -f docker-compose-local.yml logs redis
```

For local Compose, `.env` should use:

```text
REDIS_HOST=redis
REDIS_PASSWORD=rowset
REDIS_PORT=6379
```

### MCP authentication fails

Confirm the agent runtime has the full key:

```bash
printenv ROWSET_API_KEY
```

Do not paste the key into logs or public chat. In MCP clients, configure the
bearer-token env-var field to `ROWSET_API_KEY`; do not configure the visible key
prefix.

Then verify REST with:

```bash
curl -H "Authorization: Bearer $ROWSET_API_KEY" \
  http://localhost:8000/api/user
```

### REST returns the landing page for an API path

Use `/api/`, not the legacy `/api/v1/` path. Unknown API paths are handled as
JSON 404s by the current URL configuration.

### `manage.py check` warns about missing frontend assets

Build assets:

```bash
npm run build
```

In CI, a dummy manifest is created because backend tests do not exercise the
compiled frontend.

### Vector search raises configuration errors

Vector search requires all of the following:

- `ROWSET_VECTOR_SEARCH_ENABLED=True`
- `QDRANT_URL`
- `OPENROUTER_API_KEY`
- `OPENROUTER_BASE_URL`
- compatible `ROWSET_EMBEDDING_MODEL` and `ROWSET_EMBEDDING_DIMENSIONS`

Keep `ROWSET_VECTOR_SEARCH_ENABLED=False` until those services are ready.

### Public preview confusion

Public previews are browser pages for human review. They are read-only and may
be password-protected, but they are not API authentication. Agents and systems
should use REST or MCP with bearer API-key auth.

## Contributor Notes

- Read `AGENTS.md`, `PRODUCT.md`, `TECH.md`, `STRUCTURE.md`, `VISION.md`, and
  `DESIGN.md` before changing product behavior.
- Public checked-in docs, tutorials, how-to guides, explanations, and blog
  Markdown live under `apps/pages/content`.
- Keep reusable dataset behavior in services, not views, templates, or MCP tool
  bodies.
- Keep REST and MCP behavior aligned by reusing service functions.
- Keep private authenticated dataset access as the default.
- Do not print API keys, OAuth tokens, raw secrets, or private dataset contents
  into logs, docs, screenshots, commits, or final messages.
- Do not hand-write migrations. Change models first, then run
  `make makemigrations`.
- Prefer focused tests first, then broaden when changing shared services, auth,
  dataset rows, API, or MCP behavior.
