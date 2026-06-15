import pytest
from django.test import override_settings
from django.urls import reverse


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
        assert "https://rowset.example/SKILL.md" in content
