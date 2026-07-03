import pytest
from django.urls import reverse

from apps.blog import services as blog_services
from apps.blog.services import BlogPostSourceError, get_blog_post, get_blog_posts
from rowset.sitemaps import sitemaps


def write_markdown_post(directory, filename="agent-datasets.md", frontmatter="", content=""):
    path = directory / filename
    path.write_text(
        f"---\n{frontmatter}---\n{content}",
        encoding="utf-8",
    )
    return path


def published_frontmatter(slug="agent-managed-datasets", title="Agent-managed datasets"):
    return (
        f"title: {title}\n"
        "description: A practical note for AI agents.\n"
        f"slug: {slug}\n"
        "status: published\n"
        "published_at: 2026-06-01\n"
        "updated_at: 2026-06-02\n"
    )


def test_get_blog_posts_reads_published_markdown_files(tmp_path):
    write_markdown_post(
        tmp_path,
        frontmatter=published_frontmatter(),
        content="Agents need **stable** row APIs.\n",
    )

    posts = get_blog_posts(tmp_path)

    assert len(posts) == 1
    post = posts[0]
    assert post.title == "Agent-managed datasets"
    assert post.slug == "agent-managed-datasets"
    assert post.description == "A practical note for AI agents."
    assert post.content == "Agents need **stable** row APIs."
    assert post.get_absolute_url() == reverse("blog_post", kwargs={"slug": post.slug})
    assert post.published_at.isoformat() == "2026-06-01"
    assert post.updated_at.isoformat() == "2026-06-02"


def test_get_blog_posts_excludes_drafts_and_template_files(tmp_path):
    write_markdown_post(
        tmp_path,
        "published.md",
        frontmatter=published_frontmatter("published-post", "Published post"),
        content="Visible.\n",
    )
    write_markdown_post(
        tmp_path,
        "draft.md",
        frontmatter=published_frontmatter("draft-post", "Draft post").replace(
            "status: published", "status: draft"
        ),
        content="Hidden.\n",
    )
    write_markdown_post(
        tmp_path,
        "_template.md",
        frontmatter=published_frontmatter("template-post", "Template post"),
        content="Hidden template.\n",
    )

    assert [post.slug for post in get_blog_posts(tmp_path)] == ["published-post"]


def test_get_blog_post_rejects_missing_draft_and_duplicate_slugs(tmp_path):
    write_markdown_post(
        tmp_path,
        "published.md",
        frontmatter=published_frontmatter("published-post", "Published post"),
        content="Visible.\n",
    )
    write_markdown_post(
        tmp_path,
        "duplicate.md",
        frontmatter=published_frontmatter("published-post", "Duplicate post"),
        content="Duplicate.\n",
    )

    with pytest.raises(BlogPostSourceError, match="published-post"):
        get_blog_posts(tmp_path)

    (tmp_path / "duplicate.md").unlink()
    assert get_blog_post("published-post", tmp_path).title == "Published post"

    with pytest.raises(BlogPostSourceError, match="missing-post"):
        get_blog_post("missing-post", tmp_path)


def test_published_blog_posts_require_seo_frontmatter(tmp_path):
    write_markdown_post(
        tmp_path,
        "missing-description.md",
        frontmatter=published_frontmatter("missing-description", "Missing description").replace(
            "description: A practical note for AI agents.\n", ""
        ),
        content="Content.\n",
    )

    with pytest.raises(BlogPostSourceError, match="description"):
        get_blog_posts(tmp_path)

    (tmp_path / "missing-description.md").unlink()
    write_markdown_post(
        tmp_path,
        "missing-slug.md",
        frontmatter=published_frontmatter("missing-slug", "Missing slug").replace(
            "slug: missing-slug\n", ""
        ),
        content="Content.\n",
    )

    with pytest.raises(BlogPostSourceError, match="slug"):
        get_blog_posts(tmp_path)

    (tmp_path / "missing-slug.md").unlink()
    write_markdown_post(
        tmp_path,
        "missing-published-at.md",
        frontmatter=published_frontmatter("missing-published-at", "Missing publish date").replace(
            "published_at: 2026-06-01\n", ""
        ),
        content="Content.\n",
    )

    with pytest.raises(BlogPostSourceError, match="published_at"):
        get_blog_posts(tmp_path)


