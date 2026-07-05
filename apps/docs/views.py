import re
from pathlib import Path

import frontmatter
import markdown
import yaml
from django.conf import settings
from django.http import Http404
from django.shortcuts import redirect, render
from django.template import Context, Template
from django.urls import reverse

from apps.core.agent_skill import (
    ROWSET_AGENT_SETUP_INSTRUCTIONS,
    ROWSET_FEATURES_SKILL_SOURCE_URL,
    ROWSET_SKILL_INSTALL_COMMAND,
    ROWSET_SKILL_SOURCE_URL,
    ROWSET_USE_CASES_SKILL_SOURCE_URL,
)
from apps.core.views import AGENT_API_KEY_MASK
from rowset.utils import build_absolute_public_url, get_rowset_logger

logger = get_rowset_logger(__name__)

API_KEY_PLACEHOLDER = "YOUR_ROWSET_API_KEY"
USER_EMAIL_PLACEHOLDER = "you@example.com"
DOCS_SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")
CATEGORY_LABELS = {
    "tutorials": "Tutorials",
    "how-to-guides": "How-to guides",
    "reference": "Reference",
    "explanation": "Explanation",
}
LEGACY_DOCS_REDIRECTS = {
    ("getting-started", "introduction"): ("tutorials", "get-started"),
    ("features", "mcp"): ("how-to-guides", "connect-mcp"),
    ("features", "agent-access"): ("how-to-guides", "configure-agent-access"),
    ("features", "agent-discovery"): ("how-to-guides", "help-agents-discover-rowset"),
    ("features", "datasets"): ("how-to-guides", "work-with-datasets"),
    ("features", "public-previews"): ("how-to-guides", "share-public-preview"),
    ("api-reference", "introduction"): ("reference", "rest-api"),
    ("api-reference", "user"): ("reference", "user-api"),
    ("api-reference", "projects"): ("reference", "project-api"),
    ("api-reference", "datasets"): ("reference", "dataset-api"),
}


def is_docs_slug(value):
    return bool(DOCS_SLUG_PATTERN.fullmatch(value))


def get_category_title(category_slug):
    return CATEGORY_LABELS.get(category_slug, category_slug.replace("-", " ").title())


def load_navigation_config():
    """
    Load navigation configuration from YAML file.
    Returns empty dict if file doesn't exist or has errors.
    """
    navigation_file = Path(settings.BASE_DIR) / "apps" / "docs" / "navigation.yaml"

    if not navigation_file.exists():
        return {}

    try:
        with open(navigation_file, encoding="utf-8") as file:
            config = yaml.safe_load(file)
            return config.get("navigation", {}) if config else {}
    except Exception:
        return {}


def get_page_title(markdown_file, fallback):
    try:
        with open(markdown_file, encoding="utf-8") as file:
            post = frontmatter.load(file)
        return post.get("title", fallback)
    except Exception:
        return fallback


def get_docs_navigation():  # noqa: C901
    """
    Build navigation structure from the docs/content directory.
    Uses custom ordering from navigation.yaml if defined, otherwise uses alphabetical order.
    Returns a list of dicts with category names and their pages.
    """
    content_dir = Path(settings.BASE_DIR) / "apps" / "docs" / "content"
    navigation = []

    if not content_dir.exists():
        return navigation

    all_categories = {}
    for category_dir in content_dir.iterdir():
        if category_dir.is_dir():
            category_slug = category_dir.name
            all_categories[category_slug] = category_dir

    navigation_config = load_navigation_config()

    ordered_categories = []
    for category_slug in navigation_config.keys():
        if category_slug in all_categories:
            ordered_categories.append(category_slug)

    remaining_categories = sorted(set(all_categories.keys()) - set(ordered_categories))
    if remaining_categories:
        logger.warning(
            "Docs categories missing from navigation.yaml were appended to navigation",
            categories=remaining_categories,
        )
    ordered_categories.extend(remaining_categories)

    for category_slug in ordered_categories:
        category_dir = all_categories[category_slug]
        category_name = get_category_title(category_slug)

        all_pages = {}
        for markdown_file in category_dir.glob("*.md"):
            page_slug = markdown_file.stem
            all_pages[page_slug] = markdown_file

        custom_page_order = navigation_config.get(category_slug, [])

        ordered_pages = []
        for page_slug in custom_page_order:
            if page_slug in all_pages:
                ordered_pages.append(page_slug)

        remaining_pages = sorted(set(all_pages.keys()) - set(ordered_pages))
        ordered_pages.extend(remaining_pages)

        pages = []
        for page_slug in ordered_pages:
            page_title = page_slug.replace("-", " ").title()
            pages.append(
                {
                    "slug": page_slug,
                    "title": get_page_title(all_pages[page_slug], page_title),
                    "url": f"/docs/{category_slug}/{page_slug}/",
                }
            )

        if pages:
            navigation.append(
                {
                    "category": category_name,
                    "category_slug": category_slug,
                    "pages": pages,
                }
            )

    return navigation


def get_flat_page_list(navigation):
    """
    Flatten the navigation structure into a single list of pages in order.
    Returns a list of dicts with category_slug, page_slug, page_title, and url.
    """
    flat_pages = []
    for category_item in navigation:
        for page_item in category_item["pages"]:
            flat_pages.append(
                {
                    "category_slug": category_item["category_slug"],
                    "page_slug": page_item["slug"],
                    "page_title": page_item["title"],
                    "url": page_item["url"],
                }
            )
    return flat_pages


