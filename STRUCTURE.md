# STRUCTURE.md

## Top-Level Map

- `rowset/` - Django project settings, URLs, ASGI/WSGI, storage, logging,
  sitemap, and adapters.
- `apps/core/` - profiles, account state, signup/login helpers, feedback, email,
  Stripe webhooks, shared tasks, and shared tests.
- `apps/datasets/` - dataset domain models, parsing, legacy import/export
  services, public previews, views, tasks, and dataset tests.
- `apps/api/` - Django Ninja API object, auth, schemas, REST views, and API
  service wrappers.
- `apps/mcp_server/` - hosted FastMCP server, MCP bearer auth, tools, and tests.
- `apps/pages/` - marketing/static pages, root-level content routes, checked-in
  docs/tutorial/how-to/explanation/blog content, and page context processors.
- `apps/blog/` - Markdown-backed blog services, validation checks, views, and
  public templates; post Markdown lives in `apps/pages/content/blog`.
- `frontend/templates/` - Django templates for public pages, authenticated app,
  account flows, datasets, docs, MCP auth, components, and email.
- `frontend/src/js/` - Alpine component registration and small global browser
  enhancements.
- `frontend/src/styles/` - app CSS and Pygments styles compiled by PostCSS.
- `scripts/build-assets.mjs` - frontend asset build and watch script.
- `deployment/` - deployment entrypoint and server/worker Dockerfiles.
- `.github/workflows/` - CI and deploy workflows.
- `.cursor/rules/` - Cursor-specific rules.

## Placement Rules

- Put dataset parsing, validation, indexing, serialization, and export behavior in
  `apps/datasets/services.py`.
- Put dataset background jobs in `apps/datasets/tasks.py`.
- Put API request/response schema definitions in `apps/api/schemas.py`.
- Put REST endpoint functions in `apps/api/views.py`; keep them thin.
- Put reusable API-facing dataset orchestration in `apps/api/services.py`.
- Put MCP tools in `apps/mcp_server/server.py`; keep tool bodies thin and backed
  by the same services as REST endpoints.
- Put MCP auth logic in `apps/mcp_server/auth.py`.
- Put user-facing docs, tutorials, how-to guides, explanations, and blog
  Markdown in `apps/pages/content/...`; update
  `apps/pages/content/navigation.yaml` when adding a routed content page.
- Put Django templates under the matching `frontend/templates/<area>/` folder.
- Put shared template fragments in `frontend/templates/components/`.
- Use HTMX attributes for server round trips and Alpine.js for local-only
  browser state. Put reusable Alpine components or small shared DOM behavior in
  `frontend/src/js`.
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
- REST endpoints delegating to services: `apps/api/views.py`.
- MCP tools delegating to services: `apps/mcp_server/server.py`.
- User-facing docs front matter and concise sections:
  `apps/pages/content/how-to/connect-mcp.md`.
- Shared template include pattern:
  `frontend/templates/components/`.

## Special Cases

- Never hand-create migrations. Use `make makemigrations` after model changes.
- Pages-owned content uses the repo-level documentation guidance in `AGENTS.md`.
- Public previews live in dataset pages/templates and must remain read-only.
- The hosted MCP URL and agent setup prompt appear in docs and authenticated app
  context; keep the behavior consistent when changing either path.
- If a global script belongs on all public and authenticated pages, create one
  shared component include and include it from both base templates.