@pytest.mark.django_db
def test_blog_views_skip_invalid_markdown_files(client, tmp_path, monkeypatch):
    monkeypatch.setattr(blog_services, "BLOG_POST_CONTENT_DIR", tmp_path)
    write_markdown_post(
        tmp_path,
        "published.md",
        frontmatter=published_frontmatter("published-post", "Published post"),
        content="Published content.\n",
    )
    write_markdown_post(
        tmp_path,
        "missing-title.md",
        frontmatter=published_frontmatter("missing-title", "Missing title").replace(
            "title: Missing title\n", ""
        ),
        content="Bad file should not take the blog down.\n",
    )
    write_markdown_post(
        tmp_path,
        "z-duplicate.md",
        frontmatter=published_frontmatter("published-post", "Duplicate post"),
        content="Duplicate content.\n",
    )

    index_response = client.get(reverse("blog_posts"))
    detail_response = client.get(reverse("blog_post", kwargs={"slug": "published-post"}))

    assert index_response.status_code == 200
    index_content = index_response.content.decode()
    assert "Published post" in index_content
    assert "Duplicate post" not in index_content
    assert detail_response.status_code == 200
    assert "Published content" in detail_response.content.decode()


@pytest.mark.django_db
def test_blog_index_and_detail_render_from_markdown(client, tmp_path, monkeypatch):
    monkeypatch.setattr(blog_services, "BLOG_POST_CONTENT_DIR", tmp_path)
    write_markdown_post(
        tmp_path,
        "published.md",
        frontmatter=published_frontmatter("published-post", "Published post").replace(
            "updated_at: 2026-06-02\n", ""
        ),
        content="Published **content**.\n",
    )
    write_markdown_post(
        tmp_path,
        "draft.md",
        frontmatter=published_frontmatter("draft-post", "Draft post").replace(
            "status: published", "status: draft"
        ),
        content="Draft content.\n",
    )

    index_response = client.get(reverse("blog_posts"))

    assert index_response.status_code == 200
    index_content = index_response.content.decode()
    assert "Published post" in index_content
    assert "Draft post" not in index_content

    detail_response = client.get(reverse("blog_post", kwargs={"slug": "published-post"}))
    assert detail_response.status_code == 200
    detail_content = detail_response.content.decode()
    assert "Published post" in detail_content
    assert "<strong>content</strong>" in detail_content
    assert '"datePublished":"2026-06-01' in detail_content
    assert '"dateModified":"2026-06-01' in detail_content

    assert client.get(reverse("blog_post", kwargs={"slug": "draft-post"})).status_code == 404


def test_blog_sitemap_reads_published_markdown(monkeypatch, tmp_path):
    monkeypatch.setattr(blog_services, "BLOG_POST_CONTENT_DIR", tmp_path)
    write_markdown_post(
        tmp_path,
        "published.md",
        frontmatter=published_frontmatter("published-post", "Published post"),
        content="Visible.\n",
    )
    write_markdown_post(
        tmp_path,
        "missing-title.md",
        frontmatter=published_frontmatter("missing-title", "Missing title").replace(
            "title: Missing title\n", ""
        ),
        content="Invalid.\n",
    )
    write_markdown_post(
        tmp_path,
        "z-duplicate.md",
        frontmatter=published_frontmatter("published-post", "Duplicate post"),
        content="Duplicate.\n",
    )

    sitemap = sitemaps["blog"]()
    items = list(sitemap.items())

    assert [item.slug for item in items] == ["published-post"]
    assert sitemap.location(items[0]) == "/blog/published-post"
