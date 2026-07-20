# PostHog MCP Analytics Integration Report

## Summary

The Rowset MCP server (`apps/mcp_server/server.py`) has been instrumented with PostHog MCP analytics using **Path P1** (jlowin FastMCP 2.0 server object wrapped with `instrument()`).

## What was changed

### `apps/mcp_server/server.py`

Added at the top of the file:
- `import os` and `import signal` (stdlib imports)
- `from posthog import Posthog` and `from posthog.mcp import instrument`

Added after the existing module-level imports, before `mcp = FastMCP(...)`:
- A `_posthog` client constructed once at module scope, reading `POSTHOG_PROJECT_TOKEN` and `POSTHOG_HOST` from environment variables.

Added immediately after `mcp = FastMCP(...)`:
- `_mcp_analytics = instrument(mcp, _posthog)` — wraps the FastMCP server so every tool call, tools/list, and initialize handshake emits a `$mcp_*` event in PostHog.

Added a SIGTERM handler:
- `_shutdown_posthog` drains the PostHog client on process shutdown so in-flight events are not dropped.

### `.env`

Added:
- `POSTHOG_PROJECT_TOKEN=phc_pTcV6kftJbpskpn5Pc7yvsqp8XFQShdXgpDAiWD68kj3`

`POSTHOG_HOST` was already present in `.env`.

## Files modified

| File | Change |
|------|--------|
| `apps/mcp_server/server.py` | Added PostHog imports, client, `instrument()` call, SIGTERM flush |
| `.env` | Added `POSTHOG_PROJECT_TOKEN` |

## No manual steps required

`posthog>=7.21.2` was already declared in `pyproject.toml` and installed in `.venv`, so no package installation is needed.

Once the server handles its next MCP request you will see `$mcp_tool_call`, `$mcp_tools_list`, and `$mcp_initialize` events in PostHog.

See the [MCP analytics docs](https://posthog.com/docs/mcp-analytics) for the dashboard template and full event reference.

> **Note:** `posthog.mcp` is pre-1.0 (beta). Pin `posthog>=7.21.2` (already done) and watch for breaking changes in minor releases until v1.
