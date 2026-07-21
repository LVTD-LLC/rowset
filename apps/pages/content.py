import re
from pathlib import Path

import frontmatter
import markdown
import yaml
from django.conf import settings
from django.http import Http404
from django.shortcuts import render
from django.template import Context, Template
from django.urls import reverse

from apps.core.agent_skill import (
    ROWSET_AGENT_SETUP_INSTRUCTIONS,
    ROWSET_FEATURES_SKILL_SOURCE_URL,
    ROWSET_SETUP_SKILL_SOURCE_URL,
    ROWSET_SKILL_INSTALL_COMMAND,
    ROWSET_SKILL_SOURCE_URL,
    ROWSET_USE_CASES_SKILL_SOURCE_URL,
)
from apps.core.views import AGENT_API_KEY_MASK
from apps.pages.public_markdown import build_ai_reader_context, build_public_markdown_context
from apps.pages.schema import article_schema, json_ld
from apps.pages.search import build_canonical_url
from rowset.utils import build_absolute_public_url, get_rowset_logger

logger = get_rowset_logger(__name__)

API_KEY_PLACEHOLDER = "YOUR_ROWSET_API_KEY"
USER_EMAIL_PLACEHOLDER = "you@example.com"
CONTENT_SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")
CONTENT_MARKDOWN_EXTENSIONS = ["fenced_code", "tables"]
CONTENT_SECTIONS = {
    "docs": {
        "label": "Docs",
        "title": "Rowset Docs",
        "description": ("Start, use features, and look up reference details from one place."),
        "home_url_name": "docs_home",
        "page_url_name": "docs_page",
    },
    "use-cases": {
        "label": "Use cases",
        "title": "Rowset Use Cases",
        "description": ("Starter dataset shapes for common AI-agent workflows."),
        "home_page_slug": "index",
        "home_url_name": "use_cases",
        "page_url_name": "use_case_page",
    },
}


def is_content_slug(value):
    return bool(CONTENT_SLUG_PATTERN.fullmatch(value))


def get_content_root():
    return Path(settings.BASE_DIR) / "apps" / "pages" / "content"


def get_content_section_config(section_slug):
    try:
        return CONTENT_SECTIONS[section_slug]
    except KeyError as exc:
        raise Http404("Content section not found") from exc


def get_content_section_dir(section_slug):
    return get_content_root() / section_slug


def load_content_navigation_config():
    navigation_file = get_content_root() / "navigation.yaml"

    if not navigation_file.exists():
        return {}

    try:
        with navigation_file.open(encoding="utf-8") as file:
            config = yaml.safe_load(file)
            return config.get("navigation", {}) if config else {}
    except Exception:
        return {}


def get_page_title(markdown_file, fallback):
    return get_page_frontmatter(markdown_file).get("title", fallback)


def get_page_frontmatter(markdown_file):
    try:
        with markdown_file.open(encoding="utf-8") as file:
            post = frontmatter.load(file)
        return post.metadata
    except Exception:
        return {}


def get_section_page_url(section_slug, page_slug):
    config = get_content_section_config(section_slug)
    if page_slug == config.get("home_page_slug"):
        return reverse(config["home_url_name"])
    return reverse(config["page_url_name"], kwargs={"slug": page_slug})


def get_section_home_url(section_slug):
    config = get_content_section_config(section_slug)
    return reverse(config["home_url_name"])


def get_navigation_group_id(label, index):
    group_id = re.sub(r"[^a-z0-9]+", "-", str(label).lower()).strip("-")
    return f"{group_id or 'group'}-{index}"


def get_current_content_group_id(section, current_page):
    for group in section["groups"]:
        if current_page in group["page_slugs"]:
            return group["id"]
    return ""


