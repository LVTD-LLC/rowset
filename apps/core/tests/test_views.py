import pytest
from django.urls import reverse

from apps.core.views import build_agent_setup_prompt


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

    def test_home_view_includes_agent_setup_prompt(self, auth_client, profile):
        url = reverse("home")
        response = auth_client.get(url)

        prompt = response.context["agent_setup_prompt"]
        assert "FileBridge MCP URL: http://testserver/mcp/" in prompt
        assert "FileBridge REST API base: http://testserver/api/" in prompt
        assert f"FileBridge API key: {profile.key}" in prompt
        assert "Agent instructions/skill: http://testserver/agent/filebridge-mcp.md" in prompt
        assert "get_user_info" in prompt

    def test_agent_instructions_markdown_is_public_and_actionable(self, client):
        response = client.get(reverse("agent_instructions_filebridge_mcp"))

        assert response.status_code == 200
        assert response["Content-Type"] == "text/markdown; charset=utf-8"
        content = response.content.decode()
        assert "# FileBridge MCP Agent Skill" in content
        assert "Streamable HTTP" in content
        assert "get_user_info" in content
        assert "do not print it" in content

    def test_build_agent_setup_prompt_uses_current_site_and_profile_key(self, rf, user):
        request = rf.get("/home", HTTP_HOST="testserver")
        request.user = user

        prompt = build_agent_setup_prompt(request)

        assert "FileBridge MCP URL: http://testserver/mcp/" in prompt
        assert "FileBridge REST API base: http://testserver/api/" in prompt
        assert f"FileBridge API key: {user.profile.key}" in prompt