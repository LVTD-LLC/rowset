import json
import re
import struct
import time
from dataclasses import replace
from datetime import timedelta
from html import unescape
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from allauth.account.models import EmailAddress
from allauth.mfa.models import Authenticator
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.core.exceptions import ImproperlyConfigured
from django.templatetags.static import static
from django.test import override_settings
from django.urls import resolve, reverse
from django.utils.html import strip_tags
from PIL import Image

from apps.core.capabilities import RowsetUseCase
from apps.pages import use_cases as page_use_cases
from apps.pages.checks import check_use_case_page_registry
from apps.pages.comparisons import get_comparison_page
from apps.pages.content import get_content_section
from apps.pages.public_markdown import markdown_path_for
from apps.pages.schema import (
    article_schema,
    breadcrumb_list_schema,
    faq_page_schema,
    json_ld,
    use_case_item_list_schema,
)

pytestmark = pytest.mark.django_db


PUBLIC_CONTENT_PATH_PREFIXES = ("/blog/", "/docs/", "/use-cases/", "/vs/")
PUBLIC_CONTENT_ROOT_PATHS = {
    "/blog",
    "/changelog",
    "/docs",
    "/pricing",
    "/privacy-policy",
    "/terms-of-service",
    "/use-cases",
    "/uses",
}


def _public_source_markdown_paths():
    return Path(settings.BASE_DIR, "apps/pages/content").rglob("*.md")


def _public_content_links(source):
    markdown_targets = re.findall(r"(?<!!)\[[^]]*]\(([^)\s]+)(?:\s+[^)]*)?\)", source)
    html_targets = re.findall(r'href=["\']([^"\']+)["\']', source)
    for target in (*markdown_targets, *html_targets):
        parsed = urlparse(unescape(target))
        if parsed.scheme or parsed.netloc or not parsed.path.startswith("/"):
            continue
        if parsed.path in PUBLIC_CONTENT_ROOT_PATHS or parsed.path.startswith(
            PUBLIC_CONTENT_PATH_PREFIXES
        ):
            yield target, parsed.path


def test_checked_in_markdown_public_content_links_use_live_extensionless_routes(client):
    retired_routes = []
    broken_routes = []

    for markdown_path in _public_source_markdown_paths():
        source = markdown_path.read_text(encoding="utf-8")
        for target, path in _public_content_links(source):
            location = str(markdown_path.relative_to(settings.BASE_DIR))
            if path != "/" and path.endswith("/"):
                retired_routes.append(f"{location}: {target}")
                continue
            if client.get(path).status_code == 404:
                broken_routes.append(f"{location}: {target}")

    assert not retired_routes, "Retired trailing-slash public routes:\n" + "\n".join(retired_routes)
    assert not broken_routes, "Broken public content routes:\n" + "\n".join(broken_routes)


@pytest.mark.parametrize(
    "path",
    (
        "/index.md",
        "/pricing.md",
        "/privacy-policy.md",
        "/terms-of-service.md",
        "/docs.md",
        "/blog.md",
        "/changelog.md",
        "/uses.md",
        "/use-cases.md",
        "/docs/quickstart.md",
        "/use-cases/personal-crm.md",
        "/vs/airtable.md",
        "/vs/google-sheets.md",
    ),
)
def test_public_markdown_routes_return_markdown(client, path):
    response = client.get(path)

    assert response.status_code == 200
    assert response.headers["Content-Type"] == "text/markdown; charset=utf-8"


@pytest.mark.parametrize(
    ("path", "expected_heading"),
    (
        ("/index.md", "# Rowset"),
        ("/pricing.md", "# Rowset pricing"),
        ("/privacy-policy.md", "# Privacy Policy"),
        ("/terms-of-service.md", "# Terms of Service"),
        ("/uses.md", "# Technology behind Rowset"),
        ("/blog.md", "# Rowset field notes"),
        ("/changelog.md", "# Changelog"),
        ("/docs/database-mcp-server.md", "# Database MCP server"),
        ("/vs/airtable.md", "# Rowset vs Airtable"),
        ("/vs/google-sheets.md", "# Rowset vs Google Sheets"),
    ),
)
def test_public_markdown_inventory_has_curated_content(client, path, expected_heading):
    response = client.get(path)

    assert response.status_code == 200
    content = response.content.decode()
    assert expected_heading in content
    assert not content.startswith("---")
    assert "<html" not in content.lower()
    assert "<nav" not in content.lower()
    assert "{{" not in content


def test_public_markdown_inventory_registry_reuses_canonical_sources():
    from apps.pages.public_markdown import CURATED_PUBLIC_PAGE_SOURCES

    assert CURATED_PUBLIC_PAGE_SOURCES == {
        "blog": "public/blog.md",
        "index": "public/index.md",
        "pricing": "public/pricing.md",
        "privacy-policy": "public/privacy-policy.md",
        "terms-of-service": "public/terms-of-service.md",
        "uses": "public/uses.md",
    }


def test_database_mcp_server_markdown_contains_complete_decision_guide(client):
    response = client.get("/docs/database-mcp-server.md")

    assert response.status_code == 200
    content = response.content.decode()
    assert "## The decision" in content
    assert "## Implementation checklist" in content
    assert "## Bottom line" in content


def test_public_markdown_route_name_and_missing_slug(client):
    assert reverse("public_page_markdown", kwargs={"page_slug": "index"}) == "/index.md"
    assert client.get("/missing.md").status_code == 404


@override_settings(SITE_URL="https://rowset.example")
@pytest.mark.parametrize(
    ("path", "expected_markdown_url"),
    (
        ("/", "https://rowset.example/index.md"),
        ("/pricing", "https://rowset.example/pricing.md"),
        ("/privacy-policy", "https://rowset.example/privacy-policy.md"),
        ("/terms-of-service", "https://rowset.example/terms-of-service.md"),
        ("/uses", "https://rowset.example/uses.md"),
        ("/blog", "https://rowset.example/blog.md"),
        ("/changelog", "https://rowset.example/changelog.md"),
        (
            "/blog/agent-managed-datasets",
            "https://rowset.example/blog/agent-managed-datasets.md",
        ),
        ("/use-cases", "https://rowset.example/use-cases.md"),
        (
            "/use-cases/personal-crm",
            "https://rowset.example/use-cases/personal-crm.md",
        ),
        ("/docs/quickstart", "https://rowset.example/docs/quickstart.md"),
        (
            "/docs/database-mcp-server",
            "https://rowset.example/docs/database-mcp-server.md",
        ),
    ),
)
def test_public_html_views_advertise_canonical_markdown_url(client, path, expected_markdown_url):
    response = client.get(path)

    assert response.status_code == 200
    assert response.context["markdown_url"] == expected_markdown_url
    assert (
        f'<link rel="alternate" type="text/markdown" href="{expected_markdown_url}"'
        in response.content.decode()
    )


@override_settings(SITE_URL="https://rowset.example")
def test_content_markdown_renders_public_template_variables_without_frontmatter(client):
    response = client.get(reverse("content_page_markdown", args=("docs", "quickstart")))

    assert response.status_code == 200
    content = response.content.decode()
    assert not content.startswith("---")
    assert "# Start with your first agent dataset" in content
    assert "https://rowset.example/mcp/" in content
    assert "Authorization: Bearer YOUR_ROWSET_API_KEY" in content
    assert "{{" not in content


@override_settings(SITE_URL="https://rowset.example")
def test_docs_index_markdown_reuses_rendered_quickstart(client):
    response = client.get("/docs.md")

    assert response.status_code == 200
    content = response.content.decode()
    assert not content.startswith("---")
    assert "# Start with your first agent dataset" in content
    assert "https://rowset.example/mcp/" in content
    assert "{{" not in content


def test_user_api_markdown_uses_canonical_trial_upgrade_url(client):
    response = client.get("/docs/user-api.md")

    assert response.status_code == 200
    content = response.content.decode()
    assert "https://rowset.com/pricing" in content
    assert "https://rowset.com/pricing/" not in content


