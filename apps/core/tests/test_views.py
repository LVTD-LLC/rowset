from types import SimpleNamespace

import pytest
from allauth.account.models import EmailAddress
from django.contrib import messages as message_constants
from django.contrib.messages import get_messages
from django.db import IntegrityError, OperationalError, transaction
from django.test import RequestFactory, override_settings
from django.urls import path, reverse
from django.utils import timezone
from django.views.generic import TemplateView

from apps.core import agent_skill
from apps.core.admin_dashboard import build_admin_dashboard_context
from apps.core.models import AgentApiKey, Feedback, Profile
from apps.core.services import create_agent_api_key, get_or_create_profile_for_user
from apps.core.views import build_agent_setup_prompt, get_or_create_stripe_customer, server_error
from apps.datasets.models import Dataset, Project
from rowset.utils import build_absolute_public_url


def _broken_view(_request):
    raise RuntimeError("boom")


urlpatterns = [
    path("", TemplateView.as_view(), name="landing"),
    path("home", TemplateView.as_view(), name="home"),
    path("broken/", _broken_view, name="broken"),
    path("api/broken/", _broken_view, name="api_broken"),
    path("mcp/broken/", _broken_view, name="mcp_broken"),
]

handler500 = "apps.core.views.server_error"
handler404 = "apps.core.views.page_not_found"


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
@override_settings(ROOT_URLCONF=__name__, DEBUG=False)
def test_server_error_redirects_authenticated_browser_requests_to_home(auth_client):
    auth_client.raise_request_exception = False

    response = auth_client.get("/broken/")

    assert response.status_code == 302
    assert response["Location"] == reverse("home")
    flash_messages = list(get_messages(response.wsgi_request))
    assert len(flash_messages) == 1
    assert flash_messages[0].level == message_constants.ERROR
    assert str(flash_messages[0]) == "Something went wrong. You have been redirected."


@override_settings(ROOT_URLCONF=__name__, DEBUG=False)
def test_server_error_redirects_anonymous_browser_requests_to_landing(client):
    client.raise_request_exception = False

    response = client.get("/broken/")

    assert response.status_code == 302
    assert response["Location"] == reverse("landing")
    flash_messages = list(get_messages(response.wsgi_request))
    assert len(flash_messages) == 1
    assert flash_messages[0].level == message_constants.ERROR
    assert str(flash_messages[0]) == "Something went wrong. You have been redirected."


@pytest.mark.django_db
@override_settings(ROOT_URLCONF=__name__, DEBUG=False)
def test_server_error_redirects_htmx_browser_requests_with_header(auth_client):
    auth_client.raise_request_exception = False

    response = auth_client.get("/broken/", HTTP_HX_REQUEST="true")

    assert response.status_code == 200
    assert response["HX-Redirect"] == reverse("home")
    flash_messages = list(get_messages(response.wsgi_request))
    assert len(flash_messages) == 1
    assert flash_messages[0].level == message_constants.ERROR
    assert str(flash_messages[0]) == "Something went wrong. You have been redirected."


@override_settings(ROOT_URLCONF=__name__)
def test_server_error_redirects_to_landing_when_request_has_no_user():
    request = RequestFactory().get("/broken/")

    response = server_error(request)

    assert response.status_code == 302
    assert response["Location"] == reverse("landing")


@override_settings(ROOT_URLCONF="rowset.urls", DEBUG=False)
def test_server_error_redirect_works_with_project_urlconf(client, monkeypatch):
    client.raise_request_exception = False

    def raise_error(self, request, *args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("apps.pages.views.LandingPageView.get", raise_error)

    response = client.get("/")

    assert response.status_code == 302
    assert response["Location"] == reverse("landing")
    flash_messages = list(get_messages(response.wsgi_request))
    assert len(flash_messages) == 1
    assert flash_messages[0].level == message_constants.ERROR
    assert str(flash_messages[0]) == "Something went wrong. You have been redirected."


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="rowset.urls", DEBUG=False)
def test_page_not_found_does_not_load_the_session(auth_client, monkeypatch):
    def fail_session_load(_session):
        raise OperationalError("the connection is closed")

    monkeypatch.setattr("django.contrib.sessions.backends.db.SessionStore.load", fail_session_load)
    auth_client.raise_request_exception = False

    response = auth_client.get("/missing-page")

    assert response.status_code == 404
    assert b"Page not found" in response.content


