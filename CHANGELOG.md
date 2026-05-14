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
- Reworked the landing page into a sharper FileBridge product story with a bolder visual system, API-focused hero, use cases, and updated FAQs.
- Settings confirmation resends now show one success notification instead of duplicate allauth/app messages.
- The django-allauth email management fallback page now uses FileBridge app styling instead of the default unstyled layout.
- Passkey and two-factor account pages now use FileBridge app styling instead of django-allauth's default unstyled layout.
- Transactional emails now send from `Rasul Kireev <rasul@lvtd.dev>` by default and use `mg.lvtd.dev` as the default Mailgun sender domain.
- Email verification during signup is now non-blocking: new users land on the dashboard, receive a confirmation-link email, and see an in-app reminder until verified.
- Signup and login now use email + password only; usernames are generated automatically and signup no longer asks for password confirmation.
- The email confirmation reminder now appears only in settings, not on the dashboard home page.
- Passkey signup is disabled so passkey setup can move to a post-registration account security flow.
- Sentry setup now includes release metadata, configurable tracing/profiling/log settings, logging breadcrumbs/events, and the `before_send` hook by default.

### Fixed
- API/MCP authentication logs no longer include raw API key values, and API-key profile lookups now eager-load users for the user-info endpoint.
- CSV imports now store parsed source text in the database so async workers can import rows even when uploaded media files are not shared across containers.
- CSV uploads now reject files over 10 MB before preview/import to avoid unbounded database writes.
- Dataset detail pages now stack API and status sections vertically, wrap long names/errors/endpoints, and avoid duplicate static header status/row-count state during imports.

### Added
- Added agent access foundations: `GET /api/user` for API-key-authenticated user info and a hosted FastMCP server at `/mcp/` with a matching `get_user_info` tool.
- Added a Google DESIGN.md-style design system source of truth for FileBridge colors, typography, layout, components, and usage guardrails.
- Chatwoot support chat can now be enabled with `CHATWOOT_BASE_URL` and `CHATWOOT_WEBSITE_TOKEN`.
- Dataset settings now let owners enable an off-by-default public table preview link with configurable pagination and optional password protection.
- Dataset imports now ask users to choose a unique index column or generate a FileBridge ID column before confirming import.
- Dataset APIs now expose `GET /datasets/{dataset_key}/rows/by-index?index_value=...` for retrieving a row by its selected index value.
- Dataset parsing now uses a tabular parser abstraction so future JSON, XLSX, and parquet file types can plug into preview/import flows without rewriting dataset logic.
- CSV dataset MVP: authenticated users can upload a CSV, preview detected headers/sample rows/row count, confirm import, and get API endpoints for listing, creating, updating, deleting, and exporting rows.
- Passkey login now uses a hardened FileBridge WebAuthn launcher that validates server options before calling the browser API.
- Settings confirmation resends now use django-allauth's canonical email verification flow so generated links confirm correctly.
- Passkey setup now surfaces WebAuthn errors to users instead of failing silently when the browser/device cannot start passkey creation.
- Settings now links users to add and manage passkeys after account creation.
- `ALLOW_SIGNUPS` environment flag (default `True`) to pause new email/social registrations while keeping existing user logins available.
- Superuser-only admin blog API for creating, listing, reading, updating, patching, deleting, reviewing, and publishing blog posts when the blog app is generated.