@override_settings(SITE_URL="https://rowset.example")
def test_llms_txt_is_a_documentation_only_content_index(client):
    assert resolve(reverse("llms_txt")).func.__module__ == "apps.pages.views"

    response = client.get(reverse("llms_txt"))

    assert response.status_code == 200
    assert response["Content-Type"] == "text/plain; charset=utf-8"
    assert response["Cache-Control"] == "public, max-age=300"
    content = response.content.decode()

    docs = get_content_section("docs")["pages"]
    quickstart_url = "https://rowset.example/docs/quickstart.md"

    assert docs[0]["slug"] == "quickstart"
    assert content.index(quickstart_url) < min(
        content.index(f"https://rowset.example{markdown_path_for(page['url'])}")
        for page in docs
        if page["slug"] != "quickstart"
    )
    for page in docs:
        assert page["description"]
        markdown_url = f"https://rowset.example{markdown_path_for(page['url'])}"
        assert f"[{page['title']}]({markdown_url})" in content
        assert page["description"] in content

    assert "Use hosted MCP first" in content
    assert "Use REST second" in content
    assert "Do not use browser automation" in content
    assert "human-facing, read-only" in content
    assert "not authentication" in content
    assert "https://rowset.example/mcp/" in content
    assert "https://rowset.example/api" in content
    assert "https://rowset.example/api/docs" in content
    assert "https://rowset.example/SKILL.md" in content
    assert "https://rowset.example/skills/rowset-features/SKILL.md" in content
    assert "https://rowset.example/skills/rowset-use-cases/SKILL.md" in content
    assert "## Use cases" not in content
    assert "## Comparisons" not in content
    assert "https://rowset.example/use-cases/" not in content
    assert "https://rowset.example/vs/" not in content
    assert "https://rowset.example/blog/" not in content
    assert "MCP tools:" not in content
    assert "REST paths:" not in content


@pytest.mark.parametrize(
    "path",
    (
        "/docs/missing.md",
        "/use-cases/missing.md",
        "/docs/not_valid.md",
        "/missing/page.md",
    ),
)
def test_content_markdown_routes_404_for_missing_or_invalid_slugs(client, path):
    assert client.get(path).status_code == 404


@pytest.mark.parametrize(
    ("path", "expected"),
    (
        ("/", "/index.md"),
        ("/pricing", "/pricing.md"),
        ("/docs/quickstart/", "/docs/quickstart.md"),
    ),
)
def test_markdown_path_for_builds_route_siblings(path, expected):
    from apps.pages.public_markdown import markdown_path_for

    assert markdown_path_for(path) == expected


AI_READER_ACTION_LABELS = (
    "Read with Claude",
    "Read with ChatGPT",
    "Copy Prompt for your AI Agent",
    "Copy Markdown",
)


def _assert_ai_reader_menu(content, markdown_url):
    prompt = f"Read this Rowset page and help me understand or use it: {markdown_url}"

    for label in AI_READER_ACTION_LABELS:
        assert content.count(label) == 1
    assert [content.index(label) for label in AI_READER_ACTION_LABELS] == sorted(
        content.index(label) for label in AI_READER_ACTION_LABELS
    )

    assert f'data-markdown-url="{markdown_url}"' in content
    assert f'data-prompt="{prompt}"' in content
    trigger = re.search(
        r'<button type="button"[^>]*x-ref="trigger"[^>]*>(.*?)</button>',
        content,
        re.DOTALL,
    )
    assert trigger
    assert strip_tags(trigger.group(1)).strip() == "Read with AI"
    assert ':aria-expanded="open.toString()"' in content
    assert "x-cloak" in content
    assert "@click.outside" in content
    assert "@keydown.escape" in content
    assert 'role="status"' in content
    assert 'x-text="status"' in content
    assert "x-html" not in content

    provider_links = re.findall(r'<a href="(https://(?:chatgpt|claude)\.[^"]+)"([^>]*)>', content)
    assert len(provider_links) == 2
    for _, attributes in provider_links:
        assert 'target="_blank"' in attributes
        assert 'rel="noopener"' in attributes

    provider_urls = [url for url, _ in provider_links]
    assert len(provider_urls) == 2
    for provider_url in provider_urls:
        decoded_query = parse_qs(urlparse(unescape(provider_url)).query)
        assert decoded_query["q"] == [prompt]


@override_settings(SITE_URL="https://rowset.example")
@pytest.mark.parametrize(
    ("url", "markdown_url"),
    (
        (
            reverse("docs_page", kwargs={"slug": "quickstart"}),
            "https://rowset.example/docs/quickstart.md",
        ),
        (
            reverse("docs_page", kwargs={"slug": "database-mcp-server"}),
            "https://rowset.example/docs/database-mcp-server.md",
        ),
    ),
)
def test_ai_reader_menu_renders_for_docs_articles(client, url, markdown_url):
    response = client.get(url)

    assert response.status_code == 200
    _assert_ai_reader_menu(response.content.decode(), markdown_url)


@override_settings(SITE_URL="https://rowset.example")
@pytest.mark.parametrize(
    "url",
    (
        reverse("use_cases"),
        reverse("use_case_page", kwargs={"slug": "personal-crm"}),
    ),
)
def test_ai_reader_menu_is_absent_from_use_case_pages(client, url):
    response = client.get(url)

    assert response.status_code == 200
    content = response.content.decode()
    for label in AI_READER_ACTION_LABELS:
        assert label not in content


def _nav_html(content, aria_label):
    start = content.index(f'aria-label="{aria_label}"')
    return content[start : content.index("</nav>", start)]


def _section_html(content, section_id):
    start = content.index(f'<section id="{section_id}"')
    return content[start : content.index("</section>", start)]


def _json_ld_payload(content):
    start = content.index('<script type="application/ld+json">')
    end = content.index("</script>", start)
    return content[start:end].split(">", 1)[1].strip()


def test_login_page_shows_passkey_option(client):
    response = client.get(reverse("account_login"))
    assert response.status_code == 200

    content = response.content.decode()
    assert "Sign in with a passkey" in content
    assert 'id="mfa_login"' in content
    assert "window.webauthnJSON.get(requestOptions)" in content
    assert "X-Requested-With" in content
    assert "allauth.webauthn.forms.loginForm" not in content


def test_signup_page_hides_passkey_signup_option(client):
    response = client.get(reverse("account_signup"))
    assert response.status_code == 200

    content = response.content.decode()
    assert "Username" not in content
    assert "Confirm Password" not in content
    assert "Cofirm Password" not in content
    assert "Sign up using a passkey" not in content


def test_login_page_uses_email_instead_of_username(client):
    response = client.get(reverse("account_login"))
    assert response.status_code == 200

    content = response.content.decode()
    assert 'placeholder="Email"' in content
    assert 'type="email"' in content
    assert 'placeholder="Username"' not in content


def test_signup_redirects_to_dashboard_without_blocking_email_code_page(
    client, monkeypatch, settings
):
    sent_confirmations = []

    def fake_send_confirmation_mail(self, request, emailconfirmation, signup):
        sent_confirmations.append((emailconfirmation.email_address.email, signup))

    monkeypatch.setattr(
        "rowset.adapters.CustomAccountAdapter.send_confirmation_mail",
        fake_send_confirmation_mail,
    )
    settings.POSTHOG_API_KEY = ""

    response = client.post(
        reverse("account_signup"),
        data={
            "email": "newuser@example.com",
            "password1": "strong-test-pass-123",
        },
    )

    assert response.status_code == 302
    assert response["Location"] == reverse("home")
    user = get_user_model().objects.get(email="newuser@example.com")
    assert user.username
    assert sent_confirmations == [("newuser@example.com", True)]


