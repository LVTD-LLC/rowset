import pytest
from django.test import override_settings
from django.urls import reverse

from apps.core.views import build_absolute_public_url, build_agent_setup_prompt


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

        assert "Connect your AI agent to FileBridge" in content
        assert "Copy agent prompt" in content
        assert "Connect Google Sheets" not in content
        assert "Upload dataset" not in content

    @override_settings(SITE_URL="https://filebridge.example")
    def test_home_view_includes_agent_setup_prompt(self, auth_client, profile):
        url = reverse("home")
        response = auth_client.get(url)

        masked_prompt = response.context["agent_setup_prompt_masked"]
        content = response.content.decode()
        assert "agent_setup_prompt" not in response.context
        assert "FileBridge API key: ***" in masked_prompt
        assert profile.key not in masked_prompt
        assert "FileBridge API key: ***" in content
        assert profile.key not in content
        assert reverse("agent_setup_prompt") in content
        assert "Only share this prompt with agents and people you trust." in content
        assert "create_dataset" in masked_prompt
        assert "update_dataset_public_preview" in masked_prompt
        assert response.context["mcp_url"] == "https://filebridge.example/mcp/"
        assert response.context["rest_api_base_url"] == "https://filebridge.example/api/"

    @override_settings(SITE_URL="https://filebridge.example")
    def test_agent_setup_prompt_endpoint_returns_full_prompt(self, auth_client, profile):
        response = auth_client.get(reverse("agent_setup_prompt"))

        assert response.status_code == 200
        assert response["Content-Type"] == "application/json"
        assert response["Cache-Control"] == "no-store"
        prompt = response.json()["prompt"]
        assert "FileBridge MCP URL: https://filebridge.example/mcp/" in prompt
        assert "FileBridge REST API base: https://filebridge.example/api/" in prompt
        assert f"FileBridge API key: {profile.key}" in prompt
        assert "FileBridge skill: https://filebridge.example/SKILL.md" in prompt
        assert "get_user_info" in prompt
        assert "create_dataset" in prompt
        assert "update_dataset_public_preview" in prompt
        assert "Discover the current MCP tools and API docs at runtime" in prompt

    @override_settings(SITE_URL="https://filebridge.example")
    def test_home_view_creates_missing_profile(self, auth_client, user):
        user.profile.delete()

        response = auth_client.get(reverse("home"))

        assert response.status_code == 200
        assert "FileBridge API key: ***" in response.context["agent_setup_prompt_masked"]
        assert "agent_setup_prompt" not in response.context
        assert user.__class__.objects.get(pk=user.pk).profile

    def test_agent_instructions_markdown_is_public_and_actionable(self, client):
        response = client.get(reverse("agent_instructions_filebridge_mcp"))

        assert response.status_code == 200
        assert response["Content-Type"] == "text/markdown; charset=utf-8"
        content = response.content.decode()
        assert "# FileBridge Agent Skill" in content
        assert "FileBridge turns user-owned tabular data into datasets" in content
        assert "Streamable HTTP" in content
        assert "get_user_info" in content
        assert "create_dataset" in content
        assert "update_dataset_public_preview" in content
        assert "Keep user data private" in content

    @override_settings(SITE_URL="http://filebridge.example")
    def test_build_agent_setup_prompt_uses_https_public_site_url(self, rf, user):
        request = rf.get("/home", HTTP_HOST="internal-proxy")
        request.user = user

        prompt = build_agent_setup_prompt(request)

        assert "FileBridge MCP URL: https://filebridge.example/mcp/" in prompt
        assert "FileBridge REST API base: https://filebridge.example/api/" in prompt
        assert "FileBridge skill: https://filebridge.example/SKILL.md" in prompt
        assert f"FileBridge API key: {user.profile.key}" in prompt
        assert "API key only when your client needs bearer-token auth" in prompt
        assert "update_dataset_public_preview" in prompt

        masked_prompt = build_agent_setup_prompt(request, mask_api_key=True)
        assert "FileBridge API key: ***" in masked_prompt
        assert user.profile.key not in masked_prompt

    @override_settings(SITE_URL="https://filebridge.example")
    def test_build_agent_setup_prompt_creates_missing_profile(self, rf, user):
        user.profile.delete()
        fresh_user = user.__class__.objects.get(pk=user.pk)
        request = rf.get("/home", HTTP_HOST="internal-proxy")
        request.user = fresh_user

        prompt = build_agent_setup_prompt(request)

        assert f"FileBridge API key: {fresh_user.profile.key}" in prompt
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
