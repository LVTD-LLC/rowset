# Changelog
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project tries to adhere to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Types of changes

**Added** for new features.
**Changed** for changes in existing functionality.
**Deprecated** for soon-to-be removed features.
**Removed** for now removed features.
**Fixed** for any bug fixes.
**Security** in case of vulnerabilities.


## [Unreleased]

### Changed
- Added Sentry request metrics for low-cardinality HTTP request counts and duration distributions, controlled by `SENTRY_ENABLE_METRICS`.
- Tightened the copyable agent setup prompt, public `/SKILL.md`, and MCP docs with a concrete Codex/OpenClaw `codex mcp add ... --bearer-token-env-var ROWSET_API_KEY` setup path and first-run verification checklist.
- Repositioned Rowset as an AI-native, agent-first dataset tool centered on MCP and REST workflows.
- Reworked the dashboard around the copyable agent setup prompt, connection details, recent datasets, and settings access.
- Reworked the landing page around a pre-signup agent prompt so visitors can hand setup to an AI agent before creating an account.
- Replaced the default app logo/favicon with a generated Rowset icon and added dedicated favicon/apple-touch assets.
- Settings confirmation resends now show one success notification instead of duplicate allauth/app messages.
- The django-allauth email management fallback page now uses Rowset app styling instead of the default unstyled layout.
- Passkey and two-factor account pages now use Rowset app styling instead of django-allauth's default unstyled layout.
- Transactional emails now send from `Rasul Kireev <rasul@lvtd.dev>` by default and use `mg.lvtd.dev` as the default Mailgun sender domain.
- Email verification during signup is now non-blocking: new users land on the dashboard, receive a confirmation-link email, and see an in-app reminder until verified.
- Signup and login now use email + password only; usernames are generated automatically and signup no longer asks for password confirmation.
- The email confirmation reminder now appears only in settings, not on the dashboard home page.
- Passkey signup is disabled so passkey setup can move to a post-registration account security flow.
- Sentry setup now includes release metadata, configurable tracing/profiling/log settings, logging breadcrumbs/events, and the `before_send` hook by default.
- Google signup/login now asks only for basic profile/email access.

### Fixed
- Sentry request metrics middleware now wraps the full Django middleware stack so request counts include earlier middleware handling and durations include framework overhead.
- REST API key authentication now accepts `Authorization: Bearer ...` and `X-API-Key` headers in addition to `?api_key=...`, matching the published docs and agent setup guidance.
- API/MCP authentication logs no longer include raw API key values, and API-key profile lookups now eager-load users for the user-info endpoint.
- CSV imports now store parsed source text in the database so async workers can import rows even when uploaded media files are not shared across containers.
- Dataset detail pages now stack API and status sections vertically, wrap long names/errors/endpoints, and avoid duplicate static header status/row-count state during imports.

### Added
- API and MCP clients can now enable, disable, password-protect, and resize public dataset previews.
- API and MCP clients can now create ready API-backed datasets on the fly, with optional initial rows and either a supplied unique index column or a generated Rowset ID.
- Google OAuth can now be enabled with `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` for Google signup/login.
- Hosted MCP now exposes dataset detail and ready-dataset row tools for listing, reading, creating, updating, and deleting rows.
- Dataset owners can now delete datasets from the dataset list, dashboard recent datasets, and dataset settings.
- Dataset owners can now export imported datasets as CSV or Parquet from the dataset UI.
- Added dataset discovery for agents via `GET /api/datasets` and the hosted MCP `get_all_datasets` tool, returning dataset metadata for the authenticated profile without row payloads.
- Dashboard home now includes a copyable “teach your AI agent to use Rowset” prompt with the user's HTTPS MCP URL, REST API base, and a linked public `/SKILL.md` agent skill file.
- Added agent access foundations: `GET /api/user` for API-key-authenticated user info and a hosted FastMCP server at `/mcp/` with a matching `get_user_info` tool.
- Added a Google DESIGN.md-style design system source of truth for Rowset colors, typography, layout, components, and usage guardrails.

### Removed
- Removed the dashboard CSV/Parquet upload and preview-confirm import wizard.
- Removed Rowset-managed Google Sheets connection, import, and write-back code.
- Chatwoot support chat can now be enabled with `CHATWOOT_BASE_URL` and `CHATWOOT_WEBSITE_TOKEN`.
- Dataset settings now let owners enable an off-by-default public table preview link with configurable pagination and optional password protection.
- Dataset imports now ask users to choose a unique index column or generate a Rowset ID column before confirming import.
- Dataset APIs now expose `GET /datasets/{dataset_key}/rows/by-index?index_value=...` for retrieving a row by its selected index value.
- Dataset parsing now uses a tabular parser abstraction so future JSON, XLSX, and parquet file types can plug into preview/import flows without rewriting dataset logic.
- CSV dataset MVP: authenticated users can upload a CSV, preview detected headers/sample rows/row count, confirm import, and get API endpoints for listing, creating, updating, deleting, and exporting rows.
- Passkey login now uses a hardened Rowset WebAuthn launcher that validates server options before calling the browser API.
- Settings confirmation resends now use django-allauth's canonical email verification flow so generated links confirm correctly.
- Passkey setup now surfaces WebAuthn errors to users instead of failing silently when the browser/device cannot start passkey creation.
- Settings now links users to add and manage passkeys after account creation.
- `ALLOW_SIGNUPS` environment flag (default `True`) to pause new email/social registrations while keeping existing user logins available.
- Superuser-only admin blog API for creating, listing, reading, updating, patching, deleting, reviewing, and publishing blog posts when the blog app is generated.