@pytest.mark.django_db
@override_settings(ROOT_URLCONF=__name__, DEBUG=False)
@pytest.mark.parametrize("path", ["/api/broken/", "/mcp/broken/"])
def test_server_error_preserves_programmatic_500_responses(auth_client, path):
    auth_client.raise_request_exception = False

    response = auth_client.get(path)

    assert response.status_code == 500
    assert response["Content-Type"].startswith("text/html")


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

        assert "<title>Dashboard · Rowset</title>" in content
        assert "Set up Rowset in two steps" in content
        assert "Create an agent key" in content
        assert "Create agent key" in content
        assert "data-uidotsh" not in content
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
        assert "Create an agent key" in content
        assert "Create agent key" in content
        assert "Copy setup prompt" not in content
        assert "Copy request" not in content
        assert "Rowset API key: ***" not in content
        assert profile.key not in content
        assert reverse("create_agent_api_key") in content
        assert 'name="next" value="home"' in content
        assert "Skip setup for now" not in content
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
        assert 'data-copy-tracking-event="rowset_agent_setup_prompt_copied"' in content
        assert "Copy request" not in content
        assert "First request for your agent" not in content
        assert "Give your agent its first job" not in content
        assert "Copy first task" not in content
        assert "Copy setup prompt" in content
        assert content.count('data-copy-success-event="agent-setup-prompt-copied"') == 1
        assert "Skip setup for now" not in content
        assert "private bearer token" in content
        assert "Rowset current docs index" in masked_prompt
        assert "Rowset current capabilities" in masked_prompt
        assert "Rowset setup skill" in masked_prompt
        assert "post-verification activation handoff" in masked_prompt

    @override_settings(SITE_URL="https://rowset.example")
    def test_home_view_collapses_prompt_and_completes_copy_task_after_copy_success(
        self,
        auth_client,
        profile,
    ):
        create_agent_api_key(profile, "Codex")

        response = auth_client.get(reverse("home"))

        content = response.content.decode()
        assert 'x-data="{ promptCopied: false, promptVisible: false }"' in content
        assert '@agent-setup-prompt-copied="promptCopied = true"' in content
        assert 'data-copy-success-event="agent-setup-prompt-copied"' in content
        assert 'data-copy-response-key="prompt"' in content
        assert 'x-text="promptCopied ? &#x27;✓&#x27; : &#x27;2&#x27;"' in content
        assert 'x-data="copyPanel"' in content
        assert 'x-show="promptVisible"' in content
        assert 'aria-controls="agent-setup-prompt-preview"' in content
        assert 'id="agent-setup-prompt-preview"' in content
        assert ':aria-expanded="promptVisible"' in content
        prompt_toggle = (
            'x-text="promptVisible ? &#x27;Hide what will be copied&#x27; : '
            '&#x27;See what will be copied&#x27;"'
        )
        assert prompt_toggle in content

    def test_home_view_requires_agent_setup_for_previously_dismissed_profile(
        self,
        auth_client,
        profile,
    ):
        profile.agent_setup_prompt_dismissed = True
        profile.save(update_fields=["agent_setup_prompt_dismissed"])

        response = auth_client.get(reverse("home"))

        content = response.content.decode()
        assert response.context["show_agent_setup_prompt"] is True
        assert "Set up Rowset in two steps" in content
        assert "Create an agent key" in content
        assert "Your data workspace" not in content

    def test_home_view_hides_agent_setup_prompt_after_setup_completes(self, auth_client, profile):
        profile.setup_completed_at = timezone.now()
        profile.save(update_fields=["setup_completed_at"])

        response = auth_client.get(reverse("home"))

        content = response.content.decode()
        assert response.context["show_agent_setup_prompt"] is False
        assert "Set up Rowset in two steps" not in content
        assert "Your data workspace" in content

    def test_home_view_keeps_agent_setup_prompt_until_setup_completes(
        self,
        auth_client,
        profile,
    ):
        Dataset.objects.create(
            profile=profile,
            name="People",
            headers=["name"],
            row_count=0,
        )

        response = auth_client.get(reverse("home"))

        content = response.content.decode()
        assert response.context["show_agent_setup_prompt"] is True
        assert response.context["dashboard_stats"] == {
            "total_datasets": 1,
            "total_projects": 0,
            "total_rows": 0,
            "public_preview_count": 0,
        }
        assert response.context["selected_view_mode"] == "grouped"
        assert "Set up Rowset in two steps" in content

    @override_settings(SITE_URL="https://rowset.example")
    def test_home_view_creates_missing_profile(self, auth_client, user):
        user.profile.delete()

        response = auth_client.get(reverse("home"))

        assert response.status_code == 200
        content = response.content.decode()
        assert "agent_setup_prompt_masked" not in response.context
        assert "agent_setup_prompt" not in response.context
        assert response.context["active_agent_api_key"] is None
        assert "Set up Rowset in two steps" in content
        assert "Create an agent key" in content
        assert "Create agent key" in content
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
        assert "Copy setup prompt" in content
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
        assert 'src="/static/js/posthog-identity.js"' in content
        assert "<form data-posthog-reset" in content

    @override_settings(POSTHOG_API_KEY="phc_test")
    def test_posthog_snippet_preserves_anonymous_identity(self, client):
        response = client.get(reverse("landing"))

        content = response.content.decode()
        assert response.status_code == 200
        assert 'posthog.init("phc_test"' in content
        assert "posthog.identify(" not in content
        assert 'src="/static/js/posthog-identity.js"' in content
        assert "<form data-posthog-reset" not in content

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

    def test_settings_view_includes_design_colorize_toggle(self, auth_client):
        response = auth_client.get(reverse("settings"))

        content = response.content.decode()
        assert response.status_code == 200
        assert "Design" in content
        assert "Colorize" in content
        assert 'name="choice_colorization_enabled"' in content

    def test_settings_view_updates_choice_colorization_preference(self, auth_client, profile):
        response = auth_client.post(
            reverse("settings"),
            {
                "settings_section": "design",
                "choice_colorization_enabled": "on",
            },
        )

        assert response.status_code == 302
        profile.refresh_from_db()
        assert profile.choice_colorization_enabled is True

        response = auth_client.post(
            reverse("settings"),
            {
                "settings_section": "design",
            },
        )

        assert response.status_code == 302
        profile.refresh_from_db()
        assert profile.choice_colorization_enabled is False

    def test_app_shell_renders_overview_navigation(self, auth_client):
        response = auth_client.get(reverse("settings"))

        content = response.content.decode()
        assert "Overview" in content

    def test_agent_instructions_markdown_is_public_and_actionable(self, client):
        response = client.get(reverse("agent_instructions_rowset_mcp"))

        assert response.status_code == 200
        assert response["Content-Type"] == "text/markdown; charset=utf-8"
        content = response.content.decode()
        assert "name: rowset" in content
        assert "# Rowset" in content
        assert "Use Rowset as a stable backend for user-owned structured datasets." in content
        assert "MCP, the Rowset CLI, or the REST API" in content
        assert "get_rowset_capabilities" in content
        assert "working with Rowset after access" in content
        assert "Search before creating duplicates" in content
        assert "Public previews are read-only sharing surfaces" in content
        assert "Suggest two to four tailored" not in content
        assert "daily Rowset tips automation" not in content

    def test_companion_agent_instruction_markdown_is_public(self, client):
        setup_response = client.get(reverse("agent_instructions_rowset_setup"))
        features_response = client.get(reverse("agent_instructions_rowset_features"))
        use_cases_response = client.get(reverse("agent_instructions_rowset_use_cases"))

        assert setup_response.status_code == 200
        assert setup_response["Content-Type"] == "text/markdown; charset=utf-8"
        setup_content = setup_response.content.decode()
        assert "name: rowset-setup" in setup_content
        assert "Ask the user which interface to configure" in setup_content
        assert "get_user_info" in setup_content
        assert "marks onboarding complete" in setup_content
        assert (
            "Suggest two to four tailored project, section, and dataset structures" in setup_content
        )
        assert "daily Rowset tips automation" in setup_content
        assert "runs in the user's agent account" in setup_content

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
    def test_llms_txt_route_name_remains_public_and_does_not_expose_profile_key(
        self, client, profile
    ):
        response = client.get(reverse("llms_txt"))

        assert response.status_code == 200
        assert response["Content-Type"] == "text/plain; charset=utf-8"
        assert response["Cache-Control"] == "public, max-age=300"
        content = response.content.decode()
        assert "# Rowset" in content
        assert "https://rowset.example/mcp/" in content
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
            "rowset_setup_skill_path",
            lambda: tmp_path / "missing-setup.md",
        )
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

        setup_response = client.get(reverse("agent_instructions_rowset_setup"))
        features_response = client.get(reverse("agent_instructions_rowset_features"))
        use_cases_response = client.get(reverse("agent_instructions_rowset_use_cases"))

        assert setup_response.status_code == 200
        setup_content = setup_response.content.decode()
        assert "name: rowset-setup" in setup_content
        assert "connect an AI agent to Rowset" in setup_content
        assert "# Rowset Setup" in setup_content
        assert "rowset-setup/SKILL.md" in setup_content

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

        prompt = build_agent_setup_prompt(request, api_key="rsk_explicit")

        assert "Rowset MCP URL: https://rowset.example/mcp/" in prompt
        assert "Rowset REST API base: https://rowset.example/api/" in prompt
        assert "Rowset CLI guide: https://rowset.example/docs/use-cli.md" in prompt
        assert "Rowset setup skill: https://rowset.example/skills/rowset-setup/SKILL.md" in prompt
        assert "Rowset skill: https://rowset.example/SKILL.md" in prompt
        assert "Rowset skill install: npx skills add LVTD-LLC/rowset" in prompt
        assert "Rowset current docs index: https://rowset.example/llms.txt" in prompt
        assert "Rowset docs: https://rowset.example/docs" in prompt
        assert "Rowset blog: https://rowset.example/blog" in prompt
        assert "Rowset current API docs: https://rowset.example/api/docs" in prompt
        assert "Rowset current capabilities: https://rowset.example/api/capabilities" in prompt
        assert "Rowset trial rewards: https://rowset.example/trial-rewards" in prompt
        assert "Rowset API key: rsk_explicit" in prompt
        assert "Read or install the Rowset setup skill before acting" in prompt
        assert "post-verification activation handoff" in prompt
        assert "Use the Rowset skill for ongoing platform interaction" in prompt
        assert "suggest two to four useful project" not in prompt
        assert "codex mcp add" not in prompt.lower()

        masked_prompt = build_agent_setup_prompt(request, mask_api_key=True)
        assert "Rowset API key: ***" in masked_prompt
        assert user.profile.key not in masked_prompt

    @override_settings(SITE_URL="https://rowset.example")
    def test_build_agent_setup_prompt_creates_missing_profile(self, rf, user):
        user.profile.delete()
        fresh_user = user.__class__.objects.get(pk=user.pk)
        request = rf.get("/home", HTTP_HOST="internal-proxy")
        request.user = fresh_user

        prompt = build_agent_setup_prompt(request, mask_api_key=True)

        assert "Rowset API key: ***" in prompt
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
        assert "Rows stored" in content
        assert "Public previews" in content
        assert "Operations" in content

    def test_admin_panel_summarizes_product_health_growth_and_operations(
        self,
        client,
        django_user_model,
    ):
        now = timezone.now()
        superuser = django_user_model.objects.create_superuser(
            username="admin-health",
            email="admin-health@example.com",
            password="strong-test-pass-123",
        )
        activated_user = django_user_model.objects.create_user(
            username="activated-user",
            email="activated@example.com",
            password="strong-test-pass-123",
        )
        stalled_user = django_user_model.objects.create_user(
            username="stalled-user",
            email="stalled@example.com",
            password="strong-test-pass-123",
        )
        old_user = django_user_model.objects.create_user(
            username="old-user",
            email="old@example.com",
            password="strong-test-pass-123",
        )
        django_user_model.objects.filter(pk=activated_user.pk).update(
            date_joined=now - timezone.timedelta(days=2)
        )
        django_user_model.objects.filter(pk=stalled_user.pk).update(
            date_joined=now - timezone.timedelta(days=3)
        )
        django_user_model.objects.filter(pk=old_user.pk).update(
            date_joined=now - timezone.timedelta(days=20)
        )
        activated_user.profile.setup_completed_at = now - timezone.timedelta(days=1)
        activated_user.profile.save(update_fields=["setup_completed_at", "updated_at"])

        active_key = AgentApiKey.objects.create(
            profile=activated_user.profile,
            name="Active agent",
            key_prefix="rsk_active",
            token_hash="a" * 64,
            last_used_at=now - timezone.timedelta(hours=2),
        )
        AgentApiKey.objects.create(
            profile=stalled_user.profile,
            name="Unused agent",
            key_prefix="rsk_unused",
            token_hash="b" * 64,
        )
        Dataset.objects.create(
            profile=activated_user.profile,
            created_by_agent_api_key=active_key,
            name="Agent research",
            headers=["topic"],
            row_count=14,
            public_enabled=True,
        )
        feedback = Feedback.objects.create(
            profile=activated_user.profile,
            feedback="Please add clearer usage reporting.",
            page="/home",
        )
        Feedback.objects.filter(pk=feedback.pk).update(created_at=now - timezone.timedelta(hours=3))
        client.force_login(superuser)

        response = client.get(reverse("admin_panel"))

        assert response.status_code == 200
        assert response.context["period_days"] == 7
        assert response.context["product_health"] == {
            "new_users": 2,
            "setup_completed": 1,
            "active_agents": 1,
        }
        assert response.context["activation_funnel"][0]["count"] == 3
        assert response.context["activation_funnel"][-1]["count"] == 1
        assert response.context["operations"]["rows_stored"] == 14
        assert response.context["operations"]["public_previews"] == 1
        assert response.context["attention"]["stalled_onboarding"] == 1
        assert response.context["attention"]["unused_agent_keys"] == 1
        assert response.context["attention"]["new_feedback"] == 1
        assert response.context["activity_feed"][0]["kind"] == "feedback"
        content = response.content.decode()
        assert "Product health" in content
        assert "Activation funnel" in content
        assert "Growth" in content
        assert "Operations" in content
        assert "Needs attention" in content
        assert "Recent activity" in content
        assert 'hx-sync="closest #admin-dashboard:replace"' in content
        assert "New users:" in content
        assert 'tabindex="0"' in content

    def test_admin_panel_counts_trials_from_trial_dates(self, client, django_user_model):
        now = timezone.now()
        superuser = django_user_model.objects.create_superuser(
            username="admin-trials",
            email="admin-trials@example.com",
            password="strong-test-pass-123",
        )
        trial_user = django_user_model.objects.create_user(
            username="active-trial-user",
            email="active-trial@example.com",
            password="strong-test-pass-123",
        )
        trial_user.profile.trial_started_at = now - timezone.timedelta(days=2)
        trial_user.profile.trial_ends_at = now + timezone.timedelta(days=2)
        trial_user.profile.save(update_fields=["trial_started_at", "trial_ends_at", "updated_at"])
        client.force_login(superuser)

        response = client.get(reverse("admin_panel"))

        assert response.context["growth"]["active_trials"] == 1
        assert response.context["attention"]["trials_expiring"] == 1

    def test_admin_dashboard_activity_feed_orders_sources_before_slicing(self, django_user_model):
        now = timezone.now()
        for number in range(13):
            item = Feedback.objects.create(feedback=f"Feedback {number}", page="/admin-panel")
            Feedback.objects.filter(pk=item.pk).update(
                created_at=now + timezone.timedelta(minutes=number)
            )
            user = django_user_model.objects.create_user(
                username=f"feed-user-{number}",
                email=f"feed-user-{number}@example.com",
                password="strong-test-pass-123",
            )
            django_user_model.objects.filter(pk=user.pk).update(
                date_joined=now + timezone.timedelta(minutes=number)
            )

        context = build_admin_dashboard_context(7, now=now + timezone.timedelta(hours=1))
        activity_titles = {item["title"] for item in context["activity_feed"]}
        activity_details = {item["detail"] for item in context["activity_feed"]}

        assert "Feedback 12" in activity_titles
        assert "Feedback 0" not in activity_titles
        assert "feed-user-12@example.com" in activity_details
        assert "feed-user-0@example.com" not in activity_details

    def test_admin_dashboard_uses_calendar_day_boundaries(self, django_user_model):
        now = timezone.localtime(timezone.now()).replace(hour=18, minute=0, second=0, microsecond=0)
        first_day = now.replace(hour=0) - timezone.timedelta(days=6)
        user = django_user_model.objects.create_user(
            username="boundary-user",
            email="boundary@example.com",
            password="strong-test-pass-123",
        )
        django_user_model.objects.filter(pk=user.pk).update(
            date_joined=first_day + timezone.timedelta(hours=10)
        )

        context = build_admin_dashboard_context(7, now=now)

        assert context["product_health"]["new_users"] == 1
        assert sum(day["signups"] for day in context["growth_series"]) == 1

    def test_admin_panel_supports_a_thirty_day_htmx_range(self, client, django_user_model):
        now = timezone.now()
        superuser = django_user_model.objects.create_superuser(
            username="admin-range",
            email="admin-range@example.com",
            password="strong-test-pass-123",
        )
        recent_user = django_user_model.objects.create_user(
            username="recent-range-user",
            email="recent-range@example.com",
            password="strong-test-pass-123",
        )
        django_user_model.objects.filter(pk=recent_user.pk).update(
            date_joined=now - timezone.timedelta(days=20)
        )
        client.force_login(superuser)

        response = client.get(
            reverse("admin_panel"),
            {"period": "30"},
            HTTP_HX_REQUEST="true",
        )

        assert response.status_code == 200
        assert response.context["period_days"] == 30
        assert response.context["product_health"]["new_users"] == 1
        assert b'id="admin-dashboard"' in response.content
        assert b"<html" not in response.content

    def test_admin_panel_defaults_invalid_range_to_seven_days(self, client, django_user_model):
        superuser = django_user_model.objects.create_superuser(
            username="admin-invalid-range",
            email="admin-invalid-range@example.com",
            password="strong-test-pass-123",
        )
        client.force_login(superuser)

        response = client.get(reverse("admin_panel"), {"period": "365"})

        assert response.status_code == 200
        assert response.context["period_days"] == 7
