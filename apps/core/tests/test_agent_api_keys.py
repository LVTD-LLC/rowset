from datetime import timedelta

import pytest
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.core.models import AgentApiKey
from apps.core.services import (
    create_agent_api_key,
    generate_agent_api_key_token,
    get_agent_api_key_token,
    hash_agent_api_key,
    resolve_api_key_profile,
)

pytestmark = pytest.mark.django_db


def test_create_agent_api_key_stores_hash_and_returns_raw_key(profile):
    credential = create_agent_api_key(profile, " Codex ")

    agent_api_key = credential.agent_api_key
    assert credential.raw_key.startswith("rsk_")
    assert agent_api_key.name == "Codex"
    assert generate_agent_api_key_token(agent_api_key) == credential.raw_key
    assert agent_api_key.key_prefix == credential.raw_key[:12]
    assert agent_api_key.token_hash == hash_agent_api_key(credential.raw_key)
    assert credential.raw_key not in agent_api_key.token_hash


def test_resolve_api_key_profile_accepts_named_key_and_records_last_used(profile):
    credential = create_agent_api_key(profile, "Codex")

    resolved_profile, agent_api_key = resolve_api_key_profile(credential.raw_key)

    assert resolved_profile == profile
    assert agent_api_key == credential.agent_api_key
    credential.agent_api_key.refresh_from_db()
    assert credential.agent_api_key.last_used_at is not None


def test_resolve_api_key_profile_throttles_recent_last_used_updates(profile):
    credential = create_agent_api_key(profile, "Codex")
    recent_last_used_at = timezone.now()
    credential.agent_api_key.last_used_at = recent_last_used_at
    credential.agent_api_key.save(update_fields=["last_used_at", "updated_at"])

    resolved_profile, agent_api_key = resolve_api_key_profile(credential.raw_key)

    assert resolved_profile == profile
    assert agent_api_key == credential.agent_api_key
    credential.agent_api_key.refresh_from_db()
    assert credential.agent_api_key.last_used_at == recent_last_used_at


def test_resolve_api_key_profile_refreshes_stale_last_used_and_updated_at(profile):
    credential = create_agent_api_key(profile, "Codex")
    stale_last_used_at = timezone.now() - timedelta(minutes=10)
    AgentApiKey.objects.filter(pk=credential.agent_api_key.pk).update(
        last_used_at=stale_last_used_at,
        updated_at=stale_last_used_at,
    )

    resolved_profile, agent_api_key = resolve_api_key_profile(credential.raw_key)

    assert resolved_profile == profile
    assert agent_api_key == credential.agent_api_key
    credential.agent_api_key.refresh_from_db()
    assert credential.agent_api_key.last_used_at > stale_last_used_at
    assert credential.agent_api_key.updated_at == credential.agent_api_key.last_used_at


def test_resolve_api_key_profile_keeps_legacy_profile_key(profile):
    resolved_profile, agent_api_key = resolve_api_key_profile(profile.key)

    assert resolved_profile == profile
    assert agent_api_key is None


def test_settings_create_agent_api_key_keeps_raw_key_out_of_html(auth_client):
    response = auth_client.post(
        reverse("create_agent_api_key"),
        {"name": "Codex"},
        follow=True,
    )

    assert response.status_code == 200
    created_key = response.context["created_agent_api_key"]
    assert created_key["name"] == "Codex"

    agent_api_key = AgentApiKey.objects.get(name="Codex")
    raw_key = get_agent_api_key_token(agent_api_key)
    assert agent_api_key.token_hash == hash_agent_api_key(raw_key)
    content = response.content.decode()
    assert raw_key not in content
    assert "Created Codex." in content
    assert "Copy Setup Prompt" in content
    assert reverse("agent_api_key_setup_prompt", args=[agent_api_key.uuid]) in content

    followup = auth_client.get(reverse("settings"))
    assert followup.context["created_agent_api_key"] is None
    assert raw_key not in followup.content.decode()


def test_settings_lists_agent_api_keys_without_raw_secret(auth_client, profile):
    credential = create_agent_api_key(profile, "Reporting Agent")

    response = auth_client.get(reverse("settings"))
    content = response.content.decode()

    assert "Reporting Agent" in content
    assert f"{credential.agent_api_key.key_prefix}..." in content
    assert "Copy Setup Prompt" in content
    assert reverse("agent_api_key_setup_prompt", args=[credential.agent_api_key.uuid]) in content
    assert credential.raw_key not in content


@override_settings(SITE_URL="https://rowset.example")
def test_agent_api_key_setup_prompt_endpoint_returns_selected_key_prompt(auth_client, profile):
    credential = create_agent_api_key(profile, "Reporting Agent")

    response = auth_client.get(
        reverse("agent_api_key_setup_prompt", args=[credential.agent_api_key.uuid])
    )

    assert response.status_code == 200
    assert response["Content-Type"] == "application/json"
    assert response["Cache-Control"] == "no-store"
    prompt = response.json()["prompt"]
    assert "Rowset MCP URL: https://rowset.example/mcp/" in prompt
    assert "Rowset REST API base: https://rowset.example/api/" in prompt
    assert f"Rowset API key: {credential.raw_key}" in prompt
    assert f"Rowset API key: {profile.key}" not in prompt
    assert "Rowset skill: https://rowset.example/SKILL.md" in prompt


def test_agent_api_key_setup_prompt_endpoint_rejects_revoked_key(auth_client, profile):
    credential = create_agent_api_key(profile, "Reporting Agent")
    credential.agent_api_key.revoked_at = timezone.now()
    credential.agent_api_key.save(update_fields=["revoked_at", "updated_at"])

    response = auth_client.get(
        reverse("agent_api_key_setup_prompt", args=[credential.agent_api_key.uuid])
    )

    assert response.status_code == 404


def test_settings_rejects_duplicate_agent_api_key_names(auth_client, profile):
    create_agent_api_key(profile, "Codex")

    response = auth_client.post(
        reverse("create_agent_api_key"),
        {"name": "Codex"},
        follow=True,
    )

    assert response.status_code == 200
    assert AgentApiKey.objects.filter(profile=profile, name="Codex").count() == 1
    assert "already exists" in response.content.decode()


def test_settings_owner_can_revoke_agent_api_key(auth_client, profile):
    credential = create_agent_api_key(profile, "Codex")

    response = auth_client.post(
        reverse("revoke_agent_api_key", args=[credential.agent_api_key.uuid]),
    )

    assert response.status_code == 302
    credential.agent_api_key.refresh_from_db()
    assert credential.agent_api_key.revoked_at is not None
    assert resolve_api_key_profile(credential.raw_key) is None


def test_settings_owner_cannot_revoke_another_profile_agent_api_key(
    auth_client,
    django_user_model,
):
    other_user = django_user_model.objects.create_user(
        username="otheragentkeyuser",
        email="otheragentkeyuser@example.com",
        password="password123",
    )
    credential = create_agent_api_key(other_user.profile, "Codex")

    response = auth_client.post(
        reverse("revoke_agent_api_key", args=[credential.agent_api_key.uuid]),
    )

    assert response.status_code == 404
    credential.agent_api_key.refresh_from_db()
    assert credential.agent_api_key.revoked_at is None
