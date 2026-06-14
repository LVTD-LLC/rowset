# GitHub Copilot Instructions

Follow the repo steering files before suggesting or applying changes:

- `AGENTS.md` for workflow, commands, guardrails, and code style.
- `PRODUCT.md` for product scope and user workflows.
- `TECH.md` for stack, runtime, API/MCP, and testing details.
- `STRUCTURE.md` for file placement.
- `VISION.md` for long-term direction and non-goals.
- `DESIGN.md` for UI work.

Prefer service-layer changes over duplicated view, template, REST, or MCP logic.
Run tests through `make test ...`. Do not hand-write migrations; use
`make makemigrations`. Keep API keys, OAuth tokens, and private dataset contents
out of generated code, docs, logs, and examples.