def get_previous_and_next_pages(navigation, current_category, current_page):
    """
    Find the previous and next pages in the documentation navigation.
    Returns a tuple of (previous_page, next_page) where each is a dict or None.
    """
    flat_pages = get_flat_page_list(navigation)

    current_index = None
    for index, page_item in enumerate(flat_pages):
        if (
            page_item["category_slug"] == current_category
            and page_item["page_slug"] == current_page
        ):
            current_index = index
            break

    if current_index is None:
        return None, None

    previous_page = flat_pages[current_index - 1] if current_index > 0 else None
    next_page = flat_pages[current_index + 1] if current_index < len(flat_pages) - 1 else None

    return previous_page, next_page


def docs_home_view(request):
    return render(
        request,
        "docs/docs_home.html",
        {
            "navigation": get_docs_navigation(),
            "docs_base_template": (
                "base_app.html" if request.user.is_authenticated else "base_landing.html"
            ),
        },
    )


def build_docs_agent_setup_prompt():
    mcp_url = build_absolute_public_url("/mcp/")
    rest_api_base_url = build_absolute_public_url("/api/")
    instructions_url = build_absolute_public_url(reverse("agent_instructions_rowset_mcp"))

    return "\n".join(
        [
            "Set up Rowset for this user.",
            "",
            f"Rowset MCP URL: {mcp_url}",
            f"Rowset REST API base: {rest_api_base_url}",
            f"Rowset API key: {AGENT_API_KEY_MASK}",
            f"Rowset skill: {instructions_url}",
            f"Rowset skill install: {ROWSET_SKILL_INSTALL_COMMAND}",
            "",
            ROWSET_AGENT_SETUP_INSTRUCTIONS,
        ]
    )


def get_docs_template_context():
    return {
        "api_base_url": build_absolute_public_url("/api/").rstrip("/"),
        "api_docs_url": build_absolute_public_url("/api/docs"),
        "api_key_placeholder": API_KEY_PLACEHOLDER,
        "agent_setup_prompt_masked": build_docs_agent_setup_prompt(),
        "dashboard_url": build_absolute_public_url(reverse("home")),
        "features_skill_source_url": ROWSET_FEATURES_SKILL_SOURCE_URL,
        "features_skill_url": build_absolute_public_url(
            reverse("agent_instructions_rowset_features")
        ),
        "llms_txt_url": build_absolute_public_url(reverse("llms_txt")),
        "mcp_url": build_absolute_public_url("/mcp/"),
        "settings_url": build_absolute_public_url(reverse("settings")),
        "skill_install_command": ROWSET_SKILL_INSTALL_COMMAND,
        "skill_source_url": ROWSET_SKILL_SOURCE_URL,
        "signup_url": build_absolute_public_url(reverse("account_signup")),
        "site_url": build_absolute_public_url("/").rstrip("/"),
        "use_cases_skill_source_url": ROWSET_USE_CASES_SKILL_SOURCE_URL,
        "use_cases_skill_url": build_absolute_public_url(
            reverse("agent_instructions_rowset_use_cases")
        ),
        "user_email_placeholder": USER_EMAIL_PLACEHOLDER,
    }


def docs_page_view(request, category, page):
    """
    Render a public documentation page from markdown with safe template context.
    """
    if not is_docs_slug(category) or not is_docs_slug(page):
        raise Http404("Documentation page not found")

    redirect_target = LEGACY_DOCS_REDIRECTS.get((category, page))
    if redirect_target is not None:
        redirect_category, redirect_page = redirect_target
        return redirect(
            reverse(
                "docs_page",
                kwargs={"category": redirect_category, "page": redirect_page},
            ),
            permanent=True,
        )

    content_dir = (Path(settings.BASE_DIR) / "apps" / "docs" / "content").resolve()
    markdown_file = (content_dir / category / f"{page}.md").resolve()

    if not markdown_file.is_relative_to(content_dir) or not markdown_file.exists():
        raise Http404("Documentation page not found")

    try:
        with open(markdown_file, encoding="utf-8") as file:
            post = frontmatter.load(file)

        rendered_markdown = Template(post.content).render(Context(get_docs_template_context()))
        markdown_html = markdown.markdown(rendered_markdown, extensions=["fenced_code", "tables"])

        navigation = get_docs_navigation()
        previous_page, next_page = get_previous_and_next_pages(navigation, category, page)
        page_url = build_absolute_public_url(
            reverse("docs_page", kwargs={"category": category, "page": page})
        )

        default_page_title = page.replace("-", " ").title()
        default_category_title = get_category_title(category)

        context = {
            "content": markdown_html,
            "navigation": navigation,
            "current_category": category,
            "current_page": page,
            "page_title": post.get("title", default_page_title),
            "category_title": default_category_title,
            "meta_description": post.get("description", ""),
            "meta_keywords": post.get("keywords", ""),
            "author": post.get("author", ""),
            "canonical_url": post.get("canonical_url", page_url),
            "page_url": page_url,
            "previous_page": previous_page,
            "next_page": next_page,
            "docs_base_template": (
                "base_app.html" if request.user.is_authenticated else "base_landing.html"
            ),
        }

        return render(request, "docs/docs_page.html", context)
    except Exception as e:
        logger.error(
            "Error loading documentation page",
            category=category,
            page=page,
            error=str(e),
        )
        raise Http404("Documentation page not found") from e
