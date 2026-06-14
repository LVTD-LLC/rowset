# STRUCTURE.md

## Top-Level Map

- `filebridge/` - Django project settings, URLs, ASGI/WSGI, storage, logging,
  sitemap, and adapters.
- `apps/core/` - profiles, account state, signup/login helpers, feedback, email,
  Stripe webhooks, shared tasks, and shared tests.
- `apps/datasets/` - dataset domain models, parsing, import/export services,
  Google Sheets integration, views, tasks, and dataset tests.
- `apps/api/` - Django Ninja API object, auth, schemas, REST views, and API
  service wrappers.
- `apps/mcp_server/` - hosted FastMCP server, MCP OAuth, tools, URLs, and tests.
- `apps/docs/` - in-app documentation renderer, Markdown content, navigation,
  and docs-specific agent guidance.
- `apps/pages/` - marketing/static pages and page context processors.
- `apps/blog/` - blog models, views, choices, and admin endpoints.
- `frontend/templates/` - Django templates for public pages, authenticated app,
  account flows, datasets, docs, MCP auth, components, and email.
- `frontend/src/controllers/` - Stimulus controllers.
- `frontend/src/styles/` - app CSS and Pygments styles.
- `frontend/webpack/` - Webpack configs.
- `deployment/` - deployment entrypoint and server/worker Dockerfiles.
- `.github/workflows/` - CI and deploy workflows.
- `.cursor/rules/` - Cursor-specific rules.

## Placement Rules

- Put dataset parsing, validation, indexing, serialization, and export behavior in
  `apps/datasets/services.py` unless the behavior is specific to Google Sheets.
- Put Google Sheets API calls, credential resolution, and write-back behavior in
  `apps/datasets/google_sheets.py`.
- Put dataset background jobs in `apps/datasets/tasks.py`.
- Put API request/response schema definitions in `apps/api/schemas.py`.
- Put REST endpoint functions in `apps/api/views.py`; keep them thin.
- Put reusable API-facing dataset orchestration in `apps/api/services.py`.
- Put MCP tools in `apps/mcp_server/server.py`; keep tool bodies thin and backed
  by the same services as REST endpoints.
- Put OAuth-specific MCP logic in `apps/mcp_server/oauth.py`.
- Put user-facing docs in `apps/docs/content/...` and update
  `apps/docs/navigation.yaml` when adding a page.
- Put docs writing guidance in `apps/docs/AGENTS.md`, not repeated in every doc.
- Put Django templates under the matching `frontend/templates/<area>/` folder.
- Put shared template fragments in `frontend/templates/components/`.
- Put new browser behavior in Stimulus controllers under
  `frontend/src/controllers`.
- Put new tests next to the app they cover, using existing `tests.py` or
  `tests/test_*.py` patterns.

## Import And Dependency Rules

- Views may import services, schemas, models, and auth helpers from their app.
- `apps/api` and `apps/mcp_server` may call dataset/core service functions.
- Avoid importing views from services or models.
- Avoid duplicating dataset validation in REST, MCP, and template code.
- Avoid cross-app template logic when a context processor or service function is
  the clearer boundary.
- Keep optional integration details behind settings checks so local development
  works with empty credentials.

## Existing Good Patterns

- Dataset parser and schema inference logic: `apps/datasets/services.py`.
- Google Sheets credential and write-back isolation:
  `apps/datasets/google_sheets.py`.
- REST endpoints delegating to services: `apps/api/views.py`.
- MCP tools delegating to services: `apps/mcp_server/server.py`.
- User-facing docs front matter and concise sections:
  `apps/docs/content/features/mcp.md`.
- Shared template include pattern:
  `frontend/templates/components/`.

## Special Cases

- Never hand-create migrations. Use `make makemigrations` after model changes.
- The docs app has its own agent instructions in `apps/docs/AGENTS.md`.
- Public previews live in dataset pages/templates and must remain read-only.
- The hosted MCP URL and agent setup prompt appear in docs and authenticated app
  context; keep the behavior consistent when changing either path.
- If a global script belongs on all public and authenticated pages, create one
  shared component include and include it from both base templates.
