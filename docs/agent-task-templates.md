# Agent Task Templates

Use these templates to keep Rowset agent work small, verifiable, and aligned
with the repo boundaries.

## Backend Service Change

```markdown
Task: <one behavior change>

Read first:
- PRODUCT.md, TECH.md, STRUCTURE.md, AGENTS.md
- docs/code-tours/dataset-lifecycle.md#<section>
- <service file>
- <closest tests>

Implementation:
- Put shared dataset behavior in `apps/api/services.py` or
  `apps/datasets/services.py`.
- Keep API/MCP/view wrappers thin.

Verification:
- `make test -- <focused tests> -q`
- `make lint-python`
- `make format-check`

Evidence to record:
- Failing test before fix when practical.
- Passing focused tests after fix.
- Any REST/MCP parity impact.
```

## REST/MCP Parity Change

```markdown
Task: <shared API and MCP behavior>

Read first:
- docs/code-tours/dataset-lifecycle.md#rest-to-service-flow
- docs/code-tours/dataset-lifecycle.md#mcp-to-service-flow
- apps/api/schemas.py
- apps/api/views.py
- apps/mcp_server/server.py
- apps/mcp_server/tests/test_rest_mcp_parity.py

Implementation:
- Add or update service behavior once.
- Expose it through REST and MCP with matching validation and response shape.

Verification:
- `make test -- apps/api apps/mcp_server -q`
- `make coverage-high-risk -- apps/api apps/mcp_server -q`
```

## Dataset Test Refactor

```markdown
Task: <test-only organization or fixture change>

Read first:
- docs/code-tours/dataset-lifecycle.md
- apps/datasets/tests/factories.py
- current source test file

Implementation:
- Move one coherent behavior group at a time.
- Prefer shared factories over copying setup blocks.
- Do not mix behavior changes into a test split.

Verification:
- `make test -- <moved test file> <old test file> -q`
- Broaden to `make test -- apps/datasets -q` when fixtures or conftest changed.
```

## Frontend Or Template Change

```markdown
Task: <template or JS change>

Read first:
- DESIGN.md
- docs/quality.md
- affected template/component files
- affected view/context code

Implementation:
- Use HTMX for server round trips.
- Use Alpine.js for local browser state.
- Keep public and authenticated shells consistent when changing shared UI.

Verification:
- `make frontend-install`
- `make frontend-check`
- `make template-check`
- Focused Django tests for rendered behavior when applicable.
```

## Type Or Quality Gate Change

```markdown
Task: <quality command or CI gate>

Read first:
- docs/quality.md
- docs/typing.md or docs/coverage.md when relevant
- Makefile
- .github/workflows/ci.yml
- scripts/ci-local.sh

Implementation:
- Keep local and CI commands aligned.
- Prefer small, actionable scopes over noisy whole-repo gates.
- Document expansion rules before enforcing new checks.

Verification:
- Run the new command locally.
- Parse `.github/workflows/ci.yml`.
- Run `make lint-python` and `make format-check`.
```

## Documentation Change

```markdown
Task: <doc page or code tour>

Read first:
- AGENTS.md
- PRODUCT.md, TECH.md, STRUCTURE.md
- existing docs in the same directory

Implementation:
- Keep docs task-oriented.
- Name files to inspect, commands to run, and common footguns.
- Link from AGENTS.md or the nearest index when the doc is a new entry point.

Verification:
- Check links and commands manually.
- Run affected docs or template tests only when rendered docs changed.
```
