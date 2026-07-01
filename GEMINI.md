# GEMINI.md

Start with the repo steering files before making code changes:

- `AGENTS.md`
- `PRODUCT.md`
- `TECH.md`
- `STRUCTURE.md`
- `VISION.md`
- `DESIGN.md`

## Repo Instructions

- Use Docker-backed commands from `AGENTS.md` and `TECH.md`.
- Prefer `make test ...` for verification.
- Do not run host `pytest` as the default path.
- Do not create migrations manually; run `make makemigrations`.
- Keep dataset, REST, and MCP behavior aligned through shared services.
- Keep public previews read-only and separate from authenticated API/MCP access.
- Keep secrets out of code, docs, logs, and responses.

## File Placement

Use `STRUCTURE.md` when deciding where new code belongs. Most dataset behavior
belongs in `apps/datasets/services.py`; REST endpoints belong in `apps/api`;
hosted MCP tools belong in `apps/mcp_server`; browser interactivity belongs in
Django templates with HTMX and Alpine.js, with reusable code in
`frontend/src/js`.
