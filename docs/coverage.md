# Coverage Visibility

Coverage is a map for agent attention, not a global score target. The default
report enforces the current 80% floor to prevent obvious regressions, but the
priority is still to find high-risk code that has weak executable feedback and
add behavior tests for the specific risk.

## Commands

Run a coverage report over any focused pytest target:

```bash
make coverage -- apps/api apps/mcp_server -q
```

Run the CI hotspot report:

```bash
make coverage-high-risk -- apps/api apps/datasets apps/mcp_server -q
```

GitHub Actions runs the same hotspot report with the host-runner override:

```bash
make coverage-high-risk COVERAGE_RUN="bash -c" -- apps/api apps/datasets apps/mcp_server -q
```

Override `COVERAGE_FAIL_UNDER` locally only when exploring a noisy area:

```bash
make coverage-high-risk COVERAGE_FAIL_UNDER=0 -- apps/api -q
```

## High-Risk Modules

The first hotspot report highlights the modules agents are most likely to touch
when changing Rowset behavior:

- `apps/api/services.py` - shared orchestration for REST-facing dataset behavior.
- `apps/datasets/services.py` - parsing, validation, row storage, export, and
  dataset business rules.
- `apps/datasets/vector_search.py` - vector indexing/search behavior and
  external embedding/search boundaries.
- `apps/mcp_server/server.py` - hosted MCP tool surface and REST/MCP parity.

## Ratchet Proposal

Start with the current 80% hotspot floor and raise it only when the missing
branches are well understood. Do not add a whole-repo percentage target until
the first CI reports have been reviewed and noisy gaps have been triaged.

Use this ratchet instead:

1. Keep the hotspot coverage report required in CI with the current floor.
2. For each high-risk module, convert uncovered risky branches into concrete
   test tasks.
3. Add per-module thresholds only after a module has stable tests and low-noise
   missing lines.
4. Prefer behavior-specific regression tests over raising a percentage target.
