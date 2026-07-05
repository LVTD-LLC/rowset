import json
import re
import time
from dataclasses import replace

import pytest
from allauth.account.models import EmailAddress
from allauth.mfa.models import Authenticator
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings
from django.urls import reverse
from django.utils.html import strip_tags

from apps.core.capabilities import RowsetUseCase
from apps.pages import use_cases as page_use_cases
from apps.pages.checks import check_use_case_page_registry
from apps.pages.schema import article_schema, breadcrumb_list_schema, faq_page_schema, json_ld
from apps.pages.views import build_absolute_static_url

pytestmark = pytest.mark.django_db


def _nav_html(content, aria_label):
    start = content.index(f'aria-label="{aria_label}"')
    return content[start : content.index("</nav>", start)]


def test_login_page_shows_passkey_option(client):
    response = client.get(reverse("account_login"))
    assert response.status_code == 200

    content = response.content.decode()
    assert "Sign in with a passkey" in content
    assert 'id="mfa_login"' in content
    assert "window.webauthnJSON.get(requestOptions)" in content
    assert "X-Requested-With" in content
    assert "allauth.webauthn.forms.loginForm" not in content


def test_signup_page_hides_passkey_signup_option(client):
    response = client.get(reverse("account_signup"))
    assert response.status_code == 200

    content = response.content.decode()
    assert "Username" not in content
    assert "Confirm Password" not in content
    assert "Cofirm Password" not in content
    assert "Sign up using a passkey" not in content


def test_login_page_uses_email_instead_of_username(client):
    response = client.get(reverse("account_login"))
    assert response.status_code == 200

    content = response.content.decode()
    assert 'placeholder="Email"' in content
    assert 'type="email"' in content
    assert 'placeholder="Username"' not in content


def test_signup_redirects_to_dashboard_without_blocking_email_code_page(
    client, monkeypatch, settings
):
    sent_confirmations = []

    def fake_send_confirmation_mail(self, request, emailconfirmation, signup):
        sent_confirmations.append((emailconfirmation.email_address.email, signup))

    monkeypatch.setattr(
        "rowset.adapters.CustomAccountAdapter.send_confirmation_mail",
        fake_send_confirmation_mail,
    )
    settings.POSTHOG_API_KEY = ""

    response = client.post(
        reverse("account_signup"),
        data={
            "email": "newuser@example.com",
            "password1": "strong-test-pass-123",
        },
    )

    assert response.status_code == 302
    assert response["Location"] == reverse("home")
    user = get_user_model().objects.get(email="newuser@example.com")
    assert user.username
    assert sent_confirmations == [("newuser@example.com", True)]


def test_dashboard_does_not_show_email_confirmation_reminder(client):
    user = get_user_model().objects.create_user(
        username="unverified",
        email="unverified@example.com",
        password="strong-test-pass-123",
    )
    EmailAddress.objects.update_or_create(
        user=user,
        email=user.email,
        defaults={"primary": True, "verified": False},
    )
    client.force_login(user)

    response = client.get(reverse("home"))

    assert response.status_code == 200
    assert response["Cache-Control"] == "public, max-age=3600"
    content = response.content.decode()
    assert "Your email is not yet confirmed" not in content
    assert "Connect your AI agent to Rowset" in content


