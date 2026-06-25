from pathlib import Path

from django.conf import settings

from rowset.utils import get_rowset_logger

logger = get_rowset_logger(__name__)

ROWSET_SKILL_INSTALL_COMMAND = "npx skills add LVTD-LLC/rowset"
ROWSET_SKILL_REPOSITORY_PATH = ".agents/skills/rowset/SKILL.md"
ROWSET_FEATURES_SKILL_REPOSITORY_PATH = ".agents/skills/rowset-features/SKILL.md"
ROWSET_USE_CASES_SKILL_REPOSITORY_PATH = ".agents/skills/rowset-use-cases/SKILL.md"
ROWSET_SKILL_SOURCE_URL = (
    "https://raw.githubusercontent.com/LVTD-LLC/rowset/main/"
    f"{ROWSET_SKILL_REPOSITORY_PATH}"
)
ROWSET_FEATURES_SKILL_SOURCE_URL = (
    "https://raw.githubusercontent.com/LVTD-LLC/rowset/main/"
    f"{ROWSET_FEATURES_SKILL_REPOSITORY_PATH}"
)
ROWSET_USE_CASES_SKILL_SOURCE_URL = (
    "https://raw.githubusercontent.com/LVTD-LLC/rowset/main/"
    f"{ROWSET_USE_CASES_SKILL_REPOSITORY_PATH}"
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
    "invoking named tools. Then call get_user_info to verify authentication, "
    "get_rowset_capabilities to load the current Rowset feature guide, and "
    "get_all_datasets to discover available datasets, get_archived_datasets "
    "before restoring archived datasets, and search_datasets when you need "
    "filters. If auth fails, confirm the env var contains the full key, not "
    "only its prefix. Use get_dataset before row work so dataset context, "
    "schema, and relationships are in context. Use create_dataset when you "
    "need to create a dataset on the fly. Use update_dataset_public_preview "
    "when the user asks for a shareable read-only preview."
)
ROWSET_SKILL_FALLBACK_DESCRIPTION = (
    "Use when a user asks to connect an AI agent to Rowset, configure Rowset MCP "
    "or REST access, or manage Rowset datasets."
)
ROWSET_FEATURES_SKILL_FALLBACK_DESCRIPTION = (
    "Use when a user asks what Rowset can do, which features are available, "
    "or how the current Rowset capabilities fit together."
)
ROWSET_USE_CASES_SKILL_FALLBACK_DESCRIPTION = (
    "Use when a user asks how to use Rowset for a specific workflow, dataset "
    "shape, or agent-owned structured data use case."
)


def rowset_skill_path() -> Path:
    return Path(settings.BASE_DIR) / ROWSET_SKILL_REPOSITORY_PATH


def rowset_features_skill_path() -> Path:
    return Path(settings.BASE_DIR) / ROWSET_FEATURES_SKILL_REPOSITORY_PATH


def rowset_use_cases_skill_path() -> Path:
    return Path(settings.BASE_DIR) / ROWSET_USE_CASES_SKILL_REPOSITORY_PATH


def _build_skill_fallback_markdown(
    *,
    skill_name: str,
    description: str,
    title: str,
    source_url: str,
) -> str:
    return f"""---
name: {skill_name}
description: >
  {description}
---

# {title}

The checked-in Rowset skill file could not be loaded from this deployment.
Install the canonical Rowset skill with:

```bash
{ROWSET_SKILL_INSTALL_COMMAND}
```

Or read the source text:

```text
{source_url}
```
"""


def _load_skill_markdown(
    path: Path,
    fallback_source_url: str,
    fallback_skill_name: str = "rowset",
    fallback_description: str = ROWSET_SKILL_FALLBACK_DESCRIPTION,
    fallback_title: str = "Rowset",
) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning(
            "Rowset skill file could not be loaded",
            path=str(path),
            error=str(exc),
        )
        return _build_skill_fallback_markdown(
            skill_name=fallback_skill_name,
            description=fallback_description,
            title=fallback_title,
            source_url=fallback_source_url,
        )


def load_rowset_skill_markdown() -> str:
    return _load_skill_markdown(rowset_skill_path(), ROWSET_SKILL_SOURCE_URL)


def load_rowset_features_skill_markdown() -> str:
    return _load_skill_markdown(
        rowset_features_skill_path(),
        ROWSET_FEATURES_SKILL_SOURCE_URL,
        fallback_skill_name="rowset-features",
        fallback_description=ROWSET_FEATURES_SKILL_FALLBACK_DESCRIPTION,
        fallback_title="Rowset Features",
    )


def load_rowset_use_cases_skill_markdown() -> str:
    return _load_skill_markdown(
        rowset_use_cases_skill_path(),
        ROWSET_USE_CASES_SKILL_SOURCE_URL,
        fallback_skill_name="rowset-use-cases",
        fallback_description=ROWSET_USE_CASES_SKILL_FALLBACK_DESCRIPTION,
        fallback_title="Rowset Use Cases",
    )
