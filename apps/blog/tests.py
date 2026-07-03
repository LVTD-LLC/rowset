import json

import pytest
from django.core.checks import run_checks
from django.urls import reverse

from apps.blog.services import get_blog_post, list_blog_posts
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
    assert 'href="https://rowset.example/blog/"' in content


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
    assert 'property="article:published_time" content="2026-07-03T00:00:00"' in content
    assert (
        'property="og:image" content="https://rowset.example/static/blog/agent-managed-datasets.png"'
        in content
    )
    assert "Rowset dataset workflow" in content
    assert '"@type": "BlogPosting"' in content
    assert '"datePublished": "2026-07-03T00:00:00"' in content


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


def test_blog_post_404s_when_markdown_file_is_missing(client, blog_posts_dir):
    response = client.get(reverse("blog_post", kwargs={"slug": "missing-post"}))

    assert response.status_code == 404


def test_blog_frontmatter_check_reports_missing_seo_fields(blog_posts_dir):
    (blog_posts_dir / "missing-description.md").write_text(
        "---\ntitle: Missing description\npublished_at: 2026-07-03\n---\n\nBody.\n",
        encoding="utf-8",
    )

    errors = run_checks()

    assert len(errors) == 1
    assert errors[0].id == "blog.E001"
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
    assert sitemap.lastmod(post).isoformat() == "2026-07-04T00:00:00"


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
    from apps.blog.services import blog_post_schema, json_ld

    return json_ld(blog_post_schema(post))