def get_content_section(section_slug):
    config = get_content_section_config(section_slug)
    content_dir = get_content_section_dir(section_slug)
    navigation_config = load_content_navigation_config()
    configured_order = navigation_config.get(section_slug, [])

    grouped_pages = []
    if not content_dir.exists():
        pages = []
    else:
        all_pages = {
            markdown_file.stem: markdown_file for markdown_file in content_dir.glob("*.md")
        }
        ordered_page_slugs = []
        groups = []
        for item in configured_order:
            if isinstance(item, str):
                ordered_page_slugs.append(item)
                continue
            if not isinstance(item, dict):
                continue
            page_slugs = [
                page_slug for page_slug in item.get("pages", []) if page_slug in all_pages
            ]
            current_page_slugs = [
                page_slug for page_slug in item.get("current_pages", []) if page_slug in all_pages
            ]
            ordered_page_slugs.extend(page_slugs)
            ordered_page_slugs.extend(current_page_slugs)
            group_pages = [{"type": "content", "slug": page_slug} for page_slug in page_slugs]
            groups.append(
                {
                    "id": get_navigation_group_id(item.get("label", ""), len(groups) + 1),
                    "label": item.get("label", ""),
                    "description": item.get("description", ""),
                    "page_slugs": [
                        *page_slugs,
                        *current_page_slugs,
                    ],
                    "pages": group_pages,
                }
            )

        ordered_pages = [page_slug for page_slug in ordered_page_slugs if page_slug in all_pages]
        ordered_pages.extend(sorted(set(all_pages.keys()) - set(ordered_pages)))

        pages = []
        for page_slug in ordered_pages:
            page_title = page_slug.replace("-", " ").title()
            metadata = get_page_frontmatter(all_pages[page_slug])
            pages.append(
                {
                    "slug": page_slug,
                    "title": metadata.get("title", page_title),
                    "description": metadata.get("description", ""),
                    "url": get_section_page_url(section_slug, page_slug),
                }
            )

        page_lookup = {page["slug"]: page for page in pages}
        grouped_pages = [
            {
                "id": group["id"],
                "label": group["label"],
                "description": group["description"],
                "page_slugs": group["page_slugs"],
                "pages": [
                    page_lookup[page["slug"]] if page["type"] == "content" else page["page"]
                    for page in group["pages"]
                ],
            }
            for group in groups
            if group["pages"]
        ]

    return {
        "section_slug": section_slug,
        "label": config["label"],
        "title": config["title"],
        "description": config["description"],
        "url": get_section_home_url(section_slug),
        "pages": pages,
        "groups": grouped_pages,
    }


def get_content_sections():
    return [get_content_section(section_slug) for section_slug in CONTENT_SECTIONS]


def get_previous_and_next_pages(section, current_page):
    pages = section["pages"]
    current_index = None
    for index, page_item in enumerate(pages):
        if page_item["slug"] == current_page:
            current_index = index
            break

    if current_index is None:
        return None, None

    previous_page = pages[current_index - 1] if current_index > 0 else None
    next_page = pages[current_index + 1] if current_index < len(pages) - 1 else None
    return previous_page, next_page


def build_content_agent_setup_prompt():
    mcp_url = build_absolute_public_url("/mcp/")
    rest_api_base_url = build_absolute_public_url("/api/")
    instructions_url = build_absolute_public_url(reverse("agent_instructions_rowset_mcp"))
    setup_instructions_url = build_absolute_public_url(reverse("agent_instructions_rowset_setup"))
    llms_txt_url = build_absolute_public_url(reverse("llms_txt"))
    api_docs_url = build_absolute_public_url("/api/docs")
    cli_docs_url = build_absolute_public_url("/docs/use-cli.md")
    docs_url = build_absolute_public_url(reverse("docs_home"))
    blog_url = build_absolute_public_url(reverse("blog_posts"))
    trial_rewards_url = build_absolute_public_url(reverse("trial_rewards"))

    return "\n".join(
        [
            "Set up Rowset for this user.",
            "",
            f"Rowset MCP URL: {mcp_url}",
            f"Rowset REST API base: {rest_api_base_url}",
            f"Rowset CLI guide: {cli_docs_url}",
            f"Rowset API key: {AGENT_API_KEY_MASK}",
            f"Rowset setup skill: {setup_instructions_url}",
            f"Rowset skill: {instructions_url}",
            f"Rowset skill install: {ROWSET_SKILL_INSTALL_COMMAND}",
            f"Rowset current docs index: {llms_txt_url}",
            f"Rowset docs: {docs_url}",
            f"Rowset blog: {blog_url}",
            f"Rowset current API docs: {api_docs_url}",
            f"Rowset current capabilities: {rest_api_base_url}capabilities",
            f"Rowset trial rewards: {trial_rewards_url}",
            "",
            ROWSET_AGENT_SETUP_INSTRUCTIONS,
        ]
    )


