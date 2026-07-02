# Scoped Type Checking

Rowset uses `ty` as an incremental signal, not a whole-repo gate. Django dynamic
attributes and framework-heavy modules are intentionally out of scope until they
have local cleanup tasks.

## Current Scope

`make type-check` currently runs:

```bash
uv run ty check \
  apps/api/errors.py \
  apps/api/row_contracts.py \
  apps/api/schemas.py \
  apps/api/utils.py \
  apps/core/agent_skill.py \
  apps/core/capabilities.py \
  apps/datasets/choices.py \
  apps/datasets/constants.py \
  apps/datasets/embeddings.py \
  apps/datasets/types.py \
  rowset/logging_utils.py \
  rowset/sentry_metrics.py \
  rowset/sentry_utils.py \
  rowset/utils.py
```

These modules are low-noise because they are pure helpers, API schemas, row
contract helpers, or structured agent-facing output code. They should stay clean
in CI. `apps/api/row_contracts.py` is the typed API row boundary: it names shared
row write payloads, normalized row data, row search filters, and row search
candidate shapes without pulling the full Django service kernel into the scoped
check.

The shared dataset aliases in `apps/datasets/types.py` are the preferred names
for metadata and schema shapes at REST/MCP boundaries:

- `JsonScalar`, `JsonValue`, and `JsonObject` for arbitrary JSON metadata.
- `ColumnSchema`, `ColumnSchemaEntry`, and `ColumnTypeSpec` for semantic column metadata.
- `DatasetRowInput` for API/MCP create-row and update-row payloads that may contain raw JSON values.

## Expansion Path

Add files only when a focused task can keep the diagnostics actionable:

1. Prefer pure helpers, schemas, serializers, or prompt/capability builders.
2. Avoid adding Django auth, models, views, or tests until there is a real typing
   strategy for their framework-provided dynamic attributes.
3. Fix real diagnostics instead of suppressing broad paths.
4. Update `Makefile`, this document, and `docs/quality.md` in the same change
   when expanding the scope.
5. Run `make type-check` locally before opening the PR.
