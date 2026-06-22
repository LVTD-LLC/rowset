import pytest
from allauth.account.models import EmailAddress
from django.test import override_settings
from django.urls import reverse

from apps.core.views import build_agent_setup_prompt
from apps.datasets.choices import DatasetStatus
from apps.datasets.models import Dataset
from filebridge.utils import build_absolute_public_url


@pytest.mark.django_db
class TestHomeView:
    def test_home_view_status_code(self, auth_client):
        url = reverse("home")
        response = auth_client.get(url)
        assert response.status_code == 200

    def test_home_view_uses_correct_template(self, auth_client):
        url = reverse("home")
        response = auth_client.get(url)
        assert "pages/home.html" in [t.name for t in response.templates]

    def test_home_view_leads_with_agent_setup(self, auth_client):
        response = auth_client.get(reverse("home"))
        content = response.content.decode()

        assert "Connect your AI agent to Rowset" in content
        assert "Copy agent prompt" in content
        assert "Connect Google Sheets" not in content
        assert "Upload dataset" not in content

    @override_settings(SITE_URL="https://rowset.example")
    def test_home_view_includes_agent_setup_prompt(self, auth_client, profile):
        url = reverse("home")
        response = auth_client.get(url)

        masked_prompt = response.context["agent_setup_prompt_masked"]
        content = response.content.decode()
        assert "agent_setup_prompt" not in response.context
        assert response.context["show_agent_setup_prompt"] is True
        assert "Rowset API key: ***" in masked_prompt
        assert profile.key not in masked_prompt
        assert "Rowset API key: ***" in content
        assert profile.key not in content
        assert reverse("agent_setup_prompt") in content
        assert reverse("dismiss_agent_setup_prompt") in content
        assert "Remove from dashboard" in content
        assert "Only share this prompt with agents and people you trust." in content
        assert "create_dataset" in masked_prompt
        assert "update_dataset_public_preview" in masked_prompt
        assert response.context["mcp_url"] == "https://rowset.example/mcp/"
        assert response.context["rest_api_base_url"] == "https://rowset.example/api/"

    def test_home_view_hides_agent_setup_prompt_after_dismissal(self, auth_client, profile):
        profile.agent_setup_prompt_dismissed = True
        profile.save(update_fields=["agent_setup_prompt_dismissed"])

        response = auth_client.get(reverse("home"))

        content = response.content.decode()
        assert response.context["show_agent_setup_prompt"] is False
        assert "Connect your AI agent to Rowset" not in content
        assert "Copy/paste prompt" not in content
        assert "Copy agent prompt" not in content
        assert "Rowset API key: ***" not in content
        assert "Rowset control surface" in content

    def test_home_view_hides_agent_setup_prompt_after_dataset_exists(self, auth_client, profile):
        Dataset.objects.create(
            profile=profile,
            name="People",
            original_filename="people.csv",
            status=DatasetStatus.READY,
            headers=["name"],
            row_count=0,
        )

        response = auth_client.get(reverse("home"))

        content = response.content.decode()
        assert response.context["show_agent_setup_prompt"] is False
        assert "Copy/paste prompt" not in content
        assert "Copy agent prompt" not in content
        assert "People" in content

    def test_dismiss_agent_setup_prompt_removes_prompt_from_home(self, auth_client, profile):
        response = auth_client.post(reverse("dismiss_agent_setup_prompt"))

        assert response.status_code == 302
        assert response["Location"] == reverse("home")
        profile.refresh_from_db()
        assert profile.agent_setup_prompt_dismissed is True

    @override_settings(SITE_URL="https://rowset.example")
    def test_agent_setup_prompt_endpoint_returns_full_prompt(self, auth_client, profile):
        response = auth_client.get(reverse("agent_setup_prompt"))

        assert response.status_code == 200
        assert response["Content-Type"] == "application/json"
        assert response["Cache-Control"] == "no-store"
        prompt = response.json()["prompt"]
        assert "Rowset MCP URL: https://rowset.example/mcp/" in prompt
        assert "Rowset REST API base: https://rowset.example/api/" in prompt
        assert f"Rowset API key: {profile.key}" in prompt
        assert "Rowset skill: https://rowset.example/SKILL.md" in prompt
        assert "get_user_info" in prompt
        assert "create_dataset" in prompt
        assert "update_dataset_public_preview" in prompt
        assert "Discover the current MCP tools and API docs at runtime" in prompt

    @override_settings(SITE_URL="https://rowset.example")
    def test_home_view_creates_missing_profile(self, auth_client, user):
        user.profile.delete()

        response = auth_client.get(reverse("home"))

        assert response.status_code == 200
        assert "Rowset API key: ***" in response.context["agent_setup_prompt_masked"]
        assert "agent_setup_prompt" not in response.context
        assert user.__class__.objects.get(pk=user.pk).profile

    @override_settings(SITE_URL="https://rowset.example")
    def test_settings_view_keeps_agent_setup_prompt_after_dismissal(self, auth_client, profile):
        EmailAddress.objects.create(user=profile.user, email=profile.user.email, verified=True)
        profile.agent_setup_prompt_dismissed = True
        profile.save(update_fields=["agent_setup_prompt_dismissed"])

        response = auth_client.get(reverse("settings"))

        content = response.content.decode()
        assert response.status_code == 200
        assert "Agent setup prompt" in content
        assert "Copy/paste prompt" in content
        assert "Copy agent prompt" in content
        assert "Remove from dashboard" not in content
        assert "Rowset API key: ***" in content
        assert f"Rowset API key: {profile.key}" not in content
        assert reverse("agent_setup_prompt") in content

    def test_agent_instructions_markdown_is_public_and_actionable(self, client):
        response = client.get(reverse("agent_instructions_rowset_mcp"))

        assert response.status_code == 200
        assert response["Content-Type"] == "text/markdown; charset=utf-8"
        content = response.content.decode()
        assert "# Rowset Agent Skill" in content
        assert "Rowset turns user-owned tabular data into datasets" in content
        assert "Streamable HTTP" in content
        assert "get_user_info" in content
        assert "create_dataset" in content
        assert "update_dataset_public_preview" in content
        assert "Keep user data private" in content

    @override_settings(SITE_URL="http://rowset.example")
    def test_build_agent_setup_prompt_uses_https_public_site_url(self, rf, user):
        request = rf.get("/home", HTTP_HOST="internal-proxy")
        request.user = user

        prompt = build_agent_setup_prompt(request)

        assert "Rowset MCP URL: https://rowset.example/mcp/" in prompt
        assert "Rowset REST API base: https://rowset.example/api/" in prompt
        assert "Rowset skill: https://rowset.example/SKILL.md" in prompt
        assert f"Rowset API key: {user.profile.key}" in prompt
        assert "Configure the MCP client bearer-token env var to ROWSET_API_KEY" in prompt
        assert "update_dataset_public_preview" in prompt

        masked_prompt = build_agent_setup_prompt(request, mask_api_key=True)
        assert "Rowset API key: ***" in masked_prompt
        assert user.profile.key not in masked_prompt

    @override_settings(SITE_URL="https://rowset.example")
    def test_build_agent_setup_prompt_creates_missing_profile(self, rf, user):
        user.profile.delete()
        fresh_user = user.__class__.objects.get(pk=user.pk)
        request = rf.get("/home", HTTP_HOST="internal-proxy")
        request.user = fresh_user

        prompt = build_agent_setup_prompt(request)

        assert f"Rowset API key: {fresh_user.profile.key}" in prompt
        assert fresh_user.profile

    @override_settings(SITE_URL="http://localhost:8000")
    def test_build_absolute_public_url_keeps_localhost_http(self):
        assert build_absolute_public_url("/SKILL.md") == "http://localhost:8000/SKILL.md"

    @override_settings(SITE_URL="http://127.0.0.1:8000")
    def test_build_absolute_public_url_keeps_loopback_http(self):
        assert build_absolute_public_url("/SKILL.md") == "http://127.0.0.1:8000/SKILL.md"

    @override_settings(SITE_URL="http://notlocalhost.example")
    def test_build_absolute_public_url_does_not_substring_match_localhost(self):
        assert build_absolute_public_url("/SKILL.md") == "https://notlocalhost.example/SKILL.md"
