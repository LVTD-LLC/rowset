# AGENTS.md

## Scope

This is the repo-level operating manual for AI coding agents working on FileBridge.
Read it before editing, then use `PRODUCT.md`, `TECH.md`, `STRUCTURE.md`,
`VISION.md`, and `DESIGN.md` for deeper product, technical, repo, and UI context.

## Project Summary

FileBridge turns tabular files and spreadsheet-like sources into API-addressable
datasets. Users preview data, choose or generate a stable index column, confirm
the import, and then use REST endpoints, CSV export, hosted MCP tools, or a
read-only public preview.

The current product centers on CSV, Parquet, and Google Sheets-backed datasets.
Agents must keep public sharing, API authentication, and MCP access distinct:
public previews are browser-friendly and read-only; REST and MCP are the private
programmatic paths.

## Workflow

- Start by reading the files you are changing and the steering files relevant to
  the task. For documentation work under `apps/docs`, also read
  `apps/docs/AGENTS.md`.
- Prefer `rg` and `rg --files` for repo search.
- Keep changes inside the existing app boundaries from `STRUCTURE.md`.
- Put reusable dataset business logic in services, not directly in views,
  templates, or MCP tool bodies.
- Keep REST and MCP behavior aligned by reusing service functions instead of
  duplicating row or dataset rules.
- Do not hand-write migrations. Change models first, then run Django's migration
  generator.
- Do not add new dependencies when Django, Django Ninja, FastMCP, Stimulus, or
  the standard library already handle the need cleanly.
- Preserve user data privacy. Never print API keys, OAuth tokens, raw secrets, or
  private dataset contents into logs, docs, screenshots, or final messages.

## Commands

- Copy local env: `cp .env.example .env`
- Start the local stack: `make serve`
- Django shell: `make shell`
- Django management command: `make manage <command>`
- Create migrations after model changes: `make makemigrations`
- Apply migrations: `make migrate`
- Run tests in the Docker sandbox: `make test`
- Run a focused test file: `make test apps/datasets/tests/test_csv_datasets.py`
- Run focused pytest flags: `make test -- -k dataset -q`
- Restart workers: `make restart-worker`
- Build frontend assets locally: `npm run build`
- Lint frontend JS locally: `npm run lint`

Avoid running host `pytest` directly unless you are intentionally debugging the
host environment. The supported path is the Docker-backed `make test`.

## Verification

- For backend behavior, run the smallest relevant `make test ...` target first,
  then broaden if the change touches shared services, auth, or data import.
- For model changes, run `make makemigrations` and include generated migrations
  only when they are the direct result of the model edit.
- For API or MCP changes, verify ownership boundaries, invalid input handling,
  and the equivalent REST/MCP behavior where applicable.
- For template or frontend changes, check both public/landing and authenticated
  app shells when the change is global.
- `manage.py check` can warn when `frontend/build/manifest.json` is missing; use
  the frontend build or local stack when asset rendering is part of the change.

## Product Guardrails

- Keep private authenticated dataset access as the default.
- Do not imply public previews are an authentication mechanism or a replacement
  for REST/MCP access.
- Prefer MCP tools over browser automation for AI-agent workflows.
- Prefer OAuth for hosted MCP setup. Bearer API keys remain a compatibility path.
- Ask before destructive data actions such as deleting datasets, rows, OAuth
  artifacts, or generated files outside the requested scope.
- Be precise about supported file types. CSV, Parquet, and Google Sheets paths
  exist today; future file types should be described as future-facing until code
  and tests ship.
- Keep index columns stable, unique, and explicit. If a source has no reliable
  business key, use the generated `filebridge_id` path.
- Treat Google Sheets write-back as opt-in. It requires explicit Google Sheets
  access or service-account configuration.

## Code Style

- Python uses Ruff with 100-character lines and double quotes.
- Keep Django views thin. Use service modules for validation, persistence, and
  serialization.
- Keep Django Ninja schemas in `apps/api/schemas.py`.
- Keep dataset parsing/import/export behavior in `apps/datasets/services.py`;
  keep Google Sheets API-specific behavior in `apps/datasets/google_sheets.py`.
- Keep MCP tool descriptions user-facing and concrete. Tool bodies should
  authenticate, call services, convert service errors, and return structured data.
- Use Stimulus controllers for browser interactivity in Django templates.
- Keep docs action-oriented, user-facing, and short enough to scan.

## Git

- Worktrees may be detached. If a branch is needed, create it from the current
  HEAD with the `rasul/` prefix unless the user asked for a different name.
- Do not force-push or rewrite shared history unless the user explicitly asks.
- Do not revert user changes or unrelated files.
