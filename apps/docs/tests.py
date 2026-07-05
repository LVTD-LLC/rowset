import pytest
from django.http import Http404
from django.test import override_settings
from django.urls import reverse

from apps.docs.views import docs_page_view


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
    def test_docs_home_is_public(self, client):
        response = client.get(reverse("docs_home"))

        assert response.status_code == 302
        assert response["Location"] == reverse(
            "docs_page",
            kwargs={"category": "getting-started", "page": "introduction"},
        )

    @override_settings(SITE_URL="https://rowset.example")
    def test_docs_page_is_public_and_uses_safe_placeholders(self, client):
        response = client.get(
            reverse("docs_page", kwargs={"category": "api-reference", "page": "user"})
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
            reverse("docs_page", kwargs={"category": "features", "page": "agent-access"})
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
            reverse("docs_page", kwargs={"category": "api-reference", "page": "introduction"})
        )

        assert response.status_code == 200
        content = response.content.decode()
        assert "https://rowset.example/api" in content
        assert "https://rowset.example/api/docs" in content
        assert "http://rowset.example" not in content

    @override_settings(SITE_URL="https://rowset.example")
    def test_authenticated_docs_do_not_render_real_api_key(self, auth_client, profile):
        response = auth_client.get(
            reverse("docs_page", kwargs={"category": "api-reference", "page": "introduction"})
        )

        assert response.status_code == 200
        content = response.content.decode()
        assert "Authorization: Bearer YOUR_ROWSET_API_KEY" in content
        assert profile.key not in content

    @override_settings(SITE_URL="https://rowset.example")
    def test_agent_access_docs_include_dashboard_prompt(self, auth_client, profile):
        response = auth_client.get(
            reverse("docs_page", kwargs={"category": "features", "page": "agent-access"})
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
        response = client.get(reverse("docs_page", kwargs={"category": "features", "page": "mcp"}))

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
            reverse("docs_page", kwargs={"category": "api-reference", "page": "datasets"})
        )

        assert response.status_code == 200
        content = response.content.decode()
        assert "generic &quot;dataset API&quot; options" in content
        assert "/docs/features/mcp/" in content
        assert "stable index values" in content

    @override_settings(SITE_URL="https://rowset.example")
    def test_agent_discovery_docs_include_runtime_discovery_surfaces(self, client):
        response = client.get(
            reverse("docs_page", kwargs={"category": "features", "page": "agent-discovery"})
        )

        assert response.status_code == 200
        content = response.content.decode()
        assert "get_rowset_capabilities" in content
        assert "https://rowset.example/llms.txt" in content
        assert "https://rowset.example/skills/rowset-features/SKILL.md" in content
        assert "rowset-use-cases" in content