def test_dashboard_does_not_show_email_confirmation_reminder(client):
    user = get_user_model().objects.create_user(
        username="unverified",
        email="unverified@example.com",
        password="strong-test-pass-123",
    )
    EmailAddress.objects.update_or_create(
        user=user,
        email=user.email,
        defaults={"primary": True, "verified": False},
    )
    client.force_login(user)

    response = client.get(reverse("home"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Your email is not yet confirmed" not in content
    assert "Connect your AI agent to Rowset" in content


def test_landing_page_omits_prompt_and_shows_agent_native_positioning(client):
    response = client.get(reverse("landing"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Agent setup prompt" not in content
    assert "Rowset MCP URL:" not in content
    assert "Rowset skill install:" not in content
    assert "Agent-native data backend" in content
    assert "Dataset backends for AI agents" in content
    assert "Three steps to agent-ready data" in content
    assert "Agent task board" in content
    assert "Feedback triage" in content
    assert "Personal CRM" in content
    assert reverse("use_cases") in content
    assert reverse("docs_page", kwargs={"slug": "connect-mcp"}) in content
    assert reverse("docs_page", kwargs={"slug": "dataset-api"}) in content
    assert reverse("docs_page", kwargs={"slug": "configure-agent-access"}) in content
    assert '"@type": "SoftwareApplication"' in content
    assert '"@type": "Organization"' in content
    assert "LVTD" not in content.partition("<title>")[2].partition("</title>")[0]
    assert f"&copy; {time.localtime().tm_year} Rowset" in content


def test_public_layout_keeps_footer_at_viewport_bottom(client):
    response = client.get(reverse("pricing"))

    assert response.status_code == 200
    content = response.content.decode()
    assert 'class="isolate flex min-h-dvh flex-col ' in content
    assert '<main id="main-content" tabindex="-1" class="flex-1">' in content


def test_landing_page_shows_product_dashboard_screenshot(client):
    response = client.get(reverse("landing"))

    assert response.status_code == 200
    content = response.content.decode()
    light_screenshot = "vendors/images/landing/product-dashboard-light.webp"
    dark_screenshot = "vendors/images/landing/product-dashboard-dark.webp"
    assert f'src="{static(light_screenshot)}"' in content
    assert f'src="{static(dark_screenshot)}"' in content
    screenshot_alt = 'alt="Rowset dashboard showing projects and recently updated datasets"'
    assert content.count(screenshot_alt) == 2
    assert content.count('width="1600"') == 2
    assert content.count('height="1000"') == 2
    assert 'class="block h-auto w-full bg-white dark:hidden"' in content
    assert 'class="hidden h-auto w-full bg-slate-950 dark:block"' in content

    for screenshot_name in (light_screenshot, dark_screenshot):
        screenshot_path = settings.BASE_DIR / "frontend" / screenshot_name
        with Image.open(screenshot_path) as screenshot:
            assert screenshot.format == "WEBP"
            assert screenshot.size == (1600, 1000)


def test_landing_page_links_to_projects_using_rowset(client):
    response = client.get(reverse("landing"))

    assert response.status_code == 200
    content = response.content.decode()
    projects = (
        ("djass.dev", "djass.svg"),
        ("awesome.lvtd.dev", "awesome.svg"),
        ("builtwithdjango.com", "builtwithdjango.png"),
        ("gettjalerts.com", "gettjalerts.png"),
        ("gettalentleads.com", "gettalentleads.png"),
        ("pagefresh.lvtd.dev", "pagefresh.svg"),
        ("pgsandbox-mcp.lvtd.dev", "pgsandbox-mcp.svg"),
    )

    assert "Projects that use Rowset" in content
    assert "data-uidotsh" not in content
    assert "ui-picker.js" not in content
    for hostname, icon_name in projects:
        assert content.count(f'href="https://{hostname}/"') == 2
        assert content.count(f'aria-label="Visit {hostname} in a new tab"') == 1
        icon_path = f"vendors/images/landing/customer-icons/{icon_name}"
        assert content.count(f'src="{static(icon_path)}"') == 2


def test_landing_page_presents_open_source_and_self_hosting_as_core_identity(client):
    response = client.get(reverse("landing"))

    assert response.status_code == 200
    content = response.content.decode()
    hero = _section_html(content, "product")
    open_source_section = _section_html(content, "open-source")
    primary_nav = _nav_html(content, "Primary navigation")
    mobile_nav = _nav_html(content, "Mobile navigation")
    footer_nav = _nav_html(content, "Footer navigation")
    repository_href = 'href="https://github.com/LVTD-LLC/rowset"'
    self_hosting_href = 'href="https://github.com/LVTD-LLC/rowset#deployment"'
    meta_description = (
        '<meta name="description" content="An open-source and self-hostable backend for AI '
        "agent workflows. Create, search, update, export, and share structured datasets through "
        'MCP, REST, or CLI." />'
    )

    assert "OPEN SOURCE / SELF-HOSTABLE" in hero
    assert "open-source and self-hostable" in hero
    assert "View source on GitHub" in hero
    assert "Open source. Self-hostable." in open_source_section
    assert "Run Rowset in our cloud or on your own infrastructure." in open_source_section
    assert self_hosting_href in open_source_section
    assert "open-source" in content.partition("<title>")[2].partition("</title>")[0]
    assert meta_description in content
    assert repository_href in primary_nav
    assert repository_href in mobile_nav
    assert repository_href in footer_nav
    assert self_hosting_href in footer_nav


def test_shared_site_chrome_links_to_blog_from_navbar_and_footer(client):
    blog_href = f'href="{reverse("blog_posts")}"'
    docs_href = f'href="{reverse("docs_home")}"'
    use_cases_href = f'href="{reverse("use_cases")}"'
    changelog_href = f'href="{reverse("changelog")}"'

    landing_response = client.get(reverse("landing"))
    assert landing_response.status_code == 200
    landing_content = landing_response.content.decode()
    landing_footer = _nav_html(landing_content, "Footer navigation")

    assert blog_href in _nav_html(landing_content, "Primary navigation")
    assert blog_href in _nav_html(landing_content, "Mobile navigation")
    assert blog_href in landing_footer
    assert docs_href in _nav_html(landing_content, "Primary navigation")
    assert docs_href in _nav_html(landing_content, "Mobile navigation")
    assert docs_href in landing_footer
    assert use_cases_href in _nav_html(landing_content, "Primary navigation")
    assert use_cases_href in _nav_html(landing_content, "Mobile navigation")
    assert use_cases_href in landing_footer
    assert changelog_href in landing_footer
    assert "Alternatives" not in landing_footer

    user = get_user_model().objects.create_user(
        username="chrome-blog",
        email="chrome-blog@example.com",
        password="strong-test-pass-123",
    )
    client.force_login(user)

    app_response = client.get(reverse("home"))
    assert app_response.status_code == 200
    app_content = app_response.content.decode()
    app_help = _nav_html(app_content, "Help and support")

    assert blog_href in app_help
    assert docs_href in app_help
    assert use_cases_href in app_help
    assert changelog_href in app_help
    assert "Alternatives" not in app_help


def test_footer_has_a_separate_compare_column(client):
    response = client.get(reverse("landing"))

    assert response.status_code == 200
    footer_nav = _nav_html(response.content.decode(), "Footer navigation")
    assert ">Compare</h2>" in footer_nav
    assert f'href="{reverse("comparison_page", kwargs={"slug": "airtable"})}"' in footer_nav
    assert ">Rowset vs Airtable</a>" in footer_nav
    assert f'href="{reverse("comparison_page", kwargs={"slug": "google-sheets"})}"' in footer_nav
    assert ">Rowset vs Google Sheets</a>" in footer_nav


def test_changelog_html_and_markdown_share_the_repository_changelog(client):
    html_response = client.get(reverse("changelog"))
    markdown_response = client.get(reverse("changelog_markdown"))
    source = Path(settings.BASE_DIR, "CHANGELOG.md").read_text(encoding="utf-8")

    assert html_response.status_code == 200
    assert markdown_response.status_code == 200
    assert markdown_response.content.decode() == f"{source.rstrip()}\n"
    assert "Product updates" in html_response.content.decode()
    assert "Added a public changelog page" in html_response.content.decode()


def test_app_sidebar_shows_trial_rewards_after_agent_setup_completes(client):
    rewards_href = f'href="{reverse("trial_rewards")}"'
    user = get_user_model().objects.create_user(
        username="sidebar-trial-rewards",
        email="sidebar-trial-rewards@example.com",
        password="strong-test-pass-123",
    )
    client.force_login(user)

    initial_response = client.get(reverse("home"))
    initial_help = _nav_html(initial_response.content.decode(), "Help and support")
    assert rewards_href not in initial_help

    profile = user.profile
    profile.trial_started_at = profile.created_at
    profile.trial_ends_at = profile.created_at + timedelta(days=7)
    profile.save(update_fields=["trial_started_at", "trial_ends_at", "updated_at"])

    started_response = client.get(reverse("home"))
    started_help = _nav_html(started_response.content.decode(), "Help and support")
    assert rewards_href not in started_help

    profile.setup_completed_at = profile.created_at
    profile.save(update_fields=["setup_completed_at", "updated_at"])

    completed_response = client.get(reverse("home"))
    completed_help = _nav_html(completed_response.content.decode(), "Help and support")
    assert rewards_href in completed_help
    assert "Earn trial days" in completed_help


def test_uses_page_lists_stack_tools_and_is_linked_from_footer(client):
    uses_response = client.get(reverse("uses"))
    landing_response = client.get(reverse("landing"))
    markdown_response = client.get("/uses.md")

    assert uses_response.status_code == 200
    assert landing_response.status_code == 200
    assert markdown_response.status_code == 200
    assert 'href="https://posthog.com/"' in uses_response.content.decode()
    assert 'href="https://djass.dev/"' in uses_response.content.decode()
    assert "[PostHog](https://posthog.com/)" in markdown_response.content.decode()
    assert "[Djass](https://djass.dev/)" in markdown_response.content.decode()
    footer_nav = _nav_html(landing_response.content.decode(), "Footer navigation")
    assert f'href="{reverse("uses")}"' in footer_nav
    assert ">Uses</a>" in footer_nav


def test_public_nav_links_to_root_content_sections(client):
    response = client.get(reverse("landing"))

    assert response.status_code == 200
    content = response.content.decode()
    primary_nav = _nav_html(content, "Primary navigation")
    mobile_nav = _nav_html(content, "Mobile navigation")
    footer_nav = _nav_html(content, "Footer navigation")

    expected_hrefs = (
        reverse("docs_home"),
        reverse("blog_posts"),
        reverse("use_cases"),
    )
    assert "Resources" not in primary_nav
    assert "Use Cases" in primary_nav
    assert "How it works" not in primary_nav
    assert "How it works" not in mobile_nav
    assert "Tutorials" not in footer_nav
    assert "How-to guides" not in footer_nav
    assert "Explanations" not in footer_nav
    assert f'href="{reverse("docs_page", kwargs={"slug": "quickstart"})}"' in footer_nav
    for href in expected_hrefs:
        assert f'href="{href}"' in primary_nav
        assert f'href="{href}"' in mobile_nav
        assert f'href="{href}"' in footer_nav


def test_docs_home_redirects_to_quickstart(client):
    response = client.get(reverse("docs_home"))

    assert response.status_code == 301
    assert response["Location"] == reverse("docs_page", kwargs={"slug": "quickstart"})


def test_docs_pages_use_grouped_user_job_sidebar(client):
    response = client.get(reverse("docs_page", kwargs={"slug": "project-api"}))

    assert response.status_code == 200
    content = response.content.decode()
    docs_nav = _nav_html(content, "Docs pages")
    docs_left_sidebar = content[: content.index('aria-label="Page table of contents"')]
    assert "Explore" not in docs_nav
    assert "Docs home" not in docs_nav
    assert "Blog" not in docs_nav
    assert "transition" not in docs_nav
    assert "x-show" not in docs_nav
    assert "x-transition" not in docs_nav
    assert "<button" not in docs_nav
    assert 'x-data="docsToc"' not in docs_left_sidebar
    assert "Getting started" in docs_nav
    assert "Features" in docs_nav
    assert "Use cases" not in docs_nav
    assert "Reference" in docs_nav
    assert "Operate" not in docs_nav
    assert reverse("docs_page", kwargs={"slug": "quickstart"}) in content
    assert reverse("docs_page", kwargs={"slug": "create-datasets"}) in content
    assert reverse("docs_page", kwargs={"slug": "share-public-previews"}) in content
    assert reverse("docs_page", kwargs={"slug": "organize-projects"}) not in docs_nav
    assert reverse("docs_page", kwargs={"slug": "link-datasets"}) not in docs_nav
    assert reverse("docs_page", kwargs={"slug": "attach-images"}) not in docs_nav
    assert reverse("use_case_page", kwargs={"slug": "personal-crm"}) not in docs_nav
    assert reverse("use_case_page", kwargs={"slug": "agent-task-board"}) not in docs_nav
    assert reverse("use_case_page", kwargs={"slug": "content-pipeline"}) not in docs_nav
    assert reverse("docs_page", kwargs={"slug": "api-overview"}) in content
    assert reverse("docs_page", kwargs={"slug": "use-cli"}) in content
    assert reverse("docs_page", kwargs={"slug": "dataset-api"}) in content
    assert reverse("docs_page", kwargs={"slug": "mcp-tools"}) in content
    assert reverse("docs_page", kwargs={"slug": "connect-mcp"}) in content
    assert reverse("docs_page", kwargs={"slug": "user-api"}) not in docs_nav
    assert reverse("docs_page", kwargs={"slug": "project-api"}) not in docs_nav
    assert reverse("docs_page", kwargs={"slug": "agent-discovery"}) not in docs_nav
    assert reverse("docs_page", kwargs={"slug": "database-mcp-server"}) not in docs_nav


def test_docs_sidebar_lists_groups_without_disclosure_controls(client):
    response = client.get(reverse("docs_page", kwargs={"slug": "quickstart"}))

    assert response.status_code == 200
    content = response.content.decode()
    sidebar = _nav_html(content, "Docs pages")

    assert "Docs home" not in sidebar
    assert ">Docs<" not in sidebar
    assert 'x-data="docsToc"' not in sidebar
    assert 'id="docs-nav-panel-getting-started-1"' not in sidebar
    assert 'id="docs-nav-panel-features-2"' not in sidebar
    assert "<button" not in sidebar
    assert "grid-template-rows" not in sidebar
    assert "inert" not in sidebar
    assert "transition" not in sidebar
    assert "Start with your first agent dataset" in sidebar
    assert "Share a dataset for read-only access" in sidebar
    assert reverse("use_case_page", kwargs={"slug": "personal-crm"}) not in sidebar
    assert reverse("use_case_page", kwargs={"slug": "agent-task-board"}) not in sidebar
    assert reverse("use_case_page", kwargs={"slug": "bug-qa-tracker"}) not in sidebar
    assert f'href="{reverse("use_cases")}"' not in sidebar
    assert "hover:prose-a:underline" not in content
    assert "prose-a:hover:underline" in content


@override_settings(SITE_URL="https://rowset.example")
def test_root_content_sections_render_markdown_pages(client):
    cases = (
        (reverse("docs_page", kwargs={"slug": "user-api"}), "User API"),
        (
            reverse("docs_page", kwargs={"slug": "quickstart"}),
            "Start with your first agent dataset",
        ),
        (reverse("docs_page", kwargs={"slug": "connect-mcp"}), "Connect over MCP"),
        (reverse("docs_page", kwargs={"slug": "use-cli"}), "Use Rowset from the CLI"),
        (reverse("docs_page", kwargs={"slug": "datasets"}), "How Rowset datasets work"),
    )

    for url, expected_title in cases:
        response = client.get(url)

        assert response.status_code == 200
        content = response.content.decode()
        assert expected_title in content
        assert "Authorization: Bearer YOUR_ROWSET_API_KEY" in content or "dataset" in content


@override_settings(SITE_URL="https://self-hosted.example")
def test_connection_docs_explain_self_hosted_instance_urls(client):
    cases = (
        ("connect-mcp", "https://self-hosted.example/mcp/"),
        ("api-overview", "https://self-hosted.example/api"),
    )

    for slug, expected in cases:
        response = client.get(reverse("docs_page", kwargs={"slug": slug}))

        assert response.status_code == 200
        content = response.content.decode()
        assert expected in content
        assert "self-hosted" in content

    cli_response = client.get(reverse("docs_page", kwargs={"slug": "use-cli"}))

    assert cli_response.status_code == 200
    cli_content = cli_response.content.decode()
    assert "--api-base" in cli_content
    assert "ROWSET_API_BASE" in cli_content
    assert "https://rowset.example.com/api/" in cli_content


def test_use_cases_page_lists_use_case_pages(client):
    response = client.get(reverse("use_cases"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Start here when you know the job" in content
    assert reverse("use_case_page", kwargs={"slug": "personal-crm"}) in content
    assert reverse("use_case_page", kwargs={"slug": "agent-task-board"}) in content
    assert "/how-to/personal-crm/" not in content


def test_landing_page_redirects_authenticated_users_to_home(client):
    user = get_user_model().objects.create_user(
        username="landing-auth",
        email="landing-auth@example.com",
        password="strong-test-pass-123",
    )
    client.force_login(user)

    response = client.get(reverse("landing"))

    assert response.status_code == 302
    assert response["Location"] == reverse("home")


@override_settings(SITE_URL="https://rowset.example")
@pytest.mark.parametrize(
    "route_name",
    ("landing", "changelog", "pricing", "privacy_policy", "terms_of_service", "uses"),
)
def test_public_pages_use_the_hosted_rowset_social_card(client, route_name):
    response = client.get(reverse(route_name))

    assert response.status_code == 200
    content = response.content.decode()
    image_url = "https://rowset.example/static/vendors/images/rowset-social-card.png"
    assert content.count(f'property="og:image" content="{image_url}"') == 1
    assert content.count(f'name="twitter:image" content="{image_url}"') == 1
    assert '<meta property="og:image:width" content="1200" />' in content
    assert '<meta property="og:image:height" content="630" />' in content
    assert '<meta name="twitter:card" content="summary_large_image" />' in content
    assert "osig.app/g" not in content


def test_rowset_social_card_has_open_graph_dimensions():
    image_path = settings.BASE_DIR / "frontend/vendors/images/rowset-social-card.png"
    image_bytes = image_path.read_bytes()

    assert image_bytes[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", image_bytes[16:24])
    assert (width, height) == (1200, 630)


@override_settings(SITE_URL="https://testserver")
def test_robots_txt_allows_crawling_and_links_sitemap(client):
    response = client.get(reverse("robots_txt"), secure=True, HTTP_HOST="testserver")

    assert response.status_code == 200
    assert response.headers["Content-Type"] == "text/plain; charset=utf-8"
    assert response.content.decode() == (
        "User-agent: *\nAllow: /\nSitemap: https://testserver/sitemap.xml\n\n"
    )


def test_favicon_redirects_to_collected_static_asset(client):
    response = client.get("/favicon.ico")

    assert response.status_code == 301
    assert response["Location"].endswith("/static/vendors/images/favicon.ico")


def test_sitemap_response_does_not_set_noindex_header(client):
    response = client.get("/sitemap.xml", secure=True, HTTP_HOST="testserver")

    assert response.status_code == 200
    assert "X-Robots-Tag" not in response.headers


@pytest.mark.parametrize(
    "path",
    (
        "/pricing",
        "/changelog",
        "/privacy-policy",
        "/terms-of-service",
        "/uses",
        "/vs/airtable",
        "/vs/google-sheets",
    ),
)
def test_marketing_routes_are_extensionless(client, path):
    response = client.get(f"{path}?utm_source=test")

    assert response.status_code == 200
    assert client.get(f"{path}/").status_code == 404


def test_use_cases_page_links_public_use_case_pages(client):
    response = client.get(reverse("use_cases"))

    assert response.status_code == 200
    content = response.content.decode()
    main_content = content[content.index("<main") : content.index("</main>") + len("</main>")]
    assert reverse("use_case_page", kwargs={"slug": "personal-crm"}) in content
    assert reverse("use_case_page", kwargs={"slug": "agent-task-board"}) in content
    assert "product-inventory-catalog" in content
    assert reverse("pricing") not in main_content
    assert reverse("blog_post", kwargs={"slug": "airtable-alternatives"}) not in main_content


def test_authenticated_public_pages_use_app_shell(client):
    user = get_user_model().objects.create_user(
        username="public-header-auth",
        email="public-header-auth@example.com",
        password="strong-test-pass-123",
    )
    client.force_login(user)

    response = client.get(reverse("use_cases"))

    assert response.status_code == 200
    content = response.content.decode()
    assert 'data-app-shell="sidebar"' in content
    assert f'href="{reverse("home")}"' in content
    assert "Overview" in content
    assert "Docs" in content
    assert "Settings" in content
    assert "Search everything" in content
    assert content.count("data-command-palette-trigger") == 2
    assert content.count(f'action="{reverse("account_logout")}"') == 2
    assert "data-command-palette" in content


def test_superuser_public_pages_link_to_admin_in_desktop_and_mobile_nav(client):
    user = get_user_model().objects.create_superuser(
        username="public-header-admin",
        email="public-header-admin@example.com",
        password="strong-test-pass-123",
    )
    client.force_login(user)

    response = client.get(reverse("use_cases"))

    assert response.status_code == 200
    content = response.content.decode()
    assert content.count(f'href="{reverse("admin_panel")}"') == 2


def test_how_to_use_case_page_shows_structured_example(client):
    response = client.get(reverse("use_case_page", kwargs={"slug": "personal-crm"}))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Agent-managed personal CRM" in content
    assert "people" in content
    assert "People dataset indexed by email or person_id." in content
    assert "Dataset context and semantic schema" in content
    assert "alex@example.com" in content
    assert reverse("docs_page", kwargs={"slug": "connect-mcp"}) in content
    assert reverse("docs_page", kwargs={"slug": "dataset-api"}) in content
    assert '"@type": "Article"' in content


def test_authenticated_how_to_use_case_page_uses_app_shell(client):
    user = get_user_model().objects.create_user(
        username="use-case-detail-auth",
        email="use-case-detail-auth@example.com",
        password="strong-test-pass-123",
    )
    client.force_login(user)

    response = client.get(reverse("use_case_page", kwargs={"slug": "personal-crm"}))

    assert response.status_code == 200
    content = response.content.decode()
    assert 'data-app-shell="sidebar"' in content
    assert f'href="{reverse("home")}"' in content
    assert "Overview" in content
    assert "Settings" in content
    assert "Search everything" in content
    assert f'action="{reverse("account_logout")}"' in content


def test_unknown_use_case_returns_404(client):
    response = client.get(reverse("use_case_page", kwargs={"slug": "missing"}))

    assert response.status_code == 404


@override_settings(SITE_URL="https://testserver")
def test_database_mcp_server_explanation_has_required_links_and_schema(client):
    response = client.get(reverse("docs_page", kwargs={"slug": "database-mcp-server"}))

    assert response.status_code == 200
    content = response.content.decode()
    text = strip_tags(content)
    words = re.findall(r"\b[\w'-]+\b", text)

    assert "Database MCP server: when to use Rowset instead" in content
    assert len(words) >= 2500
    assert reverse("docs_page", kwargs={"slug": "connect-mcp"}) in content
    assert reverse("docs_page", kwargs={"slug": "dataset-api"}) in content
    assert reverse("docs_page", kwargs={"slug": "configure-agent-access"}) in content
    assert reverse("docs_home") in content
    assert reverse("pricing") in content
    assert reverse("use_case_page", kwargs={"slug": "personal-crm"}) in content
    assert reverse("use_case_page", kwargs={"slug": "agent-task-board"}) in content
    assert reverse("use_case_page", kwargs={"slug": "feedback-triage"}) in content
    assert "https://testserver/mcp/" in content
    assert '"@type": "Article"' in content
    assert '"@type": "BreadcrumbList"' in content
    schema = json.loads(_json_ld_payload(content))
    breadcrumb = next(item for item in schema if item["@type"] == "BreadcrumbList")
    assert breadcrumb["itemListElement"][1]["item"].endswith(
        reverse("docs_page", kwargs={"slug": "quickstart"})
    )


def test_authenticated_database_mcp_server_explanation_uses_app_shell(client):
    user = get_user_model().objects.create_user(
        username="database-mcp-explanation-auth",
        email="database-mcp-explanation-auth@example.com",
        password="strong-test-pass-123",
    )
    client.force_login(user)

    response = client.get(reverse("docs_page", kwargs={"slug": "database-mcp-server"}))

    assert response.status_code == 200
    content = response.content.decode()
    assert 'data-app-shell="sidebar"' in content
    assert f'href="{reverse("home")}"' in content
    assert "Overview" in content
    assert "Settings" in content
    assert "Search everything" in content
    assert f'action="{reverse("account_logout")}"' in content


@override_settings(SITE_URL="https://testserver")
def test_airtable_alternatives_blog_post_has_required_links_schema_and_content(client):
    response = client.get(reverse("blog_post", kwargs={"slug": "airtable-alternatives"}))

    assert response.status_code == 200
    content = response.content.decode()
    text = strip_tags(content)
    words = re.findall(r"\b[\w'-]+\b", text)
    schema = json.loads(_json_ld_payload(content))

    assert "Best Airtable alternatives for AI-agent-managed datasets" in content
    assert len(words) >= 1500
    assert "Why Airtable alternatives changed in 2026" in content
    assert "What an AI-agent dataset backend needs" in content
    assert "Airtable vs Rowset for AI agents" in content
    assert "Migration paths" in content
    assert "FAQ" in content
    assert "not a no-code app builder" in text
    assert reverse("pricing") in content
    assert reverse("docs_page", kwargs={"slug": "connect-mcp"}) in content
    assert reverse("docs_page", kwargs={"slug": "dataset-api"}) in content
    assert reverse("use_case_page", kwargs={"slug": "personal-crm"}) in content
    assert reverse("blog_post", kwargs={"slug": "choose-index-column-agent-rows"}) in content
    assert schema["@type"] == "BlogPosting"

    assert schema["url"] == "https://testserver/blog/airtable-alternatives"
    assert schema["headline"] == "Best Airtable alternatives for AI-agent-managed datasets"


def test_airtable_alternatives_blog_post_is_in_sitemap(client):
    response = client.get("/sitemap.xml", secure=True, HTTP_HOST="testserver")

    assert response.status_code == 200
    assert b"/blog/airtable-alternatives" in response.content
    assert b"/alternatives/airtable/" not in response.content


@override_settings(SITE_URL="https://testserver")
def test_rowset_vs_airtable_page_has_required_content_links_and_schema(client):
    response = client.get(reverse("comparison_page", kwargs={"slug": "airtable"}))

    assert response.status_code == 200
    content = response.content.decode()
    text = strip_tags(content)
    words = re.findall(r"\b[\w'-]+\b", text)
    schemas = json.loads(_json_ld_payload(content))

    assert len(words) >= 1200
    assert content.count("<h1") == 1
    assert "Rowset vs Airtable: Which Fits AI Agents? (2026)" in content
    assert "Rowset vs Airtable at a glance" in content
    assert "AI agents: Airtable Field Agents vs external agent handoff" in content
    assert "The practical migration path is usually a sidecar" in content
    assert "Frequently asked questions" in content
    assert "Airtable is the better operations app for people" in text
    assert "Rowset is not an Airtable synchronization product" in text
    assert reverse("pricing") in content
    assert reverse("docs_page", kwargs={"slug": "connect-mcp"}) in content
    assert reverse("docs_page", kwargs={"slug": "dataset-api"}) in content
    assert reverse("blog_post", kwargs={"slug": "airtable-alternatives"}) in content
    assert 'href="https://www.airtable.com/platform/ai-agents"' in content
    assert (
        'href="https://support.airtable.com/docs/managing-api-call-limits-in-airtable"' in content
    )
    assert [schema["@type"] for schema in schemas] == [
        "Article",
        "BreadcrumbList",
        "FAQPage",
    ]
    assert schemas[0]["url"] == "https://testserver/vs/airtable"
    assert schemas[0]["dateModified"] == "2026-07-15"
    assert len(schemas[2]["mainEntity"]) == 5


def test_rowset_vs_airtable_has_markdown_and_sitemap_entries(client):
    markdown_response = client.get(reverse("comparison_page_markdown", kwargs={"slug": "airtable"}))
    sitemap_response = client.get("/sitemap.xml", secure=True, HTTP_HOST="testserver")

    assert markdown_response.status_code == 200
    assert markdown_response.headers["Content-Type"] == "text/markdown; charset=utf-8"
    assert markdown_response.content.startswith(b"# Rowset vs Airtable")
    assert sitemap_response.status_code == 200
    assert b"/vs/airtable" in sitemap_response.content


@override_settings(SITE_URL="https://testserver")
def test_rowset_vs_google_sheets_page_has_required_content_links_and_schema(client):
    response = client.get(reverse("comparison_page", kwargs={"slug": "google-sheets"}))

    assert response.status_code == 200
    content = response.content.decode()
    text = strip_tags(content)
    source_words = re.findall(r"\b[\w'-]+\b", get_comparison_page("google-sheets").content)
    schemas = json.loads(_json_ld_payload(content))

    assert len(source_words) >= 1200
    assert content.count("<h1") == 1
    assert "Rowset vs Google Sheets for AI Agents (2026)" in content
    assert "Rowset vs Google Sheets at a glance" in content
    assert "AI in Sheets vs external agent handoff" in content
    assert "The safest migration keeps Sheets where people need it" in content
    assert "Frequently asked questions" in content
    assert "Google Sheets is a cloud spreadsheet for human collaboration" in text
    assert "Does Google Sheets support MCP?" in content
    assert "Rowset does not provide managed Google Sheets synchronization" in text
    assert reverse("pricing") in content
    assert reverse("docs_page", kwargs={"slug": "connect-mcp"}) in content
    assert reverse("docs_page", kwargs={"slug": "dataset-api"}) in content
    assert reverse("blog_post", kwargs={"slug": "google-sheets-alternatives"}) in content
    assert 'href="https://workspace.google.com/products/sheets/"' in content
    assert 'href="https://developers.google.com/workspace/sheets/api/limits"' in content
    assert [schema["@type"] for schema in schemas] == [
        "Article",
        "BreadcrumbList",
        "FAQPage",
    ]
    assert schemas[0]["url"] == "https://testserver/vs/google-sheets"
    assert schemas[0]["dateModified"] == "2026-07-15"
    assert len(schemas[2]["mainEntity"]) == 7


@override_settings(SITE_URL="https://rowset.example")
def test_rowset_vs_google_sheets_has_markdown_and_sitemap_entries(client):
    markdown_response = client.get(
        reverse("comparison_page_markdown", kwargs={"slug": "google-sheets"})
    )
    sitemap_response = client.get("/sitemap.xml", secure=True, HTTP_HOST="testserver")

    assert markdown_response.status_code == 200
    assert markdown_response.headers["Content-Type"] == "text/markdown; charset=utf-8"
    assert markdown_response.content.startswith(b"# Rowset vs Google Sheets")
    assert sitemap_response.status_code == 200
    assert b"/vs/google-sheets" in sitemap_response.content


def test_rowset_vs_google_sheets_has_inbound_links_and_review_record():
    alternatives = Path(
        settings.BASE_DIR, "apps/pages/content/blog/google-sheets-alternatives.md"
    ).read_text(encoding="utf-8")
    agent_datasets = Path(
        settings.BASE_DIR, "apps/pages/content/blog/agent-managed-datasets.md"
    ).read_text(encoding="utf-8")
    brief = Path(settings.BASE_DIR, ".seo/briefs/rowset-vs-google-sheets.md").read_text(
        encoding="utf-8"
    )

    assert "/vs/google-sheets" in alternatives
    assert "/vs/google-sheets" in agent_datasets
    assert "## AI SEO and product-led SEO review" in brief


def test_dataset_instructions_blog_post_has_required_links_schema_and_content(client):
    response = client.get(
        reverse("blog_post", kwargs={"slug": "structure-dataset-instructions-ai-agents"})
    )

    assert response.status_code == 200
    content = response.content.decode()
    text = strip_tags(content)
    words = re.findall(r"\b[\w'-]+\b", text)
    schema = json.loads(_json_ld_payload(content))

    assert "How to structure dataset instructions for AI agents" in content
    assert len(words) >= 1500
    assert "The short rule" in content
    assert "What belongs in metadata instead" in content
    assert "A reusable instruction template" in content
    assert "FAQ" in content
    assert "operating contract" in text
    assert reverse("docs_page", kwargs={"slug": "connect-mcp"}) in content
    assert reverse("docs_page", kwargs={"slug": "dataset-api"}) in content
    assert reverse("docs_page", kwargs={"slug": "design-schema"}) in content
    assert reverse("use_case_page", kwargs={"slug": "content-pipeline"}) in content
    assert reverse("blog_post", kwargs={"slug": "choose-index-column-agent-rows"}) in content
    assert schema["@type"] == "BlogPosting"
    assert schema["url"] == "https://rowset.lvtd.dev/blog/structure-dataset-instructions-ai-agents"
    assert schema["headline"] == "How to structure dataset instructions for AI agents"


def test_dataset_instructions_blog_post_is_in_sitemap(client):
    response = client.get("/sitemap.xml", secure=True, HTTP_HOST="testserver")

    assert response.status_code == 200
    assert b"/blog/structure-dataset-instructions-ai-agents" in response.content


def test_seo_sprint_tracks_airtable_phase_as_blog_post():
    roadmap = Path(settings.BASE_DIR) / "docs/seo-sprint.md"
    phase_label = "| 3 | Ship `/blog/airtable-alternatives`"
    row = next(line for line in roadmap.read_text().splitlines() if phase_label in line)

    assert "| completed | #207 |" in row


def test_seo_link_inventory_tracks_airtable_blog_post_links():
    inventory = Path(settings.BASE_DIR) / ".seo/link-inventory.md"
    row = next(
        line for line in inventory.read_text().splitlines() if "| `airtable` | Phase 3 |" in line
    )

    assert "| `/blog/airtable-alternatives` |" in row
    assert "landing page, agent-managed datasets blog, MCP vs REST blog" in row
    assert "pricing, MCP docs, Dataset API" in row


def test_schema_helpers_render_valid_homepage_json_ld(client):
    response = client.get(reverse("landing"))

    content = response.content.decode()
    schema = json.loads(_json_ld_payload(content))

    assert {entry["@type"] for entry in schema} == {"SoftwareApplication", "Organization"}
    software_application = next(
        entry for entry in schema if entry["@type"] == "SoftwareApplication"
    )
    organization = next(entry for entry in schema if entry["@type"] == "Organization")
    assert software_application["description"] == (
        "An open-source and self-hostable MCP and REST dataset backend for trusted AI agents."
    )
    assert organization["url"].endswith("/")


def test_json_ld_escapes_script_breakout_sequences():
    payload = json_ld({"name": "</script><script>alert(1)</script>", "ampersand": "&"})

    assert "</script>" not in payload
    assert "\\u003c/script\\u003e" in payload
    assert "\\u0026" in payload


def test_schema_helper_edge_cases_escape_and_omit_optional_fields():
    assert breadcrumb_list_schema(())["itemListElement"] == []
    assert faq_page_schema(())["mainEntity"] == []

    faq_schema = faq_page_schema((("Can agents use Rowset?", "Yes, through MCP or REST."),))
    assert faq_schema["mainEntity"][0]["acceptedAnswer"]["text"] == "Yes, through MCP or REST."

    schema = article_schema(
        headline='Agent "CRM" <guide>',
        description="Use <structured> rows safely.",
        path="/use-cases/personal-crm/",
    )
    rendered = json_ld(schema)

    assert "datePublished" not in schema
    assert "dateModified" not in schema
    assert "\\u003cguide\\u003e" in rendered
    assert "\\u003cstructured\\u003e" in rendered


def test_use_case_article_schema_includes_main_entity(client):
    response = client.get(reverse("use_case_page", kwargs={"slug": "personal-crm"}))

    content = response.content.decode()
    schema = json.loads(_json_ld_payload(content))

    assert schema["mainEntityOfPage"]["@id"].endswith("/use-cases/personal-crm")


@override_settings(SITE_URL="https://rowset.example")
def test_use_case_item_list_schema_uses_docs_urls(client):
    schema = use_case_item_list_schema(page_use_cases.get_use_case_pages())

    assert schema["@type"] == "ItemList"
    assert schema["url"] == "https://rowset.example/use-cases"
    assert schema["itemListElement"][0]["url"].startswith("https://rowset.example/use-cases/")


@override_settings(SITE_URL="https://rowset.example")
def test_pricing_schema_uses_configured_public_url(client):
    response = client.get(reverse("pricing"), secure=True, HTTP_HOST="testserver")

    assert response.status_code == 200
    schema = json.loads(_json_ld_payload(response.content.decode()))

    assert schema["@type"] == "Product"
    assert schema["description"] == (
        "An open-source and self-hostable MCP and REST dataset backend for trusted AI agents."
    )
    assert schema["url"] == "https://rowset.example/pricing"
    assert schema["image"] == (
        "https://rowset.example/static/vendors/images/rowset-social-card.png"
    )


def test_pricing_offers_full_product_seven_day_trial(client):
    response = client.get(reverse("pricing"))

    content = response.content.decode()
    assert "7-day trial" in content
    assert "Full product access" in content
    assert "2 private datasets" not in content
    assert "50 rows per dataset" not in content
    assert "outgrows the free limits" not in content

    schema = json.loads(_json_ld_payload(content))
    trial_offer = schema["offers"][0]
    assert trial_offer["name"] == "Rowset 7-day trial"
    assert trial_offer["priceSpecification"]["billingDuration"] == "P7D"


def test_landing_and_footer_offer_trial_instead_of_free_tier(client):
    response = client.get(reverse("landing"))

    content = response.content.decode()
    assert "Start your 7-day trial" in content
    assert "Start with two free datasets" not in content
    assert ">Start free<" not in content


def test_use_case_pages_reject_missing_page_copy(monkeypatch):
    page_copy = dict(page_use_cases.USE_CASE_PAGE_COPY)
    page_copy.pop("personal_crm")
    monkeypatch.setattr(page_use_cases, "USE_CASE_PAGE_COPY", page_copy)

    with pytest.raises(ValueError, match="personal_crm"):
        page_use_cases.validate_use_case_page_registry()


def test_use_case_pages_reject_unknown_feature_references(monkeypatch):
    invalid_use_case = RowsetUseCase(
        id="invalid_reference",
        title="Invalid reference",
        summary="Invalid registry fixture.",
        starter_shape=("Fixture only.",),
        rowset_features=("missing_capability",),
    )
    monkeypatch.setattr(
        page_use_cases,
        "ROWSET_USE_CASES",
        page_use_cases.ROWSET_USE_CASES + (invalid_use_case,),
    )
    monkeypatch.setattr(
        page_use_cases,
        "USE_CASE_PAGE_COPY",
        {
            **page_use_cases.USE_CASE_PAGE_COPY,
            "invalid_reference": replace(
                page_use_cases.USE_CASE_PAGE_COPY["personal_crm"],
                slug="invalid-reference",
            ),
        },
    )

    with pytest.raises(ValueError, match="invalid_reference: missing_capability"):
        page_use_cases.validate_use_case_page_registry()


def test_use_case_pages_reject_duplicate_capability_ids(monkeypatch):
    monkeypatch.setattr(
        page_use_cases,
        "ROWSET_CAPABILITIES",
        page_use_cases.ROWSET_CAPABILITIES + (page_use_cases.ROWSET_CAPABILITIES[0],),
    )

    with pytest.raises(ValueError, match="duplicate IDs"):
        page_use_cases.validate_use_case_page_registry()


def test_use_case_pages_reject_duplicate_public_slugs(monkeypatch):
    page_copy = dict(page_use_cases.USE_CASE_PAGE_COPY)
    page_copy["task_board"] = replace(
        page_copy["task_board"],
        slug=page_copy["personal_crm"].slug,
    )
    monkeypatch.setattr(page_use_cases, "USE_CASE_PAGE_COPY", page_copy)

    with pytest.raises(ValueError, match="duplicate public slugs: personal-crm"):
        page_use_cases.validate_use_case_page_registry()


@pytest.mark.parametrize(
    ("bad_slug", "expected_slug"),
    (
        (None, "<empty>"),
        ("", "<empty>"),
        ("personal crm", "personal crm"),
        ("personal/crm", "personal/crm"),
    ),
)
def test_use_case_pages_reject_unrouteable_public_slugs(bad_slug, expected_slug, monkeypatch):
    page_copy = dict(page_use_cases.USE_CASE_PAGE_COPY)
    page_copy["personal_crm"] = replace(
        page_copy["personal_crm"],
        slug=bad_slug,
    )
    monkeypatch.setattr(page_use_cases, "USE_CASE_PAGE_COPY", page_copy)

    errors = page_use_cases.get_use_case_page_registry_errors()

    assert (
        f"USE_CASE_PAGE_COPY contains invalid public slugs: personal_crm: {expected_slug}"
    ) in errors


@pytest.mark.parametrize("bad_page_copy", (None, {"slug": "personal-crm"}))
def test_use_case_pages_reject_malformed_page_copy_values(bad_page_copy, monkeypatch):
    page_copy = dict(page_use_cases.USE_CASE_PAGE_COPY)
    page_copy["personal_crm"] = bad_page_copy
    monkeypatch.setattr(page_use_cases, "USE_CASE_PAGE_COPY", page_copy)

    errors = page_use_cases.get_use_case_page_registry_errors()
    check_errors = check_use_case_page_registry(None)

    assert (
        "USE_CASE_PAGE_COPY contains invalid public slugs: personal_crm: <invalid page copy>"
    ) in errors
    assert check_errors[0].id == "pages.E001"
    assert "<invalid page copy>" in check_errors[0].msg
    with pytest.raises(ImproperlyConfigured, match="<invalid page copy>"):
        page_use_cases.get_use_case_pages()


def test_use_case_page_registry_check_reports_structured_errors(monkeypatch):
    page_copy = dict(page_use_cases.USE_CASE_PAGE_COPY)
    page_copy.pop("personal_crm")
    monkeypatch.setattr(page_use_cases, "USE_CASE_PAGE_COPY", page_copy)

    errors = check_use_case_page_registry(None)

    assert errors[0].id == "pages.E001"
    assert "personal_crm" in errors[0].msg


def test_use_case_pages_fail_controlled_when_registry_is_invalid(monkeypatch):
    page_copy = dict(page_use_cases.USE_CASE_PAGE_COPY)
    page_copy.pop("personal_crm")
    monkeypatch.setattr(page_use_cases, "USE_CASE_PAGE_COPY", page_copy)

    with pytest.raises(ImproperlyConfigured, match="personal_crm"):
        page_use_cases.get_use_case_pages()


def test_settings_shows_email_confirmation_and_passkey_setup(client):
    user = get_user_model().objects.create_user(
        username="settingsuser",
        email="settingsuser@example.com",
        password="strong-test-pass-123",
    )
    EmailAddress.objects.update_or_create(
        user=user,
        email=user.email,
        defaults={"primary": True, "verified": False},
    )
    client.force_login(user)

    response = client.get(reverse("settings"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Your email is not yet confirmed" in content
    assert "Add passkey" in content
    assert reverse("mfa_add_webauthn") in content


def test_settings_shows_passkey_manage_link_when_passkey_exists(client):
    user = get_user_model().objects.create_user(
        username="passkeyuser",
        email="passkeyuser@example.com",
        password="strong-test-pass-123",
    )
    EmailAddress.objects.update_or_create(
        user=user,
        email=user.email,
        defaults={"primary": True, "verified": True},
    )
    Authenticator.objects.create(
        user=user,
        type=Authenticator.Type.WEBAUTHN,
        data={"name": "Test passkey"},
    )
    client.force_login(user)

    response = client.get(reverse("settings"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "You have 1 passkey set up." in content
    assert "Manage passkeys" in content
    assert reverse("mfa_list_webauthn") in content


def test_mfa_index_uses_rowset_styling(client):
    user = get_user_model().objects.create_user(
        username="mfauser",
        email="mfauser@example.com",
        password="strong-test-pass-123",
    )
    EmailAddress.objects.update_or_create(
        user=user,
        email=user.email,
        defaults={"primary": True, "verified": True},
    )
    client.force_login(user)

    response = client.get(reverse("mfa_index"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Passkeys" in content
    assert "Add passkey" in content
    assert "Menu:" not in content
    assert "Rowset Logo" in content


def test_webauthn_add_page_loads_styled_form_and_scripts(client):
    user = get_user_model().objects.create_user(
        username="addpasskeyuser",
        email="addpasskeyuser@example.com",
        password="strong-test-pass-123",
    )
    EmailAddress.objects.update_or_create(
        user=user,
        email=user.email,
        defaults={"primary": True, "verified": True},
    )
    assert client.login(username="addpasskeyuser", password="strong-test-pass-123")
    session = client.session
    session["account_authentication_methods"] = [
        {"method": "password", "at": time.time(), "username": "addpasskeyuser"}
    ]
    session.save()

    response = client.get(reverse("mfa_add_webauthn"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Add passkey" in content
    assert 'id="mfa_webauthn_add"' in content
    assert "allauth.webauthn.forms.addForm" in content
    assert "mfa/js/webauthn.js" in content
    assert "Menu:" not in content


def test_reauthenticate_page_uses_rowset_styling(client):
    user = get_user_model().objects.create_user(
        username="reauthuser",
        email="reauthuser@example.com",
        password="strong-test-pass-123",
    )
    client.force_login(user)

    response = client.get(reverse("account_reauthenticate"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "<title>Confirm access · Rowset</title>" in content
    assert "Confirm access" in content
    assert "Rowset Logo" in content
    assert "Menu:" not in content


def test_mailgun_sender_defaults_to_rasul_lvtd():
    assert settings.DEFAULT_FROM_EMAIL == "Rasul Kireev <rasul@lvtd.dev>"
    assert settings.SERVER_EMAIL == "Rowset Errors <rasul@lvtd.dev>"
    assert settings.ANYMAIL["MAILGUN_SENDER_DOMAIN"] == "mg.lvtd.dev"


def test_account_email_page_uses_rowset_styling(client):
    user = get_user_model().objects.create_user(
        username="emailpageuser",
        email="emailpageuser@example.com",
        password="strong-test-pass-123",
    )
    EmailAddress.objects.update_or_create(
        user=user,
        email=user.email,
        defaults={"primary": True, "verified": False},
    )
    client.force_login(user)

    response = client.get(reverse("account_email"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Email addresses" in content
    assert "Re-send verification" in content
    assert "Rowset Logo" in content
    assert "Menu:" not in content


def test_settings_resend_confirmation_uses_hmac_link(client, monkeypatch):
    sent_confirmations = []

    def fake_send_confirmation_mail(self, request, emailconfirmation, signup):
        sent_confirmations.append((emailconfirmation, signup))

    monkeypatch.setattr(
        "rowset.adapters.CustomAccountAdapter.send_confirmation_mail",
        fake_send_confirmation_mail,
    )
    user = get_user_model().objects.create_user(
        username="resenduser",
        email="resenduser@example.com",
        password="strong-test-pass-123",
    )
    EmailAddress.objects.update_or_create(
        user=user,
        email=user.email,
        defaults={"primary": True, "verified": False},
    )
    client.force_login(user)

    response = client.post(reverse("resend_confirmation"))

    assert response.status_code == 302
    assert response["Location"] == reverse("settings")
    assert len(list(get_messages(response.wsgi_request))) == 1
    assert len(sent_confirmations) == 1
    emailconfirmation, signup = sent_confirmations[0]
    assert signup is False
    assert emailconfirmation.key.count(":") == 2
    assert not EmailAddress.objects.get(user=user, email=user.email).verified


def test_settings_resend_confirmation_link_confirms_email(client, monkeypatch):
    sent_confirmations = []

    def fake_send_confirmation_mail(self, request, emailconfirmation, signup):
        sent_confirmations.append(emailconfirmation)

    monkeypatch.setattr(
        "rowset.adapters.CustomAccountAdapter.send_confirmation_mail",
        fake_send_confirmation_mail,
    )
    user = get_user_model().objects.create_user(
        username="confirmresenduser",
        email="confirmresenduser@example.com",
        password="strong-test-pass-123",
    )
    EmailAddress.objects.update_or_create(
        user=user,
        email=user.email,
        defaults={"primary": True, "verified": False},
    )
    client.force_login(user)

    response = client.post(reverse("resend_confirmation"))

    assert response.status_code == 302
    assert len(sent_confirmations) == 1
    confirm_path = reverse("account_confirm_email", args=[sent_confirmations[0].key])
    confirm_response = client.post(confirm_path)

    assert confirm_response.status_code == 302
    assert EmailAddress.objects.get(user=user, email=user.email).verified is True


def test_dashboard_suppresses_verification_reminder_without_email_address(client):
    user = get_user_model().objects.create_user(
        username="admincreated",
        email="admincreated@example.com",
        password="strong-test-pass-123",
    )
    client.force_login(user)

    response = client.get(reverse("home"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Your email is not yet confirmed" not in content
    assert "Connect your AI agent to Rowset" in content
