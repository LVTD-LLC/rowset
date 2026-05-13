import pytest
from allauth.account.models import EmailAddress
from allauth.mfa.models import Authenticator
from django.contrib.auth import get_user_model
from django.urls import reverse


pytestmark = pytest.mark.django_db


def test_login_page_shows_passkey_option(client):
    response = client.get(reverse("account_login"))
    assert response.status_code == 200

    content = response.content.decode()
    assert "Sign in with a passkey" in content
    assert 'id="mfa_login"' in content


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
        "filebridge.adapters.CustomAccountAdapter.send_confirmation_mail",
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
    content = response.content.decode()
    assert "Your email is not yet confirmed" not in content
    assert "Welcome to FileBridge" in content


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
    assert "Welcome to FileBridge" in content
