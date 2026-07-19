# Changelog
All notable changes to this project will be documented in this file.

Entries are grouped by calendar date, newest first, and use the change types from
[Keep a Changelog](https://keepachangelog.com/en/1.0.0/). Versioned releases,
when used, still try to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Dates represent when the changelog entry landed in git history, not a production
deployment or release cut date.

## Types of changes

**Added** for new features.
**Changed** for changes in existing functionality.
**Deprecated** for soon-to-be removed features.
**Removed** for now removed features.
**Fixed** for any bug fixes.
**Security** in case of vulnerabilities.

## 2026-07-19

### Added
- Added an implementation guide for AI agent audit trails that separates runtime traces, authorization decisions, and business-state changes while documenting Rowset's operational-history limits.
- Added a repeatable MCP-versus-CLI agent evaluation harness with a 24-task corpus, cross-client result contract, safety and efficiency thresholds, and baseline regression reports.

## 2026-07-18

### Added
- Added a practical guide to human-in-the-loop AI agent workflows with a risk matrix, durable approval schema, Rowset implementation pattern, and explicit execution-boundary limitations.
- Added consent-aware marketing attribution across pageviews, signup, agent activation, checkout, subscription, cancellation, churn, and payment-failure events.
- Added MCP behavior annotations for safe reads, mutations, destructive actions, and idempotent operations.

### Changed
- Unified browser and backend PostHog identity and setup milestones, removed duplicate signup and alias events, and added first-party browser ingestion configuration.
- Read-only MCP tools no longer start an account trial; the trial starts on the first dataset or project mutation.

### Security
- Filtered hosted MCP tool and capability discovery by API-key permission and blocked hidden write or admin tools before their implementation bodies run.
- Added a daily release train that skips unchanged `main`, requires a successful production deploy for the exact commit, and publishes the next immutable dotted-date release through the existing guarded release pipeline.

### Fixed
- Made self-host release publishing fail before image promotion when the bundled guide or installer references a missing command, non-executable command, or local guide file, and made the source-versus-installed guide boundary explicit.

### Changed
- Replaced eager agent startup discovery with task-driven capability lookup, bounded dataset search, and direct dataset inspection when a key or URL is already known.

## 2026-07-17

### Added
- Added explicit privacy-safe pageview capture for marketing, documentation, authentication, and public dataset pages, including exact-once HTMX handling and bounded campaign attribution.

### Security
- Disabled Django's model administration routes in production and removed internal dashboard links into editable admin records.

### Changed
- Made capability discovery progressive across MCP, REST, and CLI: bare requests return a compact topic index, topic selection loads focused details, use cases are opt-in, and full mode remains available for the complete guide.
- Enabled colorized choice values and tags by default for new user profiles.
- Limited internal admin dashboard metrics and activity to regular users while excluding staff and superuser-owned data.
- Made hosted MCP initialization instructions self-contained for bounded reads, stable-index writes, destructive-action consent, and public-preview safety.
- Moved blog reading actions into the article header alongside trial and quickstart links, matching the comparison-article action hierarchy.

### Removed
- Removed dataset mutation counts from the internal admin dashboard's health cards, activity chart, and recent-activity feed.

## 2026-07-16

### Added
- Added deterministic, read-only self-host preflight and doctor commands with stable machine-readable checks for host requirements, release access, service health, HTTPS, migrations, authentication boundaries, and optional runtime capabilities.
- Added coherent immutable self-host releases that publish a matching image and checksum-protected deployment bundle, pin installer reruns to the recorded version, and report the installed version, commit, image, and digest.
- Added coordinated PostgreSQL and local-media backup/restore commands with versioned manifests, integrity checks, retention, optional S3-compatible off-server copies, a daily systemd timer, and an isolated destructive restore drill that verifies users, datasets, relationships, and assets.
- Added an authenticated post-deployment smoke command that verifies REST, MCP, dataset writes and reads, and worker execution while removing temporary users, keys, datasets, and task results after success or failure.
- Added tested self-host sizing profiles, amd64 and arm64 startup and footprint evidence, a reproducible benchmark command, and machine-readable requirements for deployment preflight checks.
- Added a release gate that removes GHCR credentials, anonymously inspects and pulls both supported architectures before tag promotion, and prevents an immutable Git SHA tag from being overwritten with a different digest.
- Added a decision guide for sharing AI-agent data through scoped private access, authenticated exports, or read-only public previews.

### Changed
- Reworked the internal admin panel into a product-health dashboard with period comparisons, activation funnel, growth and activity trends, attention signals, operational inventory, and a unified recent-activity feed.
- Redesigned first-agent onboarding as a required two-step create-key and copy-prompt wizard that matches the app shell.
- Made the copied agent setup prompt and dedicated `rowset-setup` skill transport-neutral across MCP, CLI, and REST, while keeping the core `rowset` skill focused on ongoing platform interaction.
- Added direct docs and blog discovery links to the agent prompt and ensured Step 2 copies the protected full-key prompt while keeping its on-screen preview masked.
- Extended the post-setup agent handoff with tailored project, section, and dataset suggestions plus an opt-in daily Rowset tips automation for agent runtimes that support scheduled tasks.
- Dataset list and search responses now return compact discovery cards through REST and MCP; clients call the single-dataset detail endpoint or `get_dataset` when they need headers, semantic schema, instructions, metadata, index settings, relationships, or preview configuration.
- Agent-facing dataset, project, section, and row collections now default to 10 results, reject limits above 100, preserve explicit pagination metadata for requesting subsequent pages, and expose project sections only through their bounded collection endpoint.
- Comparison articles now use an aligned technical-brief layout with clearer action hierarchy, responsive tables, and dedicated long-form reading styles.

### Fixed
- Preserved PostHog's anonymous browser identity across page navigation so pre-signup activity and campaign attribution remain connected.

### Security
- Added idempotent production environment initialization and pre-start validation with generated strong secrets, owner-only files, injected-secret support, and rejection of unsafe development defaults.
- Removed query-string and alternate-header API-key authentication so private REST and hosted MCP requests accept credentials only as bearer tokens.
- Disabled search indexing automatically on self-hosted origins, kept the hosted Rowset origin indexable, and canonicalized public pages to `rowset.lvtd.dev`.

## 2026-07-15

### Fixed
- Prevented missing browser assets and unknown URLs from cascading into database-backed error rendering, and added a canonical `/favicon.ico` route.
- Kept the shared public-page footer anchored to the bottom of the viewport when page content is short.

### Added
- Added a homepage carousel highlighting projects that use Rowset.
- Added a public changelog page backed by the repository changelog, with a Markdown variant and links from the shared footer and app help sidebar.
- Added one-time three-day trial rewards for verifying email, starring Rowset on GitHub, joining the Discord community, and following Rasul on X, with pending rewards preserved until a trial starts and a post-setup sidebar link for discovery.

## 2026-07-07

### Changed
- Simplified the docs sidebar by keeping advanced docs routable but removing them from the default navigation, and tightened core docs copy around dataset, API, setup, and troubleshooting paths.

## 2026-07-06

### Changed
- Simplified the docs sidebar to Getting started, Features, and Reference, and removed use cases from the docs navigation.
- Reworked the public docs around user tasks, redirected `/docs/` to the quickstart, and preserved links from older documentation routes.

## 2026-07-03

### Fixed
- MCP row listing and row search tools now tolerate agent-supplied `null` pagination values and JSON-string row filters, avoiding Pydantic validation failures before the request reaches Rowset's structured service errors.

## 2026-07-02

### Changed
- Dataset browser views now render URL-looking string cell values as plain text instead of auto-converting them into Rowset or external links. Explicit dataset relationship/reference columns, row-detail links, and image links still render as links; arbitrary URL strings can be copied from the cell text and link rendering can be reintroduced later with safer, explicit column-level behavior.

### Fixed
- Agent feedback submissions now append to the configured Rowset feedback dataset instead of each submitter's own dataset.
- Dataset detail pages now ignore non-URL JSON-array-looking cell values before Rowset link normalization, avoiding 500s for result rows with values such as `[]`.
- Production Docker healthchecks now run through the project virtualenv and allow enough startup time for GHCR image rollouts.

## 2026-07-01

### Added
- Added Rowset Pro billing copy/configuration for a single $50/month plan and enforced free-account dataset quotas through shared REST/MCP services.
- Added Docker health checks for the CapRover server and worker process types so non-persistent app deploys can use health-gated rolling updates instead of routing to containers before they are ready.
- Added Qdrant-backed dataset row vector search with PydanticAI/OpenRouter embedding generation, hybrid vector/lexical ranking, REST `POST /api/datasets/{dataset_key}/search`, and hosted MCP `search_dataset_rows`.
- Added vector indexing and cleanup workers for API/MCP dataset creation, row create/update/delete, dataset archive, and an operator `backfill_dataset_vectors` management command.

### Changed
- Production deploy now builds one server/worker image in GitHub Actions, publishes it to GHCR with `latest`, UTC date, date-run, and full Git SHA tags, then deploys that image to both CapRover apps with per-app deploy tokens.
- CI and `make ci-local` now enforce Ruff lint, Ruff format, and frontend lint/build checks.
- Agent feedback submissions through REST and MCP now require read/write API keys because feedback submissions create private Rowset/CX/Feedback dataset rows.
- Stripe checkout, customer, and billing portal requests can now include `STRIPE_CONTEXT` for Stripe Organization API keys.

### Fixed
- Dataset detail pages now ignore malformed Rowset-looking URL values that Python parses as invalid IPv6 URLs instead of failing the page render.
- Generated-index row patches now accept an unchanged generated index value, avoiding validation failures when agents send full-row update payloads.
- Local CI backend checks now run with DB/Redis dependencies only, avoiding frontend container churn between backend test groups.
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

### Changed
- Email verification during signup is now non-blocking: new users land on the dashboard, receive a confirmation-link email, and see an in-app reminder until verified.
- Passkey signup is disabled so passkey setup can move to a post-registration account security flow.