def test_landing_page_omits_prompt_and_shows_agent_native_positioning(client):
    response = client.get(reverse("landing"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Agent setup prompt" not in content
    assert "Rowset MCP URL:" not in content
    assert "Rowset skill install:" not in content
    assert "Give AI agents a place to put structured work." in content
    assert "One backend. Many agent workflows." in content
    assert "Agent CRM" in content
    assert "Content pipeline" in content
    assert "Bug and QA tracker" in content
    assert reverse("use_cases") in content
    assert reverse("docs_page", kwargs={"category": "features", "page": "mcp"}) in content
    assert reverse("docs_page", kwargs={"category": "api-reference", "page": "datasets"}) in content
    assert reverse("airtable_alternative") in content
    assert '"@type": "SoftwareApplication"' in content
    assert '"@type": "Organization"' in content


def test_shared_site_chrome_links_to_blog_from_navbar_and_footer(client):
    blog_href = f'href="{reverse("blog_posts")}"'

    landing_response = client.get(reverse("landing"))
    assert landing_response.status_code == 200
    landing_content = landing_response.content.decode()

    assert blog_href in _nav_html(landing_content, "Primary navigation")
    assert blog_href in _nav_html(landing_content, "Mobile navigation")
    assert blog_href in _nav_html(landing_content, "Footer navigation")

    user = get_user_model().objects.create_user(
        username="chrome-blog",
        email="chrome-blog@example.com",
        password="strong-test-pass-123",
    )
    client.force_login(user)

    app_response = client.get(reverse("home"))
    assert app_response.status_code == 200
    app_content = app_response.content.decode()

    assert blog_href in _nav_html(app_content, "Primary navigation")
    assert blog_href in _nav_html(app_content, "Mobile navigation")
    assert blog_href in _nav_html(app_content, "Footer navigation")


def test_landing_page_redirects_authenticated_users_to_home(client):
    user = get_user_model().objects.create_user(
        username="landing-auth",
        email="landing-auth@example.com",
        password="strong-test-pass-123",
    )
    client.force_login(user)

    response = client.get(reverse("landing"))

    assert response.status_code == 302
    assert response["Location"] == reverse("home")


@override_settings(SITE_URL="https://testserver")
def test_robots_txt_allows_crawling_and_links_sitemap(client):
    response = client.get(reverse("robots_txt"), secure=True, HTTP_HOST="testserver")

    assert response.status_code == 200
    assert response.headers["Content-Type"] == "text/plain; charset=utf-8"
    assert response.content.decode() == (
        "User-agent: *\nAllow: /\nSitemap: https://testserver/sitemap.xml\n\n"
    )


def test_sitemap_response_does_not_set_noindex_header(client):
    response = client.get("/sitemap.xml", secure=True, HTTP_HOST="testserver")

    assert response.status_code == 200
    assert "X-Robots-Tag" not in response.headers


@pytest.mark.parametrize(
    ("path", "expected"),
    (
        ("/pricing/", "/pricing"),
        ("/privacy-policy/", "/privacy-policy"),
        ("/terms-of-service/", "/terms-of-service"),
        ("/use-cases/", "/use-cases"),
        ("/use-cases/personal-crm/", "/use-cases/personal-crm"),
        ("/alternatives/airtable/", "/alternatives/airtable"),
        ("/uses/", "/uses"),
    ),
)
def test_marketing_trailing_slash_routes_redirect_to_canonical_paths(client, path, expected):
    response = client.get(f"{path}?utm_source=test")

    assert response.status_code == 301
    assert response["Location"] == f"{expected}?utm_source=test"


def test_use_cases_index_lists_public_use_case_pages(client):
    response = client.get(reverse("use_cases"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Agent workflows that start as structured rows." in content
    assert reverse("use_case_detail", kwargs={"slug": "personal-crm"}) in content
    assert reverse("use_case_detail", kwargs={"slug": "agent-task-board"}) in content
    assert "product-inventory-catalog" in content
    assert reverse("docs_page", kwargs={"category": "api-reference", "page": "datasets"}) in content
    assert reverse("docs_page", kwargs={"category": "features", "page": "mcp"}) in content
    assert reverse("pricing") in content


def test_use_case_detail_page_shows_structured_example(client):
    response = client.get(reverse("use_case_detail", kwargs={"slug": "personal-crm"}))

    assert response.status_code == 200
    content = response.content.decode()
    assert "A CRM your agent can actually maintain." in content
    assert "people" in content
    assert "People dataset indexed by email or person_id." in content
    assert "Dataset context and semantic schema" in content
    assert "alex@example.com" in content
    assert reverse("docs_page", kwargs={"category": "features", "page": "mcp"}) in content
    assert reverse("docs_page", kwargs={"category": "api-reference", "page": "datasets"}) in content
    assert reverse("pricing") in content
    assert '"@type": "Article"' in content


def test_unknown_use_case_returns_404(client):
    response = client.get(reverse("use_case_detail", kwargs={"slug": "missing"}))

    assert response.status_code == 404


@override_settings(SITE_URL="https://testserver")
def test_database_mcp_server_playbook_has_required_links_and_schema(client):
    response = client.get(reverse("database_mcp_server_playbook"))

    assert response.status_code == 200
    content = response.content.decode()
    text = strip_tags(content)
    words = re.findall(r"\b[\w'-]+\b", text)

    assert "Database MCP server: when to use Rowset instead" in content
    assert len(words) >= 2500
    assert reverse("docs_page", kwargs={"category": "features", "page": "mcp"}) in content
    assert reverse("docs_page", kwargs={"category": "api-reference", "page": "datasets"}) in content
    assert reverse("docs_page", kwargs={"category": "features", "page": "agent-access"}) in content
    assert reverse("pricing") in content
    assert reverse("use_case_detail", kwargs={"slug": "personal-crm"}) in content
    assert reverse("use_case_detail", kwargs={"slug": "agent-task-board"}) in content
    assert reverse("use_case_detail", kwargs={"slug": "feedback-triage"}) in content
    assert "https://testserver/mcp/" in content
    assert '"@type": "Article"' in content
    assert '"@type": "BreadcrumbList"' in content


@override_settings(SITE_URL="https://testserver")
def test_airtable_alternative_has_required_links_and_faq_schema(client):
    response = client.get(reverse("airtable_alternative"))

    assert response.status_code == 200
    content = response.content.decode()
    text = strip_tags(content)
    words = re.findall(r"\b[\w'-]+\b", text)

    assert '<link rel="canonical" href="https://testserver/alternatives/airtable" />' in content
    assert "Airtable alternatives for AI-agent-managed datasets" in content
    assert len(words) >= 600
    assert "Airtable is still the better choice" in content
    assert reverse("pricing") in content
    assert reverse("account_signup") in content
    assert reverse("docs_page", kwargs={"category": "features", "page": "mcp"}) in content
    assert reverse("docs_page", kwargs={"category": "api-reference", "page": "datasets"}) in content
    assert reverse("docs_page", kwargs={"category": "features", "page": "agent-access"}) in content
    assert reverse("use_case_detail", kwargs={"slug": "agent-task-board"}) in content
    assert reverse("use_case_detail", kwargs={"slug": "feedback-triage"}) in content
    assert '"@type": "Article"' in content
    assert '"@type": "FAQPage"' in content
    assert '"@type": "BreadcrumbList"' in content


def test_schema_helpers_render_valid_homepage_json_ld(client):
    response = client.get(reverse("landing"))

    content = response.content.decode()
    start = content.index('<script type="application/ld+json">')
    end = content.index("</script>", start)
    payload = content[start:end].split(">", 1)[1].strip()
    schema = json.loads(payload)

    assert {entry["@type"] for entry in schema} == {"SoftwareApplication", "Organization"}
    organization = next(entry for entry in schema if entry["@type"] == "Organization")
    assert organization["url"].endswith("/")


def test_json_ld_escapes_script_breakout_sequences():
    payload = json_ld({"name": "</script><script>alert(1)</script>", "ampersand": "&"})

    assert "</script>" not in payload
    assert "\\u003c/script\\u003e" in payload
    assert "\\u0026" in payload


def test_build_absolute_static_url_adds_scheme_to_protocol_relative_static_url(settings):
    settings.STATIC_URL = "//cdn.example.test/static/"
    settings.SITE_URL = "https://testserver"
    settings.STORAGES = {
        **settings.STORAGES,
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }

    assert (
        build_absolute_static_url("vendors/images/logo.png")
        == "https://cdn.example.test/static/vendors/images/logo.png"
    )


def test_schema_helper_edge_cases_escape_and_omit_optional_fields():
    assert breadcrumb_list_schema(())["itemListElement"] == []
    assert faq_page_schema(())["mainEntity"] == []

    faq_schema = faq_page_schema((("Can agents use Rowset?", "Yes, through MCP or REST."),))
    assert faq_schema["mainEntity"][0]["acceptedAnswer"]["text"] == "Yes, through MCP or REST."

    schema = article_schema(
        headline='Agent "CRM" <guide>',
        description="Use <structured> rows safely.",
        path="/use-cases/personal-crm",
    )
    rendered = json_ld(schema)

    assert "datePublished" not in schema
    assert "dateModified" not in schema
    assert "\\u003cguide\\u003e" in rendered
    assert "\\u003cstructured\\u003e" in rendered


def test_use_case_article_schema_includes_main_entity(client):
    response = client.get(reverse("use_case_detail", kwargs={"slug": "personal-crm"}))

    content = response.content.decode()
    start = content.index('<script type="application/ld+json">')
    end = content.index("</script>", start)
    payload = content[start:end].split(">", 1)[1].strip()
    schema = json.loads(payload)

    assert schema["mainEntityOfPage"]["@id"].endswith("/use-cases/personal-crm")


def test_use_case_pages_reject_missing_page_copy(monkeypatch):
    page_copy = dict(page_use_cases.USE_CASE_PAGE_COPY)
    page_copy.pop("personal_crm")
    monkeypatch.setattr(page_use_cases, "USE_CASE_PAGE_COPY", page_copy)

    with pytest.raises(ValueError, match="personal_crm"):
        page_use_cases.validate_use_case_page_registry()


def test_use_case_pages_reject_unknown_feature_references(monkeypatch):
    invalid_use_case = RowsetUseCase(
        id="invalid_reference",
        title="Invalid reference",
        summary="Invalid registry fixture.",
        starter_shape=("Fixture only.",),
        rowset_features=("missing_capability",),
    )
    monkeypatch.setattr(
        page_use_cases,
        "ROWSET_USE_CASES",
        page_use_cases.ROWSET_USE_CASES + (invalid_use_case,),
    )
    monkeypatch.setattr(
        page_use_cases,
        "USE_CASE_PAGE_COPY",
        {
            **page_use_cases.USE_CASE_PAGE_COPY,
            "invalid_reference": replace(
                page_use_cases.USE_CASE_PAGE_COPY["personal_crm"],
                slug="invalid-reference",
            ),
        },
    )

    with pytest.raises(ValueError, match="invalid_reference: missing_capability"):
        page_use_cases.validate_use_case_page_registry()


def test_use_case_pages_reject_duplicate_capability_ids(monkeypatch):
    monkeypatch.setattr(
        page_use_cases,
        "ROWSET_CAPABILITIES",
        page_use_cases.ROWSET_CAPABILITIES + (page_use_cases.ROWSET_CAPABILITIES[0],),
    )

    with pytest.raises(ValueError, match="duplicate IDs"):
        page_use_cases.validate_use_case_page_registry()


def test_use_case_pages_reject_duplicate_public_slugs(monkeypatch):
    page_copy = dict(page_use_cases.USE_CASE_PAGE_COPY)
    page_copy["task_board"] = replace(
        page_copy["task_board"],
        slug=page_copy["personal_crm"].slug,
    )
    monkeypatch.setattr(page_use_cases, "USE_CASE_PAGE_COPY", page_copy)

    with pytest.raises(ValueError, match="duplicate public slugs: personal-crm"):
        page_use_cases.validate_use_case_page_registry()


@pytest.mark.parametrize(
    ("bad_slug", "expected_slug"),
    (
        (None, "<empty>"),
        ("", "<empty>"),
        ("personal crm", "personal crm"),
        ("personal/crm", "personal/crm"),
    ),
)
def test_use_case_pages_reject_unrouteable_public_slugs(bad_slug, expected_slug, monkeypatch):
    page_copy = dict(page_use_cases.USE_CASE_PAGE_COPY)
    page_copy["personal_crm"] = replace(
        page_copy["personal_crm"],
        slug=bad_slug,
    )
    monkeypatch.setattr(page_use_cases, "USE_CASE_PAGE_COPY", page_copy)

    errors = page_use_cases.get_use_case_page_registry_errors()

    assert (
        f"USE_CASE_PAGE_COPY contains invalid public slugs: personal_crm: {expected_slug}"
    ) in errors


@pytest.mark.parametrize("bad_page_copy", (None, {"slug": "personal-crm"}))
def test_use_case_pages_reject_malformed_page_copy_values(bad_page_copy, monkeypatch):
    page_copy = dict(page_use_cases.USE_CASE_PAGE_COPY)
    page_copy["personal_crm"] = bad_page_copy
    monkeypatch.setattr(page_use_cases, "USE_CASE_PAGE_COPY", page_copy)

    errors = page_use_cases.get_use_case_page_registry_errors()
    check_errors = check_use_case_page_registry(None)

    assert (
        "USE_CASE_PAGE_COPY contains invalid public slugs: personal_crm: <invalid page copy>"
    ) in errors
    assert check_errors[0].id == "pages.E001"
    assert "<invalid page copy>" in check_errors[0].msg
    with pytest.raises(ImproperlyConfigured, match="<invalid page copy>"):
        page_use_cases.get_use_case_pages()


def test_use_case_page_registry_check_reports_structured_errors(monkeypatch):
    page_copy = dict(page_use_cases.USE_CASE_PAGE_COPY)
    page_copy.pop("personal_crm")
    monkeypatch.setattr(page_use_cases, "USE_CASE_PAGE_COPY", page_copy)

    errors = check_use_case_page_registry(None)

    assert errors[0].id == "pages.E001"
    assert "personal_crm" in errors[0].msg


def test_use_case_pages_fail_controlled_when_registry_is_invalid(monkeypatch):
    page_copy = dict(page_use_cases.USE_CASE_PAGE_COPY)
    page_copy.pop("personal_crm")
    monkeypatch.setattr(page_use_cases, "USE_CASE_PAGE_COPY", page_copy)

    with pytest.raises(ImproperlyConfigured, match="personal_crm"):
        page_use_cases.get_use_case_pages()


def test_settings_shows_email_confirmation_and_passkey_setup(client):
    user = get_user_model().objects.create_user(
        username="settingsuser",
        email="settingsuser@example.com",
        password="strong-test-pass-123",
    )
    EmailAddress.objects.update_or_create(
        user=user,
        email=user.email,
        defaults={"primary": True, "verified": False},
    )
    client.force_login(user)

    response = client.get(reverse("settings"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Your email is not yet confirmed" in content
    assert "Add passkey" in content
    assert reverse("mfa_add_webauthn") in content


def test_settings_shows_passkey_manage_link_when_passkey_exists(client):
    user = get_user_model().objects.create_user(
        username="passkeyuser",
        email="passkeyuser@example.com",
        password="strong-test-pass-123",
    )
    EmailAddress.objects.update_or_create(
        user=user,
        email=user.email,
        defaults={"primary": True, "verified": True},
    )
    Authenticator.objects.create(
        user=user,
        type=Authenticator.Type.WEBAUTHN,
        data={"name": "Test passkey"},
    )
    client.force_login(user)

    response = client.get(reverse("settings"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "You have 1 passkey set up." in content
    assert "Manage passkeys" in content
    assert reverse("mfa_list_webauthn") in content


def test_mfa_index_uses_rowset_styling(client):
    user = get_user_model().objects.create_user(
        username="mfauser",
        email="mfauser@example.com",
        password="strong-test-pass-123",
    )
    EmailAddress.objects.update_or_create(
        user=user,
        email=user.email,
        defaults={"primary": True, "verified": True},
    )
    client.force_login(user)

    response = client.get(reverse("mfa_index"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Passkeys" in content
    assert "Add passkey" in content
    assert "Menu:" not in content
    assert "Rowset Logo" in content


def test_webauthn_add_page_loads_styled_form_and_scripts(client):
    user = get_user_model().objects.create_user(
        username="addpasskeyuser",
        email="addpasskeyuser@example.com",
        password="strong-test-pass-123",
    )
    EmailAddress.objects.update_or_create(
        user=user,
        email=user.email,
        defaults={"primary": True, "verified": True},
    )
    assert client.login(username="addpasskeyuser", password="strong-test-pass-123")
    session = client.session
    session["account_authentication_methods"] = [
        {"method": "password", "at": time.time(), "username": "addpasskeyuser"}
    ]
    session.save()

    response = client.get(reverse("mfa_add_webauthn"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Add passkey" in content
    assert 'id="mfa_webauthn_add"' in content
    assert "allauth.webauthn.forms.addForm" in content
    assert "mfa/js/webauthn.js" in content
    assert "Menu:" not in content


def test_reauthenticate_page_uses_rowset_styling(client):
    user = get_user_model().objects.create_user(
        username="reauthuser",
        email="reauthuser@example.com",
        password="strong-test-pass-123",
    )
    client.force_login(user)

    response = client.get(reverse("account_reauthenticate"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "<title>Confirm access · Rowset</title>" in content
    assert "Confirm access" in content
    assert "Rowset Logo" in content
    assert "Menu:" not in content


def test_mailgun_sender_defaults_to_rasul_lvtd():
    assert settings.DEFAULT_FROM_EMAIL == "Rasul Kireev <rasul@lvtd.dev>"
    assert settings.SERVER_EMAIL == "Rowset Errors <rasul@lvtd.dev>"
    assert settings.ANYMAIL["MAILGUN_SENDER_DOMAIN"] == "mg.lvtd.dev"


def test_account_email_page_uses_rowset_styling(client):
    user = get_user_model().objects.create_user(
        username="emailpageuser",
        email="emailpageuser@example.com",
        password="strong-test-pass-123",
    )
    EmailAddress.objects.update_or_create(
        user=user,
        email=user.email,
        defaults={"primary": True, "verified": False},
    )
    client.force_login(user)

    response = client.get(reverse("account_email"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Email addresses" in content
    assert "Re-send verification" in content
    assert "Rowset Logo" in content
    assert "Menu:" not in content


def test_settings_resend_confirmation_uses_hmac_link(client, monkeypatch):
    sent_confirmations = []

    def fake_send_confirmation_mail(self, request, emailconfirmation, signup):
        sent_confirmations.append((emailconfirmation, signup))

    monkeypatch.setattr(
        "rowset.adapters.CustomAccountAdapter.send_confirmation_mail",
        fake_send_confirmation_mail,
    )
    user = get_user_model().objects.create_user(
        username="resenduser",
        email="resenduser@example.com",
        password="strong-test-pass-123",
    )
    EmailAddress.objects.update_or_create(
        user=user,
        email=user.email,
        defaults={"primary": True, "verified": False},
    )
    client.force_login(user)

    response = client.post(reverse("resend_confirmation"))

    assert response.status_code == 302
    assert response["Location"] == reverse("settings")
    assert len(list(get_messages(response.wsgi_request))) == 1
    assert len(sent_confirmations) == 1
    emailconfirmation, signup = sent_confirmations[0]
    assert signup is False
    assert emailconfirmation.key.count(":") == 2
    assert not EmailAddress.objects.get(user=user, email=user.email).verified


def test_settings_resend_confirmation_link_confirms_email(client, monkeypatch):
    sent_confirmations = []

    def fake_send_confirmation_mail(self, request, emailconfirmation, signup):
        sent_confirmations.append(emailconfirmation)

    monkeypatch.setattr(
        "rowset.adapters.CustomAccountAdapter.send_confirmation_mail",
        fake_send_confirmation_mail,
    )
    user = get_user_model().objects.create_user(
        username="confirmresenduser",
        email="confirmresenduser@example.com",
        password="strong-test-pass-123",
    )
    EmailAddress.objects.update_or_create(
        user=user,
        email=user.email,
        defaults={"primary": True, "verified": False},
    )
    client.force_login(user)

    response = client.post(reverse("resend_confirmation"))

    assert response.status_code == 302
    assert len(sent_confirmations) == 1
    confirm_path = reverse("account_confirm_email", args=[sent_confirmations[0].key])
    confirm_response = client.post(confirm_path)

    assert confirm_response.status_code == 302
    assert EmailAddress.objects.get(user=user, email=user.email).verified is True


def test_dashboard_suppresses_verification_reminder_without_email_address(client):
    user = get_user_model().objects.create_user(
        username="admincreated",
        email="admincreated@example.com",
        password="strong-test-pass-123",
    )
    client.force_login(user)

    response = client.get(reverse("home"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Your email is not yet confirmed" not in content
    assert "Connect your AI agent to Rowset" in content
