from pathlib import Path

import pytest
from django.conf import settings
from django.http import Http404
from django.test import override_settings
from django.urls import reverse

from apps.docs.views import (
    CATEGORY_LABELS,
    DOCS_HOME_COMMON_PATHS,
    DOCS_HOME_RESOURCE_LINKS,
    DOCS_HOME_SECTION_CARDS,
    DOCS_SIDEBAR_EXPLORE_LINKS,
    DOCS_SIDEBAR_START_LINKS,
    LEGACY_DOCS_CATEGORY_REDIRECTS,
    LEGACY_DOCS_REDIRECTS,
    build_configured_link,
    build_docs_sidebar_links,
    docs_page_view,
    get_docs_navigation,
    load_navigation_config,
)
from rowset.sitemaps import DocsSitemap, StaticViewSitemap

EXPECTED_LEGACY_DOCS_REDIRECTS = {
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


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user(
        username="docsuser",
        email="docsuser@example.com",
        password="password123",
    )


@pytest.fixture
def auth_client(client, user):
    client.force_login(user)
    return client


@pytest.fixture
def profile(user):
    return user.profile


@pytest.mark.django_db
class TestDocsView:
    def test_docs_home_is_public_diataxis_landing_page(self, client):
        response = client.get(reverse("docs_home"))

        assert response.status_code == 200
        content = response.content.decode()
        assert "Find the right Rowset guide" in content
        assert "Tutorials" in content
        assert "How-to guides" in content
        assert "Reference" in content
        assert "Explanation" in content
        assert (
            reverse("docs_page", kwargs={"category": "tutorials", "page": "get-started"}) in content
        )
        assert (
            reverse("docs_page", kwargs={"category": "how-to-guides", "page": "connect-mcp"})
            in content
        )
        assert (
            reverse("docs_page", kwargs={"category": "reference", "page": "dataset-api"}) in content
        )
        assert (
            reverse(
                "docs_page",
                kwargs={"category": "explanation", "page": "concepts-and-decisions"},
            )
            in content
        )
        assert (
            reverse(
                "docs_page",
                kwargs={"category": "how-to-guides", "page": "work-with-datasets"},
            )
            in content
        )
        assert reverse("use_cases") in content
        assert "/playbooks/database-mcp-server" in content
        assert reverse("blog_posts") in content
        assert reverse("blog_post", kwargs={"slug": "agent-managed-datasets"}) in content
        assert reverse("blog_post", kwargs={"slug": "mcp-vs-rest-ai-agents"}) in content

    def test_docs_home_renders_all_configured_discovery_links(self, client):
        response = client.get(reverse("docs_home"))

        assert response.status_code == 200
        assert response.context["docs_sidebar_start_links"]
        assert response.context["docs_sidebar_explore_links"]
        content = response.content.decode()
        navigation = get_docs_navigation()
        configured_links = (
            *DOCS_HOME_SECTION_CARDS,
            *DOCS_HOME_COMMON_PATHS,
            *DOCS_HOME_RESOURCE_LINKS,
        )

        for link_config in configured_links:
            link = build_configured_link(link_config, navigation)
            assert link is not None
            assert link["url"] in content
            assert link["title"] in content

    def test_legacy_redirect_map_covers_pre_diataxis_public_paths(self):
        assert LEGACY_DOCS_REDIRECTS == EXPECTED_LEGACY_DOCS_REDIRECTS

    def test_legacy_redirect_targets_exist_on_filesystem(self):
        content_dir = Path(settings.BASE_DIR) / "apps" / "docs" / "content"

        for category, page in set(LEGACY_DOCS_REDIRECTS.values()):
            assert (content_dir / category / f"{page}.md").is_file()

    def test_navigation_config_categories_have_explicit_labels(self):
        assert set(load_navigation_config()) == set(CATEGORY_LABELS)

    @pytest.mark.parametrize("legacy_category", sorted(LEGACY_DOCS_CATEGORY_REDIRECTS))
    def test_legacy_category_urls_redirect_to_docs_home(self, client, legacy_category):
        response = client.get(f"/docs/{legacy_category}/")

        assert response.status_code == 301
        assert response["Location"] == reverse("docs_home")

    @pytest.mark.parametrize(
        ("legacy_path", "target_path"),
        sorted(EXPECTED_LEGACY_DOCS_REDIRECTS.items()),
    )
    def test_legacy_docs_urls_redirect_to_diataxis_paths(
        self,
        client,
        legacy_path,
        target_path,
    ):
        response = client.get(
            reverse(
                "docs_page",
                kwargs={"category": legacy_path[0], "page": legacy_path[1]},
            )
        )

        assert response.status_code == 301
        assert response["Location"] == reverse(
            "docs_page",
            kwargs={"category": target_path[0], "page": target_path[1]},
        )

    def test_sitemap_uses_diataxis_docs_urls(self):
        docs_sitemap = DocsSitemap()
        docs_locations = {docs_sitemap.location(item) for item in docs_sitemap.items()}
        static_sitemap = StaticViewSitemap()
        static_locations = {static_sitemap.location(item) for item in static_sitemap.items()}

        assert reverse("docs_home") in static_locations
        assert reverse("docs_page", kwargs={"category": "tutorials", "page": "get-started"}) in (
            docs_locations
        )
        assert (
            reverse("docs_page", kwargs={"category": "how-to-guides", "page": "connect-mcp"})
            in docs_locations
        )
        assert (
            reverse("docs_page", kwargs={"category": "reference", "page": "rest-api"})
            in docs_locations
        )
        assert (
            reverse(
                "docs_page",
                kwargs={"category": "explanation", "page": "concepts-and-decisions"},
            )
            in docs_locations
        )
        assert "/docs/features/mcp/" not in docs_locations
        assert "/docs/api-reference/datasets/" not in docs_locations
        assert "/docs/getting-started/introduction/" not in docs_locations

    def test_docs_navigation_excludes_draft_pages(self, tmp_path):
        docs_dir = tmp_path / "apps" / "docs"
        content_dir = docs_dir / "content" / "tutorials"
        content_dir.mkdir(parents=True)
        (docs_dir / "navigation.yaml").write_text(
            "navigation:\n  tutorials:\n    - published\n    - draft\n",
            encoding="utf-8",
        )
        (content_dir / "published.md").write_text(
            "---\ntitle: Published\n---\n# Published\n",
            encoding="utf-8",
        )
        (content_dir / "draft.md").write_text(
            "---\ntitle: Draft\ndraft: true\n---\n# Draft\n",
            encoding="utf-8",
        )

        with override_settings(BASE_DIR=tmp_path):
            navigation = get_docs_navigation()

        assert [page["slug"] for page in navigation[0]["pages"]] == ["published"]

    def test_missing_configured_docs_links_are_omitted(self):
        missing_link = build_configured_link(
            {"title": "Missing", "category": "tutorials", "page": "missing"},
            get_docs_navigation(),
        )

        assert missing_link is None

    def test_docs_navigation_uses_diataxis_sections(self, client):
        response = client.get(
            reverse("docs_page", kwargs={"category": "how-to-guides", "page": "connect-mcp"})
        )

        assert response.status_code == 200
        content = response.content.decode()
        assert "Tutorials" in content
        assert "How-to guides" in content
        assert "Reference" in content
        assert "Explanation" in content
        assert "Features" not in content
        assert "API Reference" not in content

    def test_docs_page_sidebar_links_are_resolvable(self, client):
        response = client.get(
            reverse("docs_page", kwargs={"category": "how-to-guides", "page": "connect-mcp"})
        )

        assert response.status_code == 200
        content = response.content.decode()

        for link_config in (*DOCS_SIDEBAR_START_LINKS, *DOCS_SIDEBAR_EXPLORE_LINKS):
            link = build_configured_link(link_config)
            assert link["url"] in content
            assert link["title"] in content

    def test_sidebar_link_builder_accepts_navigation_context(self):
        sidebar_links = build_docs_sidebar_links(get_docs_navigation())

        assert sidebar_links["docs_sidebar_start_links"]
        assert sidebar_links["docs_sidebar_explore_links"]

    @override_settings(SITE_URL="https://rowset.example")
    def test_docs_page_is_public_and_uses_safe_placeholders(self, client):
        response = client.get(
            reverse("docs_page", kwargs={"category": "reference", "page": "user-api"})
        )

        assert response.status_code == 200
        content = response.content.decode()
        assert "Authorization: Bearer YOUR_ROWSET_API_KEY" in content
        assert "you@example.com" in content
        assert "Sign in" in content
        assert "Create account" in content

    def test_docs_page_rejects_path_traversal(self, rf):
        request = rf.get("/docs/../AGENTS/")

        with pytest.raises(Http404):
            docs_page_view(request, "..", "AGENTS")

    @override_settings(SITE_URL="https://rowset.example")
    def test_anonymous_agent_access_docs_use_masked_prompt(self, client, profile):
        response = client.get(
            reverse(
                "docs_page",
                kwargs={"category": "how-to-guides", "page": "configure-agent-access"},
            )
        )

        assert response.status_code == 200
        content = response.content.decode()
        assert "Rowset API key: ***" in content
        assert profile.key not in content
        assert "Sign in" in content
        assert "Create account" in content

    @override_settings(SITE_URL="http://rowset.example")
    def test_docs_use_https_public_urls(self, auth_client):
        response = auth_client.get(
            reverse("docs_page", kwargs={"category": "reference", "page": "rest-api"})
        )

        assert response.status_code == 200
        content = response.content.decode()
        assert "https://rowset.example/api" in content
        assert "https://rowset.example/api/docs" in content
        assert "http://rowset.example" not in content

    @override_settings(SITE_URL="https://rowset.example")
    def test_authenticated_docs_do_not_render_real_api_key(self, auth_client, profile):
        response = auth_client.get(
            reverse("docs_page", kwargs={"category": "reference", "page": "rest-api"})
        )

        assert response.status_code == 200
        content = response.content.decode()
        assert "Authorization: Bearer YOUR_ROWSET_API_KEY" in content
        assert profile.key not in content

    @override_settings(SITE_URL="https://rowset.example")
    def test_agent_access_docs_include_dashboard_prompt(self, auth_client, profile):
        response = auth_client.get(
            reverse(
                "docs_page",
                kwargs={"category": "how-to-guides", "page": "configure-agent-access"},
            )
        )

        assert response.status_code == 200
        content = response.content.decode()
        assert "Set up Rowset for this user." in content
        assert "Rowset API key: ***" in content
        assert f"Rowset API key: {profile.key}" not in content
        assert "treat the copied prompt like a password" in content
        assert "ROWSET_API_KEY" in content
        assert "https://rowset.example/SKILL.md" in content
        assert "https://rowset.example/skills/rowset-features/SKILL.md" in content
        assert "https://rowset.example/skills/rowset-use-cases/SKILL.md" in content
        assert "https://rowset.example/llms.txt" in content
        assert "npx skills add LVTD-LLC/rowset" in content
        assert (
            "https://raw.githubusercontent.com/LVTD-LLC/rowset/main/.agents/skills/rowset/SKILL.md"
        ) in content
        assert "rowset-features" in content
        assert "rowset-use-cases" in content
        assert "get_rowset_capabilities" in content

    @override_settings(SITE_URL="https://rowset.example")
    def test_mcp_docs_use_bearer_api_key_instead_of_oauth(self, client):
        response = client.get(
            reverse("docs_page", kwargs={"category": "how-to-guides", "page": "connect-mcp"})
        )

        assert response.status_code == 200
        content = response.content.decode()
        assert "Authorization: Bearer YOUR_ROWSET_API_KEY" in content
        assert "ROWSET_API_KEY" in content
        assert "get_rowset_capabilities" in content
        assert "https://rowset.example/llms.txt" in content
        assert "Direct database MCP servers" in content
        assert "/use-cases/personal-crm" in content
        assert "OAuth" not in content

    @override_settings(SITE_URL="https://rowset.example")
    def test_dataset_api_docs_explain_agent_dataset_api_positioning(self, client):
        response = client.get(
            reverse("docs_page", kwargs={"category": "reference", "page": "dataset-api"})
        )

        assert response.status_code == 200
        content = response.content.decode()
        assert "dataset API" in content
        assert "/docs/how-to-guides/connect-mcp/" in content
        assert "real business key" in content

    @override_settings(SITE_URL="https://rowset.example")
    def test_agent_discovery_docs_include_runtime_discovery_surfaces(self, client):
        response = client.get(
            reverse(
                "docs_page",
                kwargs={"category": "how-to-guides", "page": "help-agents-discover-rowset"},
            )
        )

        assert response.status_code == 200
        content = response.content.decode()
        assert "get_rowset_capabilities" in content
        assert "https://rowset.example/llms.txt" in content
        assert "https://rowset.example/skills/rowset-features/SKILL.md" in content
        assert "rowset-use-cases" in content
