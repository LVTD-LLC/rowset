from datetime import timedelta

import pytest
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.core.analytics import ROWSET_AGENT_API_KEY_CREATED
from apps.core.choices import AgentApiKeyAccessLevel
from apps.core.models import AgentApiKey
from apps.core.services import (
    agent_api_key_allows,
    create_agent_api_key,
    get_agent_api_key_token,
    hash_agent_api_key,
    normalize_agent_api_key_access_level,
    require_agent_api_key_access,
    resolve_api_key_profile,
)

pytestmark = pytest.mark.django_db


def test_create_agent_api_key_stores_hash_and_returns_raw_key(profile):
    credential = create_agent_api_key(profile, " Codex ")

    agent_api_key = credential.agent_api_key
    assert credential.raw_key.startswith("rsk_")
    assert agent_api_key.name == "Codex"
    assert agent_api_key.access_level == AgentApiKeyAccessLevel.READ_WRITE
    assert agent_api_key.key_prefix == credential.raw_key[:12]
    assert agent_api_key.token_hash == hash_agent_api_key(credential.raw_key)
    assert agent_api_key.token_ciphertext
    assert credential.raw_key not in agent_api_key.token_hash
    assert credential.raw_key not in agent_api_key.token_ciphertext
    assert get_agent_api_key_token(agent_api_key) == credential.raw_key


def test_create_agent_api_key_tracks_activation_without_raw_key(profile, monkeypatch):
    calls = []

    def track_activation_event(profile, event_name, properties, source_function=None):
        calls.append((profile.id, event_name, properties, source_function))

    monkeypatch.setattr("apps.core.services.track_activation_event", track_activation_event)

    credential = create_agent_api_key(profile, "Codex", AgentApiKeyAccessLevel.READ)

    assert calls == [
        (
            profile.id,
            ROWSET_AGENT_API_KEY_CREATED,
            {
                "created_agent_api_key_id": credential.agent_api_key.id,
                "created_agent_api_key_access_level": AgentApiKeyAccessLevel.READ,
            },
            "create_agent_api_key",
        )
    ]
    assert credential.raw_key not in str(calls)


def test_create_agent_api_key_stores_selected_access_level(profile):
    credential = create_agent_api_key(profile, "Admin Agent", AgentApiKeyAccessLevel.ADMIN)

    assert credential.agent_api_key.access_level == AgentApiKeyAccessLevel.ADMIN
    assert credential.agent_api_key.can_read is True
    assert credential.agent_api_key.can_write is True
    assert credential.agent_api_key.can_admin is True


def test_agent_api_key_access_level_helpers(profile):
    read_key = create_agent_api_key(profile, "Read Agent", "read").agent_api_key
    write_key = create_agent_api_key(profile, "Write Agent", "read + write").agent_api_key

    assert normalize_agent_api_key_access_level("") == AgentApiKeyAccessLevel.READ_WRITE
    assert agent_api_key_allows(read_key, AgentApiKeyAccessLevel.READ) is True
    assert agent_api_key_allows(read_key, AgentApiKeyAccessLevel.READ_WRITE) is False
    assert agent_api_key_allows(write_key, AgentApiKeyAccessLevel.READ_WRITE) is True
    assert agent_api_key_allows(None, AgentApiKeyAccessLevel.READ) is True
    assert agent_api_key_allows(None, AgentApiKeyAccessLevel.READ_WRITE) is False
    assert agent_api_key_allows(None, AgentApiKeyAccessLevel.ADMIN) is False
    with pytest.raises(PermissionError, match="requires Read \\+ write access"):
        require_agent_api_key_access(read_key, AgentApiKeyAccessLevel.READ_WRITE)
    with pytest.raises(PermissionError, match="This Rowset API key has Read access"):
        require_agent_api_key_access(None, AgentApiKeyAccessLevel.READ_WRITE)
    with pytest.raises(ValueError, match="Permission must be one of"):
        normalize_agent_api_key_access_level("root")


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
    assert created_key["uuid"]
    assert created_key["access_level_label"] == "Read + write"

    agent_api_key = AgentApiKey.objects.get(name="Codex")
    raw_key = get_agent_api_key_token(agent_api_key)
    assert agent_api_key.token_hash == hash_agent_api_key(raw_key)
    content = response.content.decode()
    assert raw_key not in content
    assert "Created Codex with Read + write access." in content
    assert "Copy key" in content
    assert reverse("agent_api_key_token", args=[agent_api_key.uuid]) in content
    assert "Copy setup prompt" in content
    assert reverse("agent_api_key_setup_prompt", args=[agent_api_key.uuid]) in content
    assert 'data-copy-tracking-event="rowset_agent_setup_prompt_copied"' in content

    followup = auth_client.get(reverse("settings"))
    assert followup.context["created_agent_api_key"] is None
    assert raw_key not in followup.content.decode()


