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
            "> Rowset gives trusted AI agents a private MCP and REST backend for "
            "user-owned structured datasets."
        ),
        "",
        "## Use Rowset",
        "",
        "- Use hosted MCP first for private, authenticated agent workflows.",
        "- Use REST second when MCP is unavailable or a file export is needed.",
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
