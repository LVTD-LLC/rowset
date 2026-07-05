from django.contrib import sitemaps
from django.urls import reverse

from apps.blog.services import list_blog_posts
from apps.pages.content import CONTENT_SECTIONS, get_content_section
from apps.pages.use_cases import get_use_case_pages


class StaticViewSitemap(sitemaps.Sitemap):
    """Generate Sitemap for the site"""

    priority = 0.9
    protocol = "https"

    def items(self):
        """Identify items that will be in the Sitemap

        Returns:
            List: urlNames that will be in the Sitemap
        """
        return [
            "landing",
            "uses",
            "pricing",
            "docs_home",
            "tutorials_home",
            "how_to_guides",
            "explanations_home",
            "airtable_alternatives",
            "blog_posts",
        ]

    def location(self, item):
        """Get location for each item in the Sitemap

        Args:
            item (str): Item from the items function

        Returns:
            str: Url for the sitemap item
        """
        return reverse(item)


class UseCaseSitemap(sitemaps.Sitemap):
    """Generate sitemap entries for marketing use-case pages."""

    priority = 0.85
    protocol = "https"
    changefreq = "monthly"

    def items(self):
        return get_use_case_pages()

    def location(self, item):
        return reverse("how_to_guide", kwargs={"slug": item["slug"]})


class ContentSitemap(sitemaps.Sitemap):
    """Generate sitemap entries for checked-in pages content."""

    priority = 0.8
    protocol = "https"
    changefreq = "weekly"

    def items(self):
        pages = []
        for section_slug in CONTENT_SECTIONS:
            section = get_content_section(section_slug)
            pages.extend(page["url"] for page in section["pages"])
        pages.append(reverse("explanation_page", kwargs={"slug": "database-mcp-server"}))
        return pages

    def location(self, item):
        return item


class BlogSitemap(sitemaps.Sitemap):
    """Generate sitemap entries for checked-in Markdown blog posts."""

    priority = 0.85
    protocol = "https"
    changefreq = "monthly"

    def items(self):
        return list_blog_posts()

    def location(self, item):
        return item.get_absolute_url()

    def lastmod(self, item):
        return item.updated_at


sitemaps = {
    "static": StaticViewSitemap,
    "how_to_use_cases": UseCaseSitemap,
    "blog": BlogSitemap,
    "content": ContentSitemap,
}
