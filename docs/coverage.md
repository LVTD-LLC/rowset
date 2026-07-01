# Coverage Visibility

Coverage is a map for agent attention, not a global score target. Use it to find
high-risk code that has weak executable feedback, then add behavior tests for the
specific risk before enforcing any broader gate.

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

Start with visibility only. Do not add a global percentage threshold until the
first CI reports have been reviewed and noisy gaps have been triaged.

Use this ratchet instead:

1. Keep the hotspot coverage report required in CI.
2. For each high-risk module, convert uncovered risky branches into concrete
   test tasks.
3. Add per-module thresholds only after a module has stable tests and low-noise
   missing lines.
4. Prefer behavior-specific regression tests over raising a percentage target.
