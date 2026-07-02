# Scoped Type Checking

Rowset uses `ty` as an incremental signal, not a whole-repo gate. Django dynamic
attributes and framework-heavy modules are intentionally out of scope until they
have local cleanup tasks.

## Current Scope

`make type-check` currently runs:

```bash
uv run ty check \
  apps/api/admin.py \
  apps/api/auth.py \
  apps/api/errors.py \
  apps/api/models.py \
  apps/api/row_contracts.py \
  apps/api/schemas.py \
  apps/api/urls.py \
  apps/api/utils.py \
  apps/blog/admin.py \
  apps/blog/choices.py \
  apps/blog/model_typing.py \
  apps/blog/models.py \
  apps/blog/urls.py \
  apps/blog/views.py \
  apps/core/admin.py \
  apps/core/agent_skill.py \
  apps/core/agents/base.py \
  apps/core/analytics.py \
  apps/core/base_models.py \
  apps/core/capabilities.py \
  apps/core/choices.py \
  apps/core/context_processors.py \
  apps/core/forms.py \
  apps/core/model_typing.py \
  apps/core/model_utils.py \
  apps/core/models.py \
  apps/core/signals.py \
  apps/core/stripe_webhooks.py \
  apps/core/templatetags/markdown_extras.py \
  apps/core/urls.py \
  apps/core/utils.py \
  apps/datasets/admin.py \
  apps/datasets/apps.py \
  apps/datasets/choices.py \
  apps/datasets/constants.py \
  apps/datasets/embeddings.py \
  apps/datasets/history.py \
  apps/datasets/management/commands/backfill_dataset_vectors.py \
  apps/datasets/management/commands/retry_dataset_asset_file_deletions.py \
  apps/datasets/model_typing.py \
  apps/datasets/public_previews.py \
  apps/datasets/services.py \
  apps/datasets/types.py \
  apps/datasets/urls.py \
  apps/datasets/vector_search.py \
  apps/datasets/vector_tasks.py \
  apps/docs/admin.py \
  apps/docs/models.py \
  apps/docs/urls.py \
  apps/docs/views.py \
  apps/mcp_server/apps.py \
  apps/mcp_server/auth.py \
  apps/mcp_server/models.py \
  apps/mcp_server/server.py \
  apps/pages/admin.py \
  apps/pages/checks.py \
  apps/pages/context_processors.py \
  apps/pages/model_typing.py \
  apps/pages/models.py \
  apps/pages/urls.py \
  apps/pages/use_cases.py \
  apps/pages/views.py \
  rowset/adapters.py \
  rowset/asgi.py \
  rowset/logging_utils.py \
  rowset/sentry_metrics.py \
  rowset/sentry_utils.py \
  rowset/settings.py \
  rowset/sitemaps.py \
  rowset/storages.py \
  rowset/urls.py \
  rowset/utils.py \
  rowset/wsgi.py \
  scripts/agent-eval-seed.py \
  scripts/check-quality-drift.py \
  scripts/startup-smoke.py
```

These 76 files are low-noise because they are pure helpers, API schemas, auth
boundaries, MCP tool boundaries, app support modules, docs/blog/page views, or
dataset service code that has explicit local typing. They should stay clean in
CI. The scope still excludes the largest dynamic surfaces, such as broad API and
dataset views, until those modules get focused cleanup.

`apps/api/row_contracts.py` is the typed API row boundary: it names shared row
write payloads, normalized row data, row search filters, and row search candidate
shapes without pulling the full Django view layer into the scoped check.

Model typing helpers centralize Django's dynamic model attributes, managers, and
generated exception classes. Prefer adding typed protocols or helper functions to
`apps/core/model_typing.py`, `apps/datasets/model_typing.py`,
`apps/pages/model_typing.py`, or a similarly local helper over scattering
`cast(Any, ...)` through API, MCP, service, or view modules.

The shared dataset aliases in `apps/datasets/types.py` are the preferred names
for metadata and schema shapes at REST/MCP boundaries:

- `JsonScalar`, `JsonValue`, and `JsonObject` for arbitrary JSON metadata.
- `ColumnSchema`, `ColumnSchemaEntry`, and `ColumnTypeSpec` for semantic column metadata.
- `DatasetRowInput` for API/MCP create-row payloads that may contain raw JSON values.

## Expansion Path

Add files only when a focused task can keep the diagnostics actionable:

1. Prefer pure helpers, schemas, serializers, or prompt/capability builders.
2. Avoid adding large Django models, views, or tests until their dynamic
   attributes have been typed deliberately.
3. Fix real diagnostics instead of suppressing broad paths.
4. Update `Makefile`, this document, and `docs/quality.md` in the same change
   when expanding the scope.
5. Run `make type-check` locally before opening the PR.
