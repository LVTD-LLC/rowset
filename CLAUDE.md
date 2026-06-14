# CLAUDE.md

Use this file for Claude-specific repo memory. The source of truth is the
vendor-neutral steering set:

- `AGENTS.md` - operating rules and commands.
- `PRODUCT.md` - product context and scope.
- `TECH.md` - stack, commands, runtime constraints, and API/MCP rules.
- `STRUCTURE.md` - where changes belong.
- `VISION.md` - durable product direction and non-goals.
- `DESIGN.md` - visual system and UI constraints.

## Claude Workflow

- Read the relevant steering file before editing.
- Use `rg`/`rg --files` for search.
- Keep views and MCP tools thin; put reusable behavior in services.
- Run tests through `make test ...` instead of host `pytest`.
- Never hand-write migrations. Use `make makemigrations`.
- Ask before destructive data actions or anything that exposes credentials.
- For docs under `apps/docs`, follow `apps/docs/AGENTS.md`.

## High-Risk Areas

- Dataset import/indexing rules in `apps/datasets/services.py`.
- Legacy dataset parser/import behavior in `apps/datasets/services.py` and
  `apps/datasets/tasks.py`.
- MCP OAuth and token handling in `apps/mcp_server/oauth.py`.
- API key handling in `apps/api/auth.py` and MCP auth paths.
- Shared base templates used by both public and authenticated pages.
