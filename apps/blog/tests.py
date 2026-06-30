from django.test import TestCase
from django.urls import reverse

from apps.blog.choices import BlogPostStatus
from apps.blog.models import BlogPost
from rowset.sitemaps import sitemaps


class BlogPublicViewTests(TestCase):
    def test_blog_index_only_lists_published_posts(self):
        published = BlogPost.objects.create(
            title="Published guide",
            description="Ready for readers",
            slug="published-guide",
            tags="agents,mcp",
            content="Published body",
            status=BlogPostStatus.PUBLISHED,
        )
        BlogPost.objects.create(
            title="Draft guide",
            description="Not ready",
            slug="draft-guide",
            tags="agents,mcp",
            content="Draft body",
            status=BlogPostStatus.DRAFT,
        )

        response = self.client.get(reverse("blog_posts"))

        assert response.status_code == 200
        assert list(response.context["blog_posts"]) == [published]
        content = response.content.decode()
        assert "Published guide" in content
        assert "Draft guide" not in content

    def test_blog_detail_returns_404_for_draft_posts(self):
        BlogPost.objects.create(
            title="Draft guide",
            description="Not ready",
            slug="draft-guide",
            tags="agents,mcp",
            content="Draft body",
            status=BlogPostStatus.DRAFT,
        )

        response = self.client.get(reverse("blog_post", kwargs={"slug": "draft-guide"}))

        assert response.status_code == 404

    def test_blog_sitemap_only_includes_published_posts(self):
        published = BlogPost.objects.create(
            title="Published guide",
            description="Ready for readers",
            slug="published-guide",
            tags="agents,mcp",
            content="Published body",
            status=BlogPostStatus.PUBLISHED,
        )
        BlogPost.objects.create(
            title="Draft guide",
            description="Not ready",
            slug="draft-guide",
            tags="agents,mcp",
            content="Draft body",
            status=BlogPostStatus.DRAFT,
        )

        blog_sitemap = sitemaps["blog"]
        urls = [item["location"] for item in blog_sitemap.get_urls(site=None)]

        assert published.get_absolute_url() in urls
        assert "/blog/draft-guide" not in urls
