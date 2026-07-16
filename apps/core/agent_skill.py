from pathlib import Path

from django.conf import settings

from rowset.utils import get_rowset_logger

logger = get_rowset_logger(__name__)

ROWSET_SKILL_INSTALL_COMMAND = "npx skills add LVTD-LLC/rowset"
ROWSET_SKILL_REPOSITORY_PATH = ".agents/skills/rowset/SKILL.md"
ROWSET_FEATURES_SKILL_REPOSITORY_PATH = ".agents/skills/rowset-features/SKILL.md"
ROWSET_USE_CASES_SKILL_REPOSITORY_PATH = ".agents/skills/rowset-use-cases/SKILL.md"
ROWSET_SKILL_SOURCE_URL = (
    f"https://raw.githubusercontent.com/LVTD-LLC/rowset/main/{ROWSET_SKILL_REPOSITORY_PATH}"
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
    "Read or install the Rowset skill before acting, then consult the current "
    "capabilities and documentation resources above. Rowset supports MCP, CLI, "
    "and REST API access. Evaluate which interface best fits your runtime and "
    "the user's likely workflow; do not assume one interface is preferred. "
    "Explain your recommendation briefly and ask the user which interface to "
    "configure before changing their environment or client settings. Store the "
    "full API key in a private environment variable named ROWSET_API_KEY or an "
    "equivalent secret store. Never expose or commit it. Follow the live docs "
    "for the approved interface instead of relying on hardcoded client-specific "
    "commands or static endpoint lists. Make an authenticated user-info request "
    "the final setup step: use get_user_info over MCP, rowset user info through "
    "the CLI, or GET <Rowset REST API base>/user with Authorization: Bearer "
    "<ROWSET_API_KEY>. This verifies the connection, completes onboarding, and "
    "starts the trial. Then report the result and ask what the user wants to do "
    "with Rowset next, including a concise recommendation when context supports one."
)
ROWSET_SKILL_FALLBACK_DESCRIPTION = (
    "Use when a user asks to connect an AI agent to Rowset, configure Rowset MCP "
    "CLI, or REST access, or manage Rowset datasets."
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
            error_type=type(exc).__name__,
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
