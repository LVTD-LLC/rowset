# Scoped Type Checking

Rowset uses `ty` as an incremental signal, not a whole-repo gate. Django dynamic
attributes and framework-heavy modules are intentionally out of scope until they
have local cleanup tasks.

## Current Scope

`make type-check` currently runs:

```bash
uv run ty check apps/core/capabilities.py apps/core/agent_skill.py rowset/utils.py rowset/logging_utils.py apps/api/row_contracts.py
```

These modules are low-noise because they are mostly pure helpers or structured
agent-facing output code. `apps/api/row_contracts.py` is included as the first
typed API row boundary: it names shared row write payloads, normalized row data,
row search filters, and row search candidate shapes without pulling the full
Django service kernel into the scoped check.

## Expansion Path

Add files only when a focused task can keep the diagnostics actionable:

1. Prefer pure helpers, schemas, serializers, or prompt/capability builders.
2. Avoid adding large Django models, views, or tests until their dynamic
   attributes have been typed deliberately.
3. Fix real diagnostics instead of suppressing broad paths.
4. Update `Makefile`, this document, and `docs/quality.md` in the same change
   when expanding the scope.
5. Run `make type-check` locally before opening the PR.
