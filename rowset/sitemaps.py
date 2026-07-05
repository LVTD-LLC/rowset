from types import MappingProxyType

from django.contrib import sitemaps
from django.urls import reverse

from apps.blog.services import list_blog_posts
from apps.docs.views import get_docs_navigation
from apps.pages.use_cases import get_use_case_pages

STATIC_SITEMAP_PRIORITY_OVERRIDES = MappingProxyType(
    {
        "airtable_alternative": 0.7,
    }
)
STATIC_SITEMAP_CHANGEFREQ_OVERRIDES = MappingProxyType(
    {
        "airtable_alternative": "monthly",
    }
)


class StaticViewSitemap(sitemaps.Sitemap):
    """Generate Sitemap for the site"""

    _default_priority = 0.9
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
            "use_cases",
            "database_mcp_server_playbook",
            "airtable_alternative",
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

    def priority(self, item):
        return STATIC_SITEMAP_PRIORITY_OVERRIDES.get(item, self._default_priority)

    def changefreq(self, item):
        return STATIC_SITEMAP_CHANGEFREQ_OVERRIDES.get(item)


class UseCaseSitemap(sitemaps.Sitemap):
    """Generate sitemap entries for marketing use-case pages."""

    priority = 0.85
    protocol = "https"
    changefreq = "monthly"

    def items(self):
        return get_use_case_pages()

    def location(self, item):
        return reverse("use_case_detail", kwargs={"slug": item["slug"]})


class DocsSitemap(sitemaps.Sitemap):
    """Generate Sitemap for documentation pages"""

    priority = 0.8
    protocol = "https"
    changefreq = "weekly"

    def items(self):
        """Get all documentation pages from the navigation structure

        Returns:
            List: List of dicts with category and page slugs for each doc page
        """
        doc_pages = []
        navigation = get_docs_navigation()

        for category_info in navigation:
            category_slug = category_info["category_slug"]
            for page_info in category_info["pages"]:
                page_slug = page_info["slug"]
                doc_pages.append(
                    {
                        "category": category_slug,
                        "page": page_slug,
                    }
                )

        return doc_pages

    def location(self, item):
        """Get location for each doc page in the Sitemap

        Args:
            item (dict): Dictionary with category and page slugs

        Returns:
            str: URL for the sitemap item
        """
        return f"/docs/{item['category']}/{item['page']}/"


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
    "use_cases": UseCaseSitemap,
    "blog": BlogSitemap,
    "docs": DocsSitemap,
}
