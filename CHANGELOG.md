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
- Passkey and two-factor account pages now use FileBridge app styling instead of django-allauth's default unstyled layout.
- Transactional emails now send from `Rasul Kireev <rasul@lvtd.dev>` by default and use `mg.lvtd.dev` as the default Mailgun sender domain.
- Email verification during signup is now non-blocking: new users land on the dashboard, receive a confirmation-link email, and see an in-app reminder until verified.
- Signup and login now use email + password only; usernames are generated automatically and signup no longer asks for password confirmation.
- The email confirmation reminder now appears only in settings, not on the dashboard home page.
- Passkey signup is disabled so passkey setup can move to a post-registration account security flow.
- Sentry setup now includes release metadata, configurable tracing/profiling/log settings, logging breadcrumbs/events, and the `before_send` hook by default.

### Added
- Passkey setup now surfaces WebAuthn errors to users instead of failing silently when the browser/device cannot start passkey creation.
- Settings now links users to add and manage passkeys after account creation.
- `ALLOW_SIGNUPS` environment flag (default `True`) to pause new email/social registrations while keeping existing user logins available.
- Superuser-only admin blog API for creating, listing, reading, updating, patching, deleting, reviewing, and publishing blog posts when the blog app is generated.
