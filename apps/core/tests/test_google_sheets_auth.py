from urllib.parse import parse_qs, urlsplit

import pytest
from allauth.socialaccount.models import SocialAccount
from django.conf import settings
from django.template.loader import render_to_string
from django.test import override_settings
from django.urls import reverse

from apps.core.signals import _mark_google_sheets_connected
from apps.datasets.google_sheets import (
    GOOGLE_SHEETS_CONNECT_SESSION_KEY,
    GOOGLE_SHEETS_CONNECTED_EXTRA_DATA_KEY,
    SHEETS_SCOPE,
)

pytestmark = pytest.mark.django_db

MINIMAL_TEMPLATE_SETTINGS = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [str(settings.BASE_DIR.joinpath("frontend", "templates"))],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]


def test_connect_google_sheets_requests_sheets_scope_only_when_clicked(client, django_user_model):
    user = django_user_model.objects.create_user(
        username="sheets-auth",
        email="sheets-auth@example.com",
        password="password123",
    )
    client.force_login(user)

    response = client.post(reverse("connect_google_sheets"))

    assert response.status_code == 302
    redirect = urlsplit(response["Location"])
    query = parse_qs(redirect.query)
    auth_params = parse_qs(query["auth_params"][0])
    assert redirect.path == reverse("google_login")
    assert query["process"] == ["connect"]
    assert query["scope"] == ["https://www.googleapis.com/auth/spreadsheets"]
    assert query["next"] == [reverse("home")]
    assert auth_params["access_type"] == ["offline"]
    assert auth_params["include_granted_scopes"] == ["true"]
    assert auth_params["prompt"] == ["consent"]
    assert client.session[GOOGLE_SHEETS_CONNECT_SESSION_KEY] is True


@override_settings(
    TEMPLATES=MINIMAL_TEMPLATE_SETTINGS,
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
)
def test_google_sheets_connect_confirmation_uses_filebridge_template(rf, django_user_model):
    request = rf.get(
        reverse("google_login"),
        {
            "process": "connect",
            "scope": SHEETS_SCOPE,
            "next": reverse("home"),
        },
    )
    request.user = django_user_model.objects.create_user(
        username="sheets-template",
        email="sheets-template@example.com",
        password="password123",
    )
    provider = type("Provider", (), {"id": "google", "name": "Google"})()

    html = render_to_string(
        "socialaccount/login.html",
        {"process": "connect", "provider": provider, "next": reverse("home")},
        request=request,
    )

    assert "Connect Google Sheets" in html
    assert "Continue to Google Sheets consent" in html
    assert "fb-card" in html
    assert "google-sheets-logo.svg" in html
    assert f'href="{reverse("home")}"' in html
    assert "Menu:" not in html


def test_google_sheets_connect_signal_marks_account(rf, django_user_model):
    user = django_user_model.objects.create_user(
        username="sheets-signal",
        email="sheets-signal@example.com",
        password="password123",
    )
    account = SocialAccount.objects.create(user=user, provider="google", uid="google-1")
    request = rf.get("/settings")
    request.session = {GOOGLE_SHEETS_CONNECT_SESSION_KEY: True}
    sociallogin = type("SocialLogin", (), {"account": account, "state": {"scope": SHEETS_SCOPE}})()

    _mark_google_sheets_connected(request, sociallogin)

    account.refresh_from_db()
    assert account.extra_data[GOOGLE_SHEETS_CONNECTED_EXTRA_DATA_KEY] is True
    assert GOOGLE_SHEETS_CONNECT_SESSION_KEY not in request.session


def test_google_sheets_connect_signal_marks_account_when_allauth_drops_scope(
    rf,
    django_user_model,
):
    user = django_user_model.objects.create_user(
        username="sheets-session-signal",
        email="sheets-session-signal@example.com",
        password="password123",
    )
    account = SocialAccount.objects.create(user=user, provider="google", uid="google-1")
    request = rf.get("/settings")
    request.session = {GOOGLE_SHEETS_CONNECT_SESSION_KEY: True}
    sociallogin = type(
        "SocialLogin",
        (),
        {"account": account, "state": {"process": "connect", "next": reverse("home")}},
    )()

    _mark_google_sheets_connected(request, sociallogin)

    account.refresh_from_db()
    assert account.extra_data[GOOGLE_SHEETS_CONNECTED_EXTRA_DATA_KEY] is True
    assert GOOGLE_SHEETS_CONNECT_SESSION_KEY not in request.session


def test_google_connect_does_not_mark_sheets_connected_for_non_sheets_scope(
    rf,
    django_user_model,
):
    user = django_user_model.objects.create_user(
        username="google-non-sheets-signal",
        email="google-non-sheets-signal@example.com",
        password="password123",
    )
    account = SocialAccount.objects.create(user=user, provider="google", uid="google-1")
    request = rf.get("/settings")
    request.session = {GOOGLE_SHEETS_CONNECT_SESSION_KEY: True}
    sociallogin = type(
        "SocialLogin",
        (),
        {"account": account, "state": {"process": "connect", "scope": "profile email"}},
    )()

    _mark_google_sheets_connected(request, sociallogin)

    account.refresh_from_db()
    assert GOOGLE_SHEETS_CONNECTED_EXTRA_DATA_KEY not in account.extra_data
    assert GOOGLE_SHEETS_CONNECT_SESSION_KEY not in request.session


def test_basic_google_login_does_not_mark_sheets_connected_with_stale_session(
    rf,
    django_user_model,
):
    user = django_user_model.objects.create_user(
        username="basic-google",
        email="basic-google@example.com",
        password="password123",
    )
    account = SocialAccount.objects.create(user=user, provider="google", uid="google-1")
    request = rf.get("/settings")
    request.session = {GOOGLE_SHEETS_CONNECT_SESSION_KEY: True}
    sociallogin = type(
        "SocialLogin",
        (),
        {"account": account, "state": {"scope": "profile email"}},
    )()

    _mark_google_sheets_connected(request, sociallogin)

    account.refresh_from_db()
    assert GOOGLE_SHEETS_CONNECTED_EXTRA_DATA_KEY not in account.extra_data
    assert GOOGLE_SHEETS_CONNECT_SESSION_KEY not in request.session


def test_google_sheets_scope_check_handles_missing_state(rf, django_user_model):
    user = django_user_model.objects.create_user(
        username="missing-state",
        email="missing-state@example.com",
        password="password123",
    )
    account = SocialAccount.objects.create(user=user, provider="google", uid="google-1")
    request = rf.get("/settings")
    request.session = {GOOGLE_SHEETS_CONNECT_SESSION_KEY: True}
    sociallogin = type("SocialLogin", (), {"account": account, "state": None})()

    _mark_google_sheets_connected(request, sociallogin)

    account.refresh_from_db()
    assert GOOGLE_SHEETS_CONNECTED_EXTRA_DATA_KEY not in account.extra_data
    assert GOOGLE_SHEETS_CONNECT_SESSION_KEY not in request.session
