from types import SimpleNamespace

import pytest
from allauth.account.models import EmailAddress
from django.db import IntegrityError, transaction
from django.test import override_settings
from django.urls import reverse

from apps.core import agent_skill
from apps.core.models import Profile
from apps.core.services import create_agent_api_key, get_or_create_profile_for_user
from apps.core.views import build_agent_setup_prompt, get_or_create_stripe_customer
from apps.datasets.choices import DatasetStatus
from apps.datasets.models import Dataset, Project
from rowset.utils import build_absolute_public_url


@pytest.mark.django_db
@override_settings(STRIPE_CONTEXT="acct_test")
def test_get_or_create_stripe_customer_passes_stripe_context(profile, monkeypatch):
    calls = []

    def create_customer(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(id="cus_test")

    monkeypatch.setattr("apps.core.views.stripe.Customer.create", create_customer)

    customer = get_or_create_stripe_customer(profile, profile.user)

    assert customer.id == "cus_test"
    assert calls[0]["stripe_context"] == "acct_test"


@pytest.mark.django_db
@override_settings(STRIPE_CONTEXT="acct_test")
def test_get_or_create_stripe_customer_retrieve_passes_stripe_context(profile, monkeypatch):
    profile.stripe_customer_id = "cus_existing"
    profile.save(update_fields=["stripe_customer_id"])
    calls = []

    def retrieve_customer(customer_id, **kwargs):
        calls.append((customer_id, kwargs))
        return SimpleNamespace(id=customer_id)

    monkeypatch.setattr("apps.core.views.stripe.Customer.retrieve", retrieve_customer)

    customer = get_or_create_stripe_customer(profile, profile.user)

    assert customer.id == "cus_existing"
    assert calls == [("cus_existing", {"stripe_context": "acct_test"})]


@pytest.mark.django_db
@override_settings(
    STRIPE_CONTEXT="acct_test",
    STRIPE_PRICE_IDS={"monthly": "price_test"},
)
def test_checkout_session_passes_stripe_context(auth_client, profile, monkeypatch):
    calls = []

    monkeypatch.setattr(
        "apps.core.views.get_or_create_stripe_customer",
        lambda profile, user: SimpleNamespace(id="cus_test"),
    )

    def create_session(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(url="https://checkout.stripe.test/session")

    monkeypatch.setattr("apps.core.views.stripe.checkout.Session.create", create_session)

    response = auth_client.post(
        reverse("user_upgrade_checkout_session", args=[profile.user_id, "monthly"])
    )

    assert response.status_code == 303
    assert response["Location"] == "https://checkout.stripe.test/session"
    assert calls[0]["stripe_context"] == "acct_test"


@pytest.mark.django_db
@override_settings(STRIPE_CONTEXT="acct_test")
def test_billing_portal_session_passes_stripe_context(auth_client, profile, monkeypatch):
    profile.stripe_customer_id = "cus_test"
    profile.save(update_fields=["stripe_customer_id"])
    calls = []

    def create_session(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(url="https://billing.stripe.test/session")

    monkeypatch.setattr("apps.core.views.stripe.billing_portal.Session.create", create_session)

    response = auth_client.get(reverse("create_customer_portal_session"))

    assert response.status_code == 303
    assert response["Location"] == "https://billing.stripe.test/session"
    assert calls == [
        {
            "customer": "cus_test",
            "return_url": "http://testserver/home",
            "stripe_context": "acct_test",
        }
    ]


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
        assert "Setup tasks" in content
        assert "Create an API key" in content
        assert "Copy the setup prompt" in content
        assert "Your prompt will appear here" in content
        assert "Connect Google Sheets" not in content
        assert "Upload dataset" not in content

    @override_settings(SITE_URL="https://rowset.example")
    def test_home_view_prompts_for_agent_api_key_before_copy_prompt(
        self,
        auth_client,
        profile,
    ):
        url = reverse("home")
        response = auth_client.get(url)

        content = response.content.decode()
        assert "agent_setup_prompt_masked" not in response.context
        assert "agent_setup_prompt" not in response.context
        assert response.context["show_agent_setup_prompt"] is True
        assert response.context["active_agent_api_key"] is None
        assert "Create an API key" in content
        assert "Create key" in content
        assert "Your prompt will appear here" in content
        assert "Copy agent prompt" not in content
        assert "Copy request" not in content
        assert "Rowset API key: ***" not in content
        assert profile.key not in content
        assert reverse("create_agent_api_key") in content
        assert 'name="next" value="home"' in content
        assert reverse("agent_setup_prompt") not in content
        assert reverse("dismiss_agent_setup_prompt") in content
        assert "Skip setup for now" in content
        assert "Only share this prompt with agents and people you trust." not in content

    @override_settings(SITE_URL="https://rowset.example")
    def test_home_view_unlocks_agent_setup_prompt_after_agent_key_exists(
        self,
        auth_client,
        profile,
    ):
        credential = create_agent_api_key(profile, "Codex")

        response = auth_client.get(reverse("home"))

        masked_prompt = response.context["agent_setup_prompt_masked"]
        content = response.content.decode()
        assert response.context["show_agent_setup_prompt"] is True
        assert response.context["active_agent_api_key"] == credential.agent_api_key
        assert "Rowset API key: ***" in masked_prompt
        assert credential.raw_key not in masked_prompt
        assert profile.key not in masked_prompt
        assert "Rowset API key: ***" in content
        assert credential.raw_key not in content
        assert profile.key not in content
        assert (
            reverse("agent_api_key_setup_prompt", args=[credential.agent_api_key.uuid]) in content
        )
        assert reverse("agent_setup_prompt") not in content
        assert "Copy agent prompt" in content
        assert 'data-copy-tracking-event="rowset_agent_setup_prompt_copied"' in content
        assert "Copy request" in content
        assert "Verify Rowset with get_user_info" in content
        assert "Hide setup guide" in content
        assert "Only share this prompt with agents and people you trust." in content
        assert "create_dataset" in masked_prompt
        assert "update_dataset_public_preview" in masked_prompt

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
        assert "Projects and datasets" in content

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
        assert response.context["dashboard_stats"] == {
            "total_datasets": 1,
            "total_projects": 0,
            "total_rows": 0,
            "public_preview_count": 0,
        }
        assert response.context["selected_view_mode"] == "grouped"
        assert "Copy/paste prompt" not in content
        assert "Copy agent prompt" not in content
        assert "MCP endpoint" not in content
        assert "REST API base" not in content
        assert "Agent skill" not in content
        assert "People" in content
        assert "Workspace summary" in content

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
        assert "Rowset skill install: npx skills add LVTD-LLC/rowset" in prompt
        assert "get_user_info" in prompt
        assert "get_rowset_capabilities" in prompt
        assert "create_dataset" in prompt
        assert "update_dataset_public_preview" in prompt
        assert (
            "codex mcp add rowset --url <Rowset MCP URL> "
            "--bearer-token-env-var ROWSET_API_KEY" in prompt
        )
        assert "screenshots, public chats, generated files, or final responses" in prompt
        assert "full key, not only its prefix" in prompt
        assert prompt.index("discover the current MCP tools") < prompt.index("get_user_info")
        assert "discover the current MCP tools and API docs at runtime" in prompt

    @override_settings(SITE_URL="https://rowset.example")
    def test_home_view_creates_missing_profile(self, auth_client, user):
        user.profile.delete()

        response = auth_client.get(reverse("home"))

        assert response.status_code == 200
        content = response.content.decode()
        assert "agent_setup_prompt_masked" not in response.context
        assert "agent_setup_prompt" not in response.context
        assert response.context["active_agent_api_key"] is None
        assert "Connect your AI agent to Rowset" in content
        assert "Projects and datasets" in content
        assert "Workspace summary" in content
        assert user.__class__.objects.get(pk=user.pk).profile

    def test_get_or_create_profile_for_user_recovers_from_create_race(
        self,
        user,
        profile,
        monkeypatch,
    ):
        def raise_integrity_error(*args, **kwargs):
            raise IntegrityError("duplicate profile")

        monkeypatch.setattr(Profile.objects, "get_or_create", raise_integrity_error)

        assert get_or_create_profile_for_user(user) == profile

    def test_get_or_create_profile_for_user_recovers_inside_transaction(
        self,
        user,
        profile,
        monkeypatch,
    ):
        def raise_integrity_error(*args, **kwargs):
            raise IntegrityError("duplicate profile")

        monkeypatch.setattr(Profile.objects, "get_or_create", raise_integrity_error)

        with transaction.atomic():
            assert get_or_create_profile_for_user(user) == profile

    def test_home_create_agent_api_key_redirects_back_to_onboarding(self, auth_client):
        response = auth_client.post(
            reverse("create_agent_api_key"),
            {"name": "Codex", "next": "home"},
        )

        assert response.status_code == 302
        assert response["Location"] == reverse("home")
        followup = auth_client.get(reverse("home"))
        content = followup.content.decode()
        assert followup.context["active_agent_api_key"].name == "Codex"
        assert "Copy agent prompt" in content
        assert "Created an API key for Codex." in content

    @override_settings(POSTHOG_API_KEY="phc_test")
    def test_posthog_snippet_tracks_activation_events_without_pageviews(
        self,
        auth_client,
        profile,
    ):
        response = auth_client.get(reverse("home"))

        content = response.content.decode()
        assert 'posthog.init("phc_test"' in content
        assert "autocapture: false" in content
        assert "capture_pageview: false" in content
        assert 'defaults: "2026-05-30"' in content
        assert 'person_profiles: "identified_only"' in content
        assert "window.posthog && window.posthog.__loaded" in content
        assert f'posthog.identify("{profile.id}"' in content
        assert f'email: "{profile.user.email}"' in content
        assert "posthog.reset();" not in content

    @override_settings(POSTHOG_API_KEY="phc_test")
    def test_posthog_snippet_resets_anonymous_visitors(self, client):
        response = client.get(reverse("landing"))

        content = response.content.decode()
        assert response.status_code == 200
        assert 'posthog.init("phc_test"' in content
        assert "posthog.identify(" not in content
        assert "posthog.reset();" in content

    @override_settings(SITE_URL="https://rowset.example")
    def test_settings_view_omits_prompt_panel_and_legacy_key(self, auth_client, profile):
        EmailAddress.objects.create(user=profile.user, email=profile.user.email, verified=True)
        profile.agent_setup_prompt_dismissed = True
        profile.save(update_fields=["agent_setup_prompt_dismissed"])

        response = auth_client.get(reverse("settings"))

        content = response.content.decode()
        assert response.status_code == 200
        assert "Agent setup prompt" not in content
        assert "Copy/paste prompt" not in content
        assert "Copy agent prompt" not in content
        assert "Remove from dashboard" not in content
        assert "Legacy account API key" not in content
        assert "Copy legacy key" not in content
        assert "Rowset API key: ***" not in content
        assert f"Rowset API key: {profile.key}" not in content
        assert reverse("agent_setup_prompt") not in content

    def test_app_header_omits_dataset_and_project_nav_links(self, auth_client):
        response = auth_client.get(reverse("settings"))

        content = response.content.decode()
        assert f'href="{reverse("dataset_list")}"' not in content
        assert f'href="{reverse("project_list")}"' not in content

    def test_agent_instructions_markdown_is_public_and_actionable(self, client):
        response = client.get(reverse("agent_instructions_rowset_mcp"))

        assert response.status_code == 200
        assert response["Content-Type"] == "text/markdown; charset=utf-8"
        content = response.content.decode()
        assert "name: rowset" in content
        assert "# Rowset" in content
        assert "Use Rowset as a stable backend for user-owned structured datasets." in content
        assert "Streamable HTTP" in content
        assert "codex mcp add rowset --url <Rowset MCP URL>" in content
        assert "screenshots, public chats, generated files, or final responses" in content
        assert "not only the visible" in content
        assert "get_user_info" in content
        assert "get_rowset_capabilities" in content
        assert content.index("Discover available MCP tools") < content.index("get_user_info")
        assert "create_dataset" in content
        assert "list_dataset_relationships" in content
        assert "update_dataset_public_preview" in content
        assert "Keep user data private" in content

    def test_companion_agent_instruction_markdown_is_public(self, client):
        features_response = client.get(reverse("agent_instructions_rowset_features"))
        use_cases_response = client.get(reverse("agent_instructions_rowset_use_cases"))

        assert features_response.status_code == 200
        assert features_response["Content-Type"] == "text/markdown; charset=utf-8"
        features_content = features_response.content.decode()
        assert "name: rowset-features" in features_content
        assert "get_rowset_capabilities" in features_content
        assert "create_dataset_relationship" in features_content

        assert use_cases_response.status_code == 200
        assert use_cases_response["Content-Type"] == "text/markdown; charset=utf-8"
        use_cases_content = use_cases_response.content.decode()
        assert "name: rowset-use-cases" in use_cases_content
        assert "Personal CRM" in use_cases_content
        assert "Agent Task Board" in use_cases_content

    @override_settings(SITE_URL="https://rowset.example")
    def test_llms_txt_is_public_and_contains_discovery_surface(self, client, profile):
        response = client.get(reverse("llms_txt"))

        assert response.status_code == 200
        assert response["Content-Type"] == "text/plain; charset=utf-8"
        assert response["Cache-Control"] == "public, max-age=300"
        content = response.content.decode()
        assert "# Rowset" in content
        assert "get_rowset_capabilities" in content
        assert "Dataset relationships" in content
        assert "https://rowset.example/mcp/" in content
        assert "https://rowset.example/skills/rowset-features/SKILL.md" in content
        assert profile.key not in content

    def test_agent_instructions_markdown_falls_back_when_skill_file_is_missing(
        self,
        client,
        monkeypatch,
        tmp_path,
    ):
        monkeypatch.setattr(agent_skill, "rowset_skill_path", lambda: tmp_path / "missing.md")

        response = client.get(reverse("agent_instructions_rowset_mcp"))

        assert response.status_code == 200
        assert response["Content-Type"] == "text/markdown; charset=utf-8"
        content = response.content.decode()
        assert "The checked-in Rowset skill file could not be loaded" in content
        assert "npx skills add LVTD-LLC/rowset" in content
        assert "raw.githubusercontent.com/LVTD-LLC/rowset/main" in content

    def test_companion_agent_instructions_fallback_uses_companion_skill_name(
        self,
        client,
        monkeypatch,
        tmp_path,
    ):
        monkeypatch.setattr(
            agent_skill,
            "rowset_features_skill_path",
            lambda: tmp_path / "missing-features.md",
        )
        monkeypatch.setattr(
            agent_skill,
            "rowset_use_cases_skill_path",
            lambda: tmp_path / "missing-use-cases.md",
        )

        features_response = client.get(reverse("agent_instructions_rowset_features"))
        use_cases_response = client.get(reverse("agent_instructions_rowset_use_cases"))

        assert features_response.status_code == 200
        features_content = features_response.content.decode()
        assert "name: rowset-features" in features_content
        assert "what Rowset can do" in features_content
        assert "# Rowset Features" in features_content
        assert "rowset-features/SKILL.md" in features_content

        assert use_cases_response.status_code == 200
        use_cases_content = use_cases_response.content.decode()
        assert "name: rowset-use-cases" in use_cases_content
        assert "specific workflow" in use_cases_content
        assert "# Rowset Use Cases" in use_cases_content
        assert "rowset-use-cases/SKILL.md" in use_cases_content

    @override_settings(SITE_URL="http://rowset.example")
    def test_build_agent_setup_prompt_uses_https_public_site_url(self, rf, user):
        request = rf.get("/home", HTTP_HOST="internal-proxy")
        request.user = user

        prompt = build_agent_setup_prompt(request)

        assert "Rowset MCP URL: https://rowset.example/mcp/" in prompt
        assert "Rowset REST API base: https://rowset.example/api/" in prompt
        assert "Rowset skill: https://rowset.example/SKILL.md" in prompt
        assert "Rowset skill install: npx skills add LVTD-LLC/rowset" in prompt
        assert f"Rowset API key: {user.profile.key}" in prompt
        assert "bearer-token env var ROWSET_API_KEY" in prompt
        assert "get_rowset_capabilities" in prompt
        assert (
            "codex mcp add rowset --url <Rowset MCP URL> "
            "--bearer-token-env-var ROWSET_API_KEY" in prompt
        )
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

    def test_admin_panel_includes_rowset_dataset_project_stats(
        self,
        client,
        django_user_model,
        profile,
    ):
        superuser = django_user_model.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="strong-test-pass-123",
        )
        project = Project.objects.create(profile=profile, name="Operations")
        Dataset.objects.create(
            profile=profile,
            project=project,
            name="People",
            original_filename="people.csv",
            status=DatasetStatus.READY,
            headers=["name"],
            row_count=3,
            public_enabled=True,
        )
        client.force_login(superuser)

        response = client.get(reverse("admin_panel"))

        content = response.content.decode()
        assert response.status_code == 200
        assert response.context["total_datasets"] == 1
        assert response.context["total_projects"] == 1
        assert response.context["total_rows"] == 3
        assert response.context["public_preview_count"] == 1
        assert response.context["profile_count"] >= 1
        assert "Total datasets" in content
        assert "Total projects" in content
        assert "Total profiles" in content
        assert "Latest datasets" in content
        assert "Latest projects" in content
        assert "People" in content
        assert "Operations" in content
