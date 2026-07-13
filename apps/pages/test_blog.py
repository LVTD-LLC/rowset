import json
import re
from html import unescape
from urllib.parse import parse_qs, urlparse

import pytest
from django.contrib.auth import get_user_model
from django.core.checks import run_checks
from django.urls import reverse
from django.utils.html import strip_tags

from apps.pages.blog import get_blog_post, list_blog_posts
from rowset.sitemaps import BlogSitemap

pytestmark = pytest.mark.django_db


@pytest.fixture
def blog_posts_dir(tmp_path, settings):
    settings.BLOG_POSTS_DIR = tmp_path
    settings.SITE_URL = "https://rowset.example"
    return tmp_path


def write_post(blog_posts_dir, slug, frontmatter, body):
    fields = "\n".join(f"{key}: {value}" for key, value in frontmatter.items())
    path = blog_posts_dir / f"{slug}.md"
    path.write_text(f"---\n{fields}\n---\n\n{body}\n", encoding="utf-8")
    return path


def test_blog_index_renders_empty_state(client, blog_posts_dir):
    response = client.get(reverse("blog_posts"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "No blog posts are available yet." in content
    assert 'href="https://rowset.example/blog"' in content


def test_ai_reader_menu_is_absent_from_blog_index(client, blog_posts_dir):
    response = client.get(reverse("blog_posts"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Read with Claude" not in content
    assert "Read with ChatGPT" not in content
    assert "Copy Prompt for your AI Agent" not in content
    assert "Copy Markdown" not in content


def test_ai_reader_menu_renders_for_blog_post(client, blog_posts_dir):
    write_post(
        blog_posts_dir,
        "agent-managed-datasets",
        {
            "title": "Agent-managed datasets",
            "description": "How AI agents keep Rowset datasets current.",
            "published_at": "2026-07-03",
        },
        "Agents need stable APIs for rows.",
    )
    response = client.get(reverse("blog_post", kwargs={"slug": "agent-managed-datasets"}))

    assert response.status_code == 200
    content = response.content.decode()
    markdown_url = "https://rowset.example/blog/agent-managed-datasets.md"
    prompt = f"Read this Rowset page and help me understand or use it: {markdown_url}"
    action_labels = (
        "Read with Claude",
        "Read with ChatGPT",
        "Copy Prompt for your AI Agent",
        "Copy Markdown",
    )
    for label in action_labels:
        assert content.count(label) == 1
    assert [content.index(label) for label in action_labels] == sorted(
        content.index(label) for label in action_labels
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
    for provider_url, attributes in provider_links:
        assert 'target="_blank"' in attributes
        assert 'rel="noopener"' in attributes
        decoded_query = parse_qs(urlparse(unescape(provider_url)).query)
        assert decoded_query["q"] == [prompt]


def test_authenticated_blog_pages_use_app_shell(client, blog_posts_dir):
    write_post(
        blog_posts_dir,
        "agent-managed-datasets",
        {
            "title": "Agent-managed datasets",
            "description": "How AI agents keep Rowset datasets current.",
            "published_at": "2026-07-03",
        },
        "Agents need stable APIs for rows.",
    )
    user = get_user_model().objects.create_user(
        username="blog-header-auth",
        email="blog-header-auth@example.com",
        password="strong-test-pass-123",
    )
    client.force_login(user)

    urls = [
        reverse("blog_posts"),
        reverse("blog_post", kwargs={"slug": "agent-managed-datasets"}),
    ]
    for url in urls:
        response = client.get(url)

        assert response.status_code == 200
        content = response.content.decode()
        assert 'data-app-shell="sidebar"' in content
        assert f'href="{reverse("home")}"' in content
        assert "Overview" in content
        assert "Docs" in content
        assert "Settings" in content
        assert "Search everything" in content
        assert f'action="{reverse("account_logout")}"' in content
        assert "data-command-palette" in content


def test_blog_post_renders_markdown_and_frontmatter_metadata(client, blog_posts_dir):
    write_post(
        blog_posts_dir,
        "agent-managed-datasets",
        {
            "title": "Agent-managed datasets",
            "description": "How AI agents keep Rowset datasets current.",
            "published_at": "2026-07-03",
            "updated_at": "2026-07-04",
            "author": "Rasul Kireev",
            "keywords": "[Rowset, MCP]",
            "topics": "[agent workflows, datasets]",
            "image": "/static/blog/agent-managed-datasets.png",
            "image_alt": "Rowset dataset workflow",
        },
        "## Why agents need it\n\nAgents need **stable APIs** for rows.",
    )

    response = client.get(reverse("blog_post", kwargs={"slug": "agent-managed-datasets"}))

    assert response.status_code == 200
    content = response.content.decode()
    assert "<title>Agent-managed datasets · Rowset Blog</title>" in content
    assert (
        '<meta name="description" content="How AI agents keep Rowset datasets current." />'
        in content
    )
    assert (
        '<link rel="canonical" href="https://rowset.example/blog/agent-managed-datasets" />'
        in content
    )
    assert "<h2>Why agents need it</h2>" in content
    assert "<strong>stable APIs</strong>" in content
    assert re.search(
        r'<meta\s+property="article:published_time"\s+content="2026-07-03T00:00:00\+00:00"\s*/>',
        content,
    )
    assert (
        'property="og:image" content="https://rowset.example/static/blog/agent-managed-datasets.png"'
        in content
    )
    assert "Rowset dataset workflow" in content
    assert '"@type": "BlogPosting"' in content
    assert '"datePublished": "2026-07-03T00:00:00+00:00"' in content


def test_blog_post_markdown_is_self_describing_and_has_no_frontmatter(client, blog_posts_dir):
    write_post(
        blog_posts_dir,
        "agent-managed-datasets",
        {
            "title": "Agent-managed datasets",
            "description": "How AI agents keep Rowset datasets current.",
            "published_at": "2026-07-03",
        },
        "## Why agents need it\n\nAgents need **stable APIs** for rows.",
    )

    response = client.get(reverse("blog_post_markdown", kwargs={"slug": "agent-managed-datasets"}))

    assert response.status_code == 200
    assert response.headers["Content-Type"] == "text/markdown; charset=utf-8"
    assert response.content.decode() == (
        "# Agent-managed datasets\n\n"
        "How AI agents keep Rowset datasets current.\n\n"
        "## Why agents need it\n\n"
        "Agents need **stable APIs** for rows.\n"
    )


@pytest.mark.parametrize("slug", ("missing-post", "not_valid"))
def test_blog_post_markdown_404s_for_missing_or_invalid_slugs(client, blog_posts_dir, slug):
    assert client.get(f"/blog/{slug}.md").status_code == 404


def test_blog_post_header_and_body_share_the_same_content_width(client, blog_posts_dir):
    write_post(
        blog_posts_dir,
        "aligned-post",
        {
            "title": "An aligned blog post",
            "description": "The article header and body begin on the same vertical line.",
            "published_at": "2026-07-03",
        },
        "The article body.",
    )

    response = client.get(reverse("blog_post", kwargs={"slug": "aligned-post"}))

    assert response.status_code == 200
    content = response.content.decode()
    assert content.count('class="mx-auto max-w-3xl px-4') == 2


def test_blog_posts_are_sorted_by_publication_date(blog_posts_dir):
    write_post(
        blog_posts_dir,
        "older-post",
        {
            "title": "Older post",
            "description": "Older description.",
            "published_at": "2026-07-01",
        },
        "Older body.",
    )
    write_post(
        blog_posts_dir,
        "newer-post",
        {
            "title": "Newer post",
            "description": "Newer description.",
            "published_at": "2026-07-03",
        },
        "Newer body.",
    )

    assert [post.slug for post in list_blog_posts()] == ["newer-post", "older-post"]


def test_blog_index_skips_invalid_markdown_files(client, blog_posts_dir):
    write_post(
        blog_posts_dir,
        "valid-post",
        {
            "title": "Valid post",
            "description": "Valid description.",
            "published_at": "2026-07-03",
        },
        "Valid body.",
    )
    (blog_posts_dir / "invalid-post.md").write_text(
        "---\ntitle: Missing description\npublished_at: 2026-07-03\n---\n\nInvalid body.\n",
        encoding="utf-8",
    )

    response = client.get(reverse("blog_posts"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Valid post" in content
    assert "Invalid body" not in content


def test_blog_post_404s_when_markdown_file_is_missing(client, blog_posts_dir):
    response = client.get(reverse("blog_post", kwargs={"slug": "missing-post"}))

    assert response.status_code == 404


def test_blog_post_404s_when_frontmatter_is_invalid(client, blog_posts_dir):
    (blog_posts_dir / "invalid-post.md").write_text(
        "---\n"
        "title: Invalid post\n"
        "description: Invalid description.\n"
        "published_at: not-a-date\n"
        "---\n\n"
        "Body.\n",
        encoding="utf-8",
    )

    response = client.get(reverse("blog_post", kwargs={"slug": "invalid-post"}))

    assert response.status_code == 404


def test_blog_frontmatter_check_reports_missing_seo_fields(blog_posts_dir):
    (blog_posts_dir / "missing-description.md").write_text(
        "---\ntitle: Missing description\npublished_at: 2026-07-03\n---\n\nBody.\n",
        encoding="utf-8",
    )

    errors = run_checks()

    assert len(errors) == 1
    assert errors[0].id == "pages.E002"
    assert "missing required frontmatter: description" in errors[0].msg


def test_blog_sitemap_uses_markdown_posts(blog_posts_dir):
    write_post(
        blog_posts_dir,
        "sitemap-post",
        {
            "title": "Sitemap post",
            "description": "Sitemap description.",
            "published_at": "2026-07-03",
            "updated_at": "2026-07-04",
        },
        "Sitemap body.",
    )

    sitemap = BlogSitemap()
    post = sitemap.items()[0]

    assert sitemap.location(post) == "/blog/sitemap-post"
    assert sitemap.lastmod(post).isoformat() == "2026-07-04T00:00:00+00:00"


def test_blog_post_schema_uses_checked_in_markdown_content(blog_posts_dir):
    write_post(
        blog_posts_dir,
        "schema-post",
        {
            "title": "Schema post",
            "description": "Schema description.",
            "published_at": "2026-07-03",
        },
        "The article body comes from markdown.",
    )

    post = get_blog_post("schema-post")
    schema = json.loads(post_schema_json(post))

    assert schema["headline"] == "Schema post"
    assert schema["url"] == "https://rowset.example/blog/schema-post"
    assert schema["articleBody"] == "The article body comes from markdown."


def post_schema_json(post):
    from apps.pages.blog import blog_post_schema, json_ld

    return json_ld(blog_post_schema(post))