def test_settings_lists_active_agent_api_keys_without_raw_secret(auth_client, profile):
    credential = create_agent_api_key(profile, "Reporting Agent", AgentApiKeyAccessLevel.READ)
    revoked_credential = create_agent_api_key(profile, "Old Agent", AgentApiKeyAccessLevel.ADMIN)
    revoked_credential.agent_api_key.revoked_at = timezone.now()
    revoked_credential.agent_api_key.save(update_fields=["revoked_at", "updated_at"])

    response = auth_client.get(reverse("settings"))
    content = response.content.decode()

    assert list(response.context["agent_api_keys"]) == [credential.agent_api_key]
    assert "Reporting Agent" in content
    assert "Read" in content
    assert f"{credential.agent_api_key.key_prefix}..." in content
    assert "Copy key" in content
    assert reverse("agent_api_key_token", args=[credential.agent_api_key.uuid]) in content
    assert "Copy setup prompt" in content
    assert reverse("agent_api_key_setup_prompt", args=[credential.agent_api_key.uuid]) in content
    assert credential.raw_key not in content
    assert "Old Agent" not in content
    assert f"{revoked_credential.agent_api_key.key_prefix}..." not in content


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


def test_agent_api_key_token_endpoint_returns_selected_key(auth_client, profile):
    credential = create_agent_api_key(profile, "Reporting Agent")

    response = auth_client.get(reverse("agent_api_key_token", args=[credential.agent_api_key.uuid]))

    assert response.status_code == 200
    assert response["Content-Type"] == "application/json"
    assert response["Cache-Control"] == "no-store"
    assert response.json() == {"api_key": credential.raw_key}


def test_agent_api_key_token_endpoint_rejects_revoked_key(auth_client, profile):
    credential = create_agent_api_key(profile, "Reporting Agent")
    credential.agent_api_key.revoked_at = timezone.now()
    credential.agent_api_key.save(update_fields=["revoked_at", "updated_at"])

    response = auth_client.get(reverse("agent_api_key_token", args=[credential.agent_api_key.uuid]))

    assert response.status_code == 404


def test_agent_api_key_token_endpoint_rejects_other_profile_key(
    auth_client,
    django_user_model,
):
    other_user = django_user_model.objects.create_user(
        username="othertokenkeyuser",
        email="othertokenkeyuser@example.com",
        password="password123",
    )
    credential = create_agent_api_key(other_user.profile, "Reporting Agent")

    response = auth_client.get(reverse("agent_api_key_token", args=[credential.agent_api_key.uuid]))

    assert response.status_code == 404


def test_agent_api_key_token_endpoint_rejects_key_without_recoverable_token(
    auth_client,
    profile,
):
    agent_api_key = AgentApiKey.objects.create(
        profile=profile,
        name="Old Agent",
        key_prefix="rsk_oldtoken",
        token_hash=hash_agent_api_key("rsk_oldtoken"),
    )

    response = auth_client.get(reverse("agent_api_key_token", args=[agent_api_key.uuid]))

    assert response.status_code == 404
    assert response.json() == {"error": "API key token is unavailable."}


def test_agent_api_key_setup_prompt_endpoint_rejects_revoked_key(auth_client, profile):
    credential = create_agent_api_key(profile, "Reporting Agent")
    credential.agent_api_key.revoked_at = timezone.now()
    credential.agent_api_key.save(update_fields=["revoked_at", "updated_at"])

    response = auth_client.get(
        reverse("agent_api_key_setup_prompt", args=[credential.agent_api_key.uuid])
    )

    assert response.status_code == 404


def test_agent_api_key_setup_prompt_endpoint_rejects_other_profile_key(
    auth_client,
    django_user_model,
):
    other_user = django_user_model.objects.create_user(
        username="otherpromptkeyuser",
        email="otherpromptkeyuser@example.com",
        password="password123",
    )
    credential = create_agent_api_key(other_user.profile, "Reporting Agent")

    response = auth_client.get(
        reverse("agent_api_key_setup_prompt", args=[credential.agent_api_key.uuid])
    )

    assert response.status_code == 404


