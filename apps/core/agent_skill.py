from pathlib import Path

from django.conf import settings

from rowset.utils import get_rowset_logger

logger = get_rowset_logger(__name__)

ROWSET_SKILL_INSTALL_COMMAND = "npx skills add LVTD-LLC/rowset"
ROWSET_SKILL_REPOSITORY_PATH = ".agents/skills/rowset/SKILL.md"
ROWSET_SKILL_SOURCE_URL = (
    "https://raw.githubusercontent.com/LVTD-LLC/rowset/main/"
    f"{ROWSET_SKILL_REPOSITORY_PATH}"
)
ROWSET_AGENT_SETUP_INSTRUCTIONS = (
    "Read the skill URL or install the repo skill before acting. Store the full "
    "Rowset API key in a private environment variable named ROWSET_API_KEY; do "
    "not print it in logs, screenshots, public chats, generated files, or final "
    "responses. Do not commit it, paste it back to chat, or save it in a "
    "tracked config file. Configure Rowset as a remote Streamable HTTP MCP "
    "server named rowset, using the Rowset MCP URL above and bearer-token env "
    "var ROWSET_API_KEY so requests send Authorization: Bearer <key>. For "
    "Codex/OpenClaw-compatible clients, the setup command is: codex mcp add "
    "rowset --url <Rowset MCP URL> --bearer-token-env-var ROWSET_API_KEY. If "
    "the client only supports custom headers, set Authorization to Bearer "
    "<key>; use X-API-Key only for REST clients that cannot send bearer tokens. "
    "After setup, discover the current MCP tools and API docs at runtime before "
    "invoking named tools. Then call get_user_info to verify authentication and "
    "get_all_datasets to discover available datasets. If auth fails, confirm "
    "the env var contains the full key, not only its prefix. Use create_dataset "
    "when you need to create a dataset on the fly. Use "
    "update_dataset_public_preview when the user asks for a shareable read-only "
    "preview."
)
ROWSET_SKILL_FALLBACK_MARKDOWN = f"""---
name: rowset
description: >
  Use when a user asks to connect an AI agent to Rowset, configure Rowset MCP or REST
  access, or manage Rowset datasets.
---

# Rowset

The checked-in Rowset skill file could not be loaded from this deployment.
Install the canonical Rowset skill with:

```bash
{ROWSET_SKILL_INSTALL_COMMAND}
```

Or read the source text:

```text
{ROWSET_SKILL_SOURCE_URL}
```
"""


def rowset_skill_path() -> Path:
    return Path(settings.BASE_DIR) / ROWSET_SKILL_REPOSITORY_PATH


def load_rowset_skill_markdown() -> str:
    path = rowset_skill_path()
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning(
            "Rowset skill file could not be loaded",
            path=str(path),
            error=str(exc),
        )
        return ROWSET_SKILL_FALLBACK_MARKDOWN
