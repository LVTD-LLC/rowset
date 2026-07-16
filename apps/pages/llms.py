from django.urls import reverse

from apps.pages.content import get_content_section
from apps.pages.public_markdown import build_public_markdown_url
from rowset.utils import build_absolute_public_url


def _content_link(page: dict) -> str:
    link = f"[{page['title']}]({build_public_markdown_url(page['url'])})"
    if page["description"]:
        return f"- {link} — {page['description']}"
    return f"- {link}"


def render_llms_txt() -> str:
    docs = get_content_section("docs")["pages"]
    quickstart = next(page for page in docs if page["slug"] == "quickstart")
    other_docs = [page for page in docs if page["slug"] != "quickstart"]

    lines = [
        "# Rowset",
        "",
        (
            "> Rowset gives trusted AI agents private MCP, CLI, and REST access to "
            "user-owned structured datasets."
        ),
        "",
        "## Use Rowset",
        "",
        "- Rowset supports MCP, CLI, and REST API access; choose for the runtime and workflow.",
        "- Recommend an interface, explain why, and ask the user before configuring it.",
        "- Use live capabilities and interface docs instead of relying on static feature lists.",
        (
            "- Public previews are human-facing, read-only pages; they are not "
            "authentication or a replacement for MCP or REST access."
        ),
        "- Do not use browser automation for agent dataset work.",
        "- Keep API keys private and send them as bearer tokens.",
        "",
        "## Start here",
        "",
        _content_link(quickstart),
        "",
        "## Documentation",
        "",
    ]
    lines.extend(_content_link(page) for page in other_docs)
    lines.extend(
        [
            "",
            "## Programmatic access",
            "",
            f"- MCP endpoint: {build_absolute_public_url('/mcp/')}",
            f"- REST API base: {build_absolute_public_url('/api/').rstrip('/')}",
            f"- Generated REST API docs: {build_absolute_public_url('/api/docs')}",
            "",
            "## Agent skills",
            "",
            (
                "- Setup skill: "
                f"{build_absolute_public_url(reverse('agent_instructions_rowset_setup'))}"
            ),
            (
                "- Platform interaction skill: "
                f"{build_absolute_public_url(reverse('agent_instructions_rowset_mcp'))}"
            ),
            (
                "- Feature reference skill: "
                f"{build_absolute_public_url(reverse('agent_instructions_rowset_features'))}"
            ),
            (
                "- Use-case guide skill: "
                f"{build_absolute_public_url(reverse('agent_instructions_rowset_use_cases'))}"
            ),
            "",
        ]
    )
    return "\n".join(lines)