def test_agent_api_key_setup_prompt_endpoint_uses_placeholder_without_recoverable_token(
    auth_client,
    profile,
):
    agent_api_key = AgentApiKey.objects.create(
        profile=profile,
        name="Old Agent",
        key_prefix="rsk_oldtoken",
        token_hash=hash_agent_api_key("rsk_oldtoken"),
    )

    response = auth_client.get(reverse("agent_api_key_setup_prompt", args=[agent_api_key.uuid]))

    assert response.status_code == 200
    assert (
        "Rowset API key: [full Old Agent key with prefix rsk_oldtoken...]"
        in response.json()["prompt"]
    )


@override_settings(
    SITE_URL="https://rowset.example",
    SECRET_KEY="old-secret",
    SECRET_KEY_FALLBACKS=[],
)
def test_agent_api_key_setup_prompt_endpoint_uses_secret_key_fallback(client, profile):
    credential = create_agent_api_key(profile, "Reporting Agent")

    with override_settings(SECRET_KEY="new-secret", SECRET_KEY_FALLBACKS=["old-secret"]):
        client.force_login(profile.user)
        response = client.get(
            reverse("agent_api_key_setup_prompt", args=[credential.agent_api_key.uuid])
        )

    assert response.status_code == 200
    assert f"Rowset API key: {credential.raw_key}" in response.json()["prompt"]


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


def test_settings_allows_reusing_revoked_agent_api_key_name(auth_client, profile):
    old_credential = create_agent_api_key(profile, "Codex")
    old_credential.agent_api_key.revoked_at = timezone.now()
    old_credential.agent_api_key.save(update_fields=["revoked_at", "updated_at"])

    response = auth_client.post(
        reverse("create_agent_api_key"),
        {"name": "Codex"},
        follow=True,
    )

    assert response.status_code == 200
    active_key = AgentApiKey.objects.get(
        profile=profile,
        name="Codex",
        revoked_at__isnull=True,
    )
    assert active_key.pk != old_credential.agent_api_key.pk
    assert AgentApiKey.objects.filter(profile=profile, name="Codex").count() == 2
    assert list(response.context["agent_api_keys"]) == [active_key]
    assert "Created Codex with Read + write access." in response.content.decode()


def test_settings_creates_agent_api_key_with_selected_permission(auth_client, profile):
    response = auth_client.post(
        reverse("create_agent_api_key"),
        {"name": "Provisioner", "access_level": AgentApiKeyAccessLevel.ADMIN},
        follow=True,
    )

    assert response.status_code == 200
    agent_api_key = AgentApiKey.objects.get(profile=profile, name="Provisioner")
    assert agent_api_key.access_level == AgentApiKeyAccessLevel.ADMIN
    assert "Created Provisioner with Admin access." in response.content.decode()


def test_settings_owner_can_revoke_agent_api_key(auth_client, profile):
    credential = create_agent_api_key(profile, "Codex")

    response = auth_client.post(
        reverse("revoke_agent_api_key", args=[credential.agent_api_key.uuid]),
        follow=True,
    )

    assert response.status_code == 200
    credential.agent_api_key.refresh_from_db()
    assert credential.agent_api_key.revoked_at is not None
    assert resolve_api_key_profile(credential.raw_key) is None
    assert list(response.context["agent_api_keys"]) == []
    assert "No active API keys." in response.content.decode()


def test_settings_revoke_agent_api_key_redirects_without_follow(auth_client, profile):
    credential = create_agent_api_key(profile, "Codex")

    response = auth_client.post(
        reverse("revoke_agent_api_key", args=[credential.agent_api_key.uuid]),
    )

    assert response.status_code == 302
    assert response["Location"] == reverse("settings")


def test_settings_revoke_preserves_active_created_agent_api_key_context(auth_client, profile):
    created_credential = create_agent_api_key(profile, "Codex")
    revoked_credential = create_agent_api_key(profile, "Old Agent")

    response = auth_client.post(
        reverse("revoke_agent_api_key", args=[revoked_credential.agent_api_key.uuid]),
        {"created_agent_api_key_uuid": str(created_credential.agent_api_key.uuid)},
        follow=True,
    )

    assert response.status_code == 200
    assert response.redirect_chain == [
        (
            f"{reverse('settings')}?created_agent_api_key={created_credential.agent_api_key.uuid}",
            302,
        )
    ]
    assert response.context["created_agent_api_key"] == {
        "uuid": str(created_credential.agent_api_key.uuid),
        "name": "Codex",
        "access_level_label": "Read + write",
    }
    assert list(response.context["agent_api_keys"]) == [created_credential.agent_api_key]
    assert "Created Codex with Read + write access." in response.content.decode()
    assert f"{revoked_credential.agent_api_key.key_prefix}..." not in response.content.decode()


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
