from io import StringIO

import pytest
from django.core.management import call_command
from django.urls import reverse

from apps.blog.choices import BlogPostStatus
from apps.blog.models import BlogPost
from apps.blog.services import BlogPostSourceError, sync_blog_posts_from_markdown
from rowset.sitemaps import sitemaps

pytestmark = pytest.mark.django_db


def write_markdown_post(directory, filename="agent-datasets.md", frontmatter="", content=""):
    path = directory / filename
    path.write_text(
        f"---\n{frontmatter}---\n{content}",
        encoding="utf-8",
    )
    return path


def test_sync_blog_posts_creates_post_from_markdown_file(tmp_path):
    write_markdown_post(
        tmp_path,
        frontmatter=(
            "title: Agent-managed datasets\n"
            "description: A practical note for AI agents.\n"
            "slug: agent-managed-datasets\n"
            "tags:\n"
            "  - agents\n"
            "  - datasets\n"
            "status: published\n"
        ),
        content="Agents need **stable** row APIs.\n",
    )

    result = sync_blog_posts_from_markdown(tmp_path)

    assert result.created == 1
    assert result.updated == 0

    post = BlogPost.objects.get(slug="agent-managed-datasets")
    assert post.title == "Agent-managed datasets"
    assert post.description == "A practical note for AI agents."
    assert post.tags == "agents, datasets"
    assert post.status == BlogPostStatus.PUBLISHED
    assert post.content == "Agents need **stable** row APIs."


def test_sync_blog_posts_updates_existing_post_by_slug(tmp_path):
    post = BlogPost.objects.create(
        title="Old title",
        description="Old description",
        slug="agent-managed-datasets",
        tags="old",
        content="Old content",
        status=BlogPostStatus.DRAFT,
    )
    write_markdown_post(
        tmp_path,
        frontmatter=(
            "title: New title\n"
            "description: New description.\n"
            "slug: agent-managed-datasets\n"
            "tags: agents, datasets\n"
            "status: published\n"
        ),
        content="New content.\n",
    )

    result = sync_blog_posts_from_markdown(tmp_path)

    assert result.created == 0
    assert result.updated == 1
    post.refresh_from_db()
    assert post.title == "New title"
    assert post.description == "New description."
    assert post.tags == "agents, datasets"
    assert post.content == "New content."
    assert post.status == BlogPostStatus.PUBLISHED


def test_sync_blog_posts_does_not_update_unchanged_post(tmp_path):
    write_markdown_post(
        tmp_path,
        frontmatter=(
            "title: Agent-managed datasets\n"
            "description: A practical note for AI agents.\n"
            "slug: agent-managed-datasets\n"
            "tags: agents, datasets\n"
            "status: published\n"
        ),
        content="Agents need stable row APIs.\n",
    )

    first_result = sync_blog_posts_from_markdown(tmp_path)
    second_result = sync_blog_posts_from_markdown(tmp_path)

    assert first_result.created == 1
    assert second_result.created == 0
    assert second_result.updated == 0


def test_sync_blog_posts_requires_title_and_content(tmp_path):
    write_markdown_post(
        tmp_path,
        frontmatter=(
            "description: Missing title should fail.\n"
            "slug: missing-title\n"
            "tags: agents\n"
            "status: published\n"
        ),
        content="Body.\n",
    )

    with pytest.raises(BlogPostSourceError, match="title"):
        sync_blog_posts_from_markdown(tmp_path)


def test_sync_blog_posts_rejects_duplicate_source_slugs(tmp_path):
    frontmatter = (
        "title: Duplicate post\n"
        "description: Duplicate slugs should fail.\n"
        "slug: duplicate-post\n"
        "tags: agents\n"
        "status: published\n"
    )
    write_markdown_post(tmp_path, "first.md", frontmatter=frontmatter, content="First post.\n")
    write_markdown_post(tmp_path, "second.md", frontmatter=frontmatter, content="Second post.\n")

    with pytest.raises(BlogPostSourceError, match="duplicate-post"):
        sync_blog_posts_from_markdown(tmp_path)


def test_sync_blog_posts_command_uses_content_dir(tmp_path):
    write_markdown_post(
        tmp_path,
        frontmatter=(
            "title: Deployment publishing\n"
            "description: Deployments sync Markdown posts.\n"
            "slug: deployment-publishing\n"
            "tags: deployment\n"
            "status: published\n"
        ),
        content="Deployment loads this post.\n",
    )
    stdout = StringIO()

    call_command("sync_blog_posts", "--content-dir", str(tmp_path), stdout=stdout)

    assert BlogPost.objects.filter(slug="deployment-publishing").exists()
    assert "created 1" in stdout.getvalue()


def test_blog_index_and_detail_only_expose_published_posts(client):
    published = BlogPost.objects.create(
        title="Published post",
        description="Visible.",
        slug="published-post",
        tags="agents",
        content="Published content.",
        status=BlogPostStatus.PUBLISHED,
    )
    draft = BlogPost.objects.create(
        title="Draft post",
        description="Hidden.",
        slug="draft-post",
        tags="agents",
        content="Draft content.",
        status=BlogPostStatus.DRAFT,
    )

    response = client.get(reverse("blog_posts"))

    assert response.status_code == 200
    content = response.content.decode()
    assert published.title in content
    assert draft.title not in content

    assert client.get(published.get_absolute_url()).status_code == 200
    assert client.get(draft.get_absolute_url()).status_code == 404


def test_blog_sitemap_only_includes_published_posts():
    published = BlogPost.objects.create(
        title="Published post",
        description="Visible.",
        slug="published-post",
        tags="agents",
        content="Published content.",
        status=BlogPostStatus.PUBLISHED,
    )
    BlogPost.objects.create(
        title="Draft post",
        description="Hidden.",
        slug="draft-post",
        tags="agents",
        content="Draft content.",
        status=BlogPostStatus.DRAFT,
    )

    assert list(sitemaps["blog"].items()) == [published]
