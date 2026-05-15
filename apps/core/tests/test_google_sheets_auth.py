from urllib.parse import parse_qs, urlsplit

import pytest
from allauth.socialaccount.models import SocialAccount
from django.urls import reverse

from apps.core.signals import _mark_google_sheets_connected
from apps.datasets.google_sheets import (
    GOOGLE_SHEETS_CONNECT_SESSION_KEY,
    GOOGLE_SHEETS_CONNECTED_EXTRA_DATA_KEY,
    SHEETS_SCOPE,
)

pytestmark = pytest.mark.django_db


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
    assert query["next"] == [reverse("settings")]
    assert auth_params["access_type"] == ["offline"]
    assert auth_params["include_granted_scopes"] == ["true"]
    assert auth_params["prompt"] == ["consent"]
    assert client.session[GOOGLE_SHEETS_CONNECT_SESSION_KEY] is True


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
