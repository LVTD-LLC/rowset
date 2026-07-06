# Changelog
All notable changes to this project will be documented in this file.

Entries are grouped by calendar date, newest first, and use the change types from
[Keep a Changelog](https://keepachangelog.com/en/1.0.0/). Versioned releases,
when used, still try to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
The date grouping also places older bullets under the most accurate change type
for that date while preserving their original text. Dates represent when the
changelog entry landed in git history, not a production deployment or release
cut date.

## Types of changes

**Added** for new features.
**Changed** for changes in existing functionality.
**Deprecated** for soon-to-be removed features.
**Removed** for now removed features.
**Fixed** for any bug fixes.
**Security** in case of vulnerabilities.

## 2026-07-06

### Added
- Added Markdown-backed use-case pages under `/use-cases/` with a standalone Use Cases navbar link.
- Added the Google Sheets alternatives article as a Markdown blog post for AI-agent-managed datasets, with a verified SEO brief and inbound links from related blog posts.

### Changed
- Simplified the docs sidebar to Getting started, Features, and Reference, and removed use cases from the docs navigation.
- Changed `/docs/` into a permanent redirect to the quickstart and grouped the docs sidebar by Start, Build, Use Cases, Reference, and Operate on every docs page.
- Reworked public Rowset docs into a docs-first, user-job information architecture with grouped Start, Build, Use Cases, Reference, and Operate pages, plus redirects from the older tutorial/how-to/explanation paths.

## 2026-07-05

### Added
- Added the Airtable alternatives article as a Markdown blog post for AI-agent-managed datasets, with current source links and inbound links from related blog posts.
- Added a Rowset blog post on choosing stable index columns for agent-managed rows, with inbound links from dataset docs, MCP docs, and existing agent workflow posts.
- Added a Rowset blog post explaining when AI-agent workflows should use MCP versus REST, with inbound links from MCP, Agent access, and the agent-managed-datasets article.

### Changed
- Moved the Airtable alternatives SEO target from a bespoke `/alternatives/airtable/` page to `/blog/airtable-alternatives` and redirected the old URL.

## 2026-07-04

### Added
- Added the `/playbooks/database-mcp-server` SEO playbook with Article/Breadcrumb schema, sitemap coverage, and internal links from MCP and Dataset API docs.
- Added the first SEO content article, defining agent-managed datasets and linking it into the MCP and Dataset API docs.
- Added the Rowset SEO sprint foundation with a measured GSC/Plausible/PostHog/DataForSEO-backed roadmap, brand context, keyword research cache, and internal-link inventory for phased organic-search work.

## 2026-07-03

### Fixed
- Added a dynamic `/robots.txt` view, canonical redirects for key trailing-slashed marketing URLs, sitemap responses without app-level `X-Robots-Tag`, and reusable JSON-LD schema helpers.
- MCP row listing and row search tools now tolerate agent-supplied `null` pagination values and JSON-string row filters, avoiding Pydantic validation failures before the request reaches Rowset's structured service errors.

## 2026-07-02

### Changed
- Strengthened the SEO internal-link spine between homepage, use-case pages, Dataset API docs, MCP docs, pricing, and commercially useful use cases.
- Dataset browser views now render URL-looking string cell values as plain text instead of auto-converting them into Rowset or external links. Explicit dataset relationship/reference columns, row-detail links, and image links still render as links; arbitrary URL strings can be copied from the cell text and link rendering can be reintroduced later with safer, explicit column-level behavior.
- Extracted public-preview settings and session-token helpers out of the API service kernel while preserving REST, MCP, and browser-preview behavior.

### Fixed
- Agent feedback submissions now append to the configured Rowset feedback dataset instead of each submitter's own dataset.
- Dataset detail pages now ignore non-URL JSON-array-looking cell values before Rowset link normalization, avoiding 500s for result rows with values such as `[]`.
- Production Docker healthchecks now run through the project virtualenv and allow enough startup time for GHCR image rollouts.

### Removed
- Removed forced quality and typing scaffolding from CI, local checks, docs, and Makefile targets.

## 2026-07-01

### Added
- Added Rowset Pro billing copy/configuration for a single $50/month plan and enforced free-account dataset quotas through shared REST/MCP services.
- Added shared Rowset dataset test factories, split public-preview tests out of the large dataset test module, and added REST/MCP parity characterization tests for shared dataset behavior.
- Added Docker health checks for the CapRover server and worker process types so non-persistent app deploys can use health-gated rolling updates instead of routing to containers before they are ready.
- Added Qdrant-backed dataset row vector search with PydanticAI/OpenRouter embedding generation, hybrid vector/lexical ranking, REST `POST /api/datasets/{dataset_key}/search`, and hosted MCP `search_dataset_rows`.
- Added vector indexing and cleanup workers for API/MCP dataset creation, row create/update/delete, dataset archive, and an operator `backfill_dataset_vectors` management command.

### Changed
- Production deploy now builds one server/worker image in GitHub Actions, publishes it to GHCR with `latest`, UTC date, date-run, and full Git SHA tags, then deploys that image to both CapRover apps with per-app deploy tokens.
- CI and `make ci-local` now enforce Ruff lint, Ruff format, and frontend lint/build checks.
- Applied the Ruff formatting baseline so future style checks can run without format churn.
- Agent feedback submissions through REST and MCP now require read/write API keys because feedback submissions create private Rowset/CX/Feedback dataset rows.
- Stripe checkout, customer, and billing portal requests can now include `STRIPE_CONTEXT` for Stripe Organization API keys.

### Fixed
- Dataset detail pages now ignore malformed Rowset-looking URL values that Python parses as invalid IPv6 URLs instead of failing the page render.
- Generated-index row patches now accept an unchanged generated index value, avoiding validation failures when agents send full-row update payloads.
- Local CI backend checks now run with DB/Redis dependencies only, avoiding frontend container churn between backend test groups.
- The Ruff lint baseline now passes by applying mechanical import and pyupgrade fixes and documenting two existing complexity exceptions.
- Choice-column row writes now accept unambiguous case, whitespace, hyphen, or underscore variants and store the schema's canonical choice label.
- Canonical legacy `/api/v1` REST requests now resolve to the current API surface, unknown or trailing-slash API paths return JSON 404s without rendering landing-page context, and referrer banner lookup failures no longer turn bad-path traffic into Sentry database errors.

## 2026-06-30

### Changed
- Replaced inherited `AWS_*` media storage setup with explicit `ROWSET_ASSET_*` private dataset asset storage configuration for Cloudflare R2/S3-compatible storage.

### Fixed
- Declared `boto3` as an explicit runtime dependency so the django-storages S3 backend imports reliably in clean production builds.

## 2026-06-28

### Added
- ReviewGate now runs on pull requests in report mode when `OPENROUTER_API_KEY` is configured.

## 2026-06-23

### Added
- Added Sentry request metrics for low-cardinality HTTP request counts and duration distributions, controlled by `SENTRY_ENABLE_METRICS`.
- API and MCP clients can now patch a row directly by the dataset's configured index value.

### Fixed
- Sentry request metrics middleware now wraps the full Django middleware stack so request counts include earlier middleware handling and durations include framework overhead.

## 2026-06-22

### Changed
- Tightened the copyable agent setup prompt, public `/SKILL.md`, and MCP docs with a concrete Codex/OpenClaw `codex mcp add ... --bearer-token-env-var ROWSET_API_KEY` setup path and first-run verification checklist.

## 2026-06-14

### Added
- API and MCP clients can now enable, disable, password-protect, and resize public dataset previews.

### Changed
- Repositioned Rowset as an AI-native, agent-first dataset tool centered on MCP and REST workflows.
- Reworked the dashboard around the copyable agent setup prompt, connection details, recent datasets, and settings access.
- Reworked the landing page around a pre-signup agent prompt so visitors can hand setup to an AI agent before creating an account.

### Removed
- Removed the dashboard CSV/Parquet upload and preview-confirm import wizard.
- Removed Rowset-managed Google Sheets connection, import, and write-back code.

## 2026-05-28

### Added
- API and MCP clients can now create ready API-backed datasets on the fly, with optional initial rows and either a supplied unique index column or a generated Rowset ID.

### Changed
- REST API key authentication now accepts `Authorization: Bearer ...` and `X-API-Key` headers in addition to `?api_key=...`, matching the published docs and agent setup guidance.

## 2026-05-16

### Changed
- Replaced the default app logo/favicon with a generated Rowset icon and added dedicated favicon/apple-touch assets.

## 2026-05-15

### Added
- Hosted MCP now exposes dataset detail and ready-dataset row tools for listing, reading, creating, updating, and deleting rows.
- Dataset owners can now delete datasets from the dataset list, dashboard recent datasets, and dataset settings.
- Dataset owners can now export imported datasets as CSV or Parquet from the dataset UI.
- Google OAuth can now be enabled with `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` for Google signup/login.

### Changed
- Google signup/login now asks only for basic profile/email access.

## 2026-05-14

### Added
- Added dataset discovery for agents via `GET /api/datasets` and the hosted MCP `get_all_datasets` tool, returning dataset metadata for the authenticated profile without row payloads.
- Dashboard home now includes a copyable “teach your AI agent to use Rowset” prompt with the user's HTTPS MCP URL, REST API base, and a linked public `/SKILL.md` agent skill file.
- Added agent access foundations: `GET /api/user` for API-key-authenticated user info and a hosted FastMCP server at `/mcp/` with a matching `get_user_info` tool.
- Added a Google DESIGN.md-style design system source of truth for Rowset colors, typography, layout, components, and usage guardrails.
- Chatwoot support chat can now be enabled with `CHATWOOT_BASE_URL` and `CHATWOOT_WEBSITE_TOKEN`.

### Fixed
- API/MCP authentication logs no longer include raw API key values, and API-key profile lookups now eager-load users for the user-info endpoint.

## 2026-05-13

### Added
- Dataset settings now let owners enable an off-by-default public table preview link with configurable pagination and optional password protection.
- Dataset imports now ask users to choose a unique index column or generate a Rowset ID column before confirming import.
- Dataset APIs now expose `GET /datasets/{dataset_key}/rows/by-index?index_value=...` for retrieving a row by its selected index value.
- Dataset parsing now uses a tabular parser abstraction so future JSON, XLSX, and parquet file types can plug into preview/import flows without rewriting dataset logic.
- CSV dataset MVP: authenticated users can upload a CSV, preview detected headers/sample rows/row count, confirm import, and get API endpoints for listing, creating, updating, deleting, and exporting rows.
- Settings now links users to add and manage passkeys after account creation.

### Changed
- Settings confirmation resends now show one success notification instead of duplicate allauth/app messages.
- The django-allauth email management fallback page now uses Rowset app styling instead of the default unstyled layout.
- Passkey and two-factor account pages now use Rowset app styling instead of django-allauth's default unstyled layout.
- Transactional emails now send from `Rasul Kireev <rasul@lvtd.dev>` by default and use `mg.lvtd.dev` as the default Mailgun sender domain.
- Signup and login now use email + password only; usernames are generated automatically and signup no longer asks for password confirmation.
- The email confirmation reminder now appears only in settings, not on the dashboard home page.
- Passkey login now uses a hardened Rowset WebAuthn launcher that validates server options before calling the browser API.

### Fixed
- CSV imports now store parsed source text in the database so async workers can import rows even when uploaded media files are not shared across containers.
- Dataset detail pages now stack API and status sections vertically, wrap long names/errors/endpoints, and avoid duplicate static header status/row-count state during imports.
- Settings confirmation resends now use django-allauth's canonical email verification flow so generated links confirm correctly.
- Passkey setup now surfaces WebAuthn errors to users instead of failing silently when the browser/device cannot start passkey creation.

## 2026-05-12

### Added
- Sentry setup now includes release metadata, configurable tracing/profiling/log settings, logging breadcrumbs/events, and the `before_send` hook by default.
- `ALLOW_SIGNUPS` environment flag (default `True`) to pause new email/social registrations while keeping existing user logins available.
- Superuser-only admin blog API for creating, listing, reading, updating, patching, deleting, reviewing, and publishing blog posts when the blog app is generated.

### Changed
- Email verification during signup is now non-blocking: new users land on the dashboard, receive a confirmation-link email, and see an in-app reminder until verified.
- Passkey signup is disabled so passkey setup can move to a post-registration account security flow.