def get_content_template_context():
    return {
        "api_base_url": build_absolute_public_url("/api/").rstrip("/"),
        "api_docs_url": build_absolute_public_url("/api/docs"),
        "api_key_placeholder": API_KEY_PLACEHOLDER,
        "agent_setup_prompt_masked": build_content_agent_setup_prompt(),
        "dashboard_url": build_absolute_public_url(reverse("home")),
        "features_skill_source_url": ROWSET_FEATURES_SKILL_SOURCE_URL,
        "features_skill_url": build_absolute_public_url(
            reverse("agent_instructions_rowset_features")
        ),
        "llms_txt_url": build_absolute_public_url(reverse("llms_txt")),
        "mcp_url": build_absolute_public_url("/mcp/"),
        "settings_url": build_absolute_public_url(reverse("settings")),
        "skill_install_command": ROWSET_SKILL_INSTALL_COMMAND,
        "setup_skill_source_url": ROWSET_SETUP_SKILL_SOURCE_URL,
        "setup_skill_url": build_absolute_public_url(reverse("agent_instructions_rowset_setup")),
        "skill_source_url": ROWSET_SKILL_SOURCE_URL,
        "signup_url": build_absolute_public_url(reverse("account_signup")),
        "site_url": build_absolute_public_url("/").rstrip("/"),
        "use_cases_skill_source_url": ROWSET_USE_CASES_SKILL_SOURCE_URL,
        "use_cases_skill_url": build_absolute_public_url(
            reverse("agent_instructions_rowset_use_cases")
        ),
        "user_email_placeholder": USER_EMAIL_PLACEHOLDER,
    }


def load_content_page(section_slug, page_slug):
    get_content_section_config(section_slug)
    if not is_content_slug(page_slug):
        raise Http404("Content page not found")

    content_dir = get_content_section_dir(section_slug).resolve()
    markdown_file = (content_dir / f"{page_slug}.md").resolve()

    if not markdown_file.is_relative_to(content_dir) or not markdown_file.exists():
        raise Http404("Content page not found")

    try:
        with markdown_file.open(encoding="utf-8") as file:
            post = frontmatter.load(file)

        rendered_markdown = Template(post.content).render(Context(get_content_template_context()))
        return post, rendered_markdown
    except Exception as exc:
        logger.error(
            "Error loading content page",
            section=section_slug,
            page=page_slug,
            error_type=type(exc).__name__,
        )
        raise Http404("Content page not found") from exc


def render_content_page(request, section_slug, page_slug):
    try:
        post, rendered_markdown = load_content_page(section_slug, page_slug)
        markdown_html = markdown.markdown(rendered_markdown, extensions=CONTENT_MARKDOWN_EXTENSIONS)
        section = get_content_section(section_slug)
        previous_page, next_page = get_previous_and_next_pages(section, page_slug)
        page_path = get_section_page_url(section_slug, page_slug)
        page_url = build_absolute_public_url(page_path)
        current_group_id = get_current_content_group_id(section, page_slug)
        markdown_context = (
            build_ai_reader_context(page_path)
            if section_slug == "docs"
            else build_public_markdown_context(page_path)
        )

        default_page_title = page_slug.replace("-", " ").title()

        context = {
            "content": markdown_html,
            "section": section,
            "current_page": page_slug,
            "current_group_id": current_group_id,
            "page_title": post.get("title", default_page_title),
            "seo_title": post.get("seo_title", post.get("title", default_page_title)),
            "section_title": section["label"],
            "meta_description": post.get("description", ""),
            "meta_keywords": post.get("keywords", ""),
            "author": post.get("author", ""),
            "canonical_url": build_canonical_url(page_path),
            "page_url": page_url,
            "previous_page": previous_page,
            "next_page": next_page,
            "schema_json": json_ld(
                article_schema(
                    headline=post.get("title", default_page_title),
                    description=post.get("description", ""),
                    path=page_path,
                )
            ),
            "docs_base_template": (
                "base_app.html" if request.user.is_authenticated else "base_landing.html"
            ),
            **markdown_context,
        }

        return render(request, "pages/content/page.html", context)
    except Http404:
        raise
    except Exception as exc:
        logger.error(
            "Error loading content page",
            section=section_slug,
            page=page_slug,
            error_type=type(exc).__name__,
        )
        raise Http404("Content page not found") from exc
