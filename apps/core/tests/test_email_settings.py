from types import SimpleNamespace

import pytest
from django.conf import settings

from rowset.adapters import CustomAccountAdapter


def test_transactional_sender_uses_rowset_domain():
    assert settings.DEFAULT_FROM_EMAIL == "Rowset <rasul@rowset.app>"
    assert settings.SERVER_EMAIL == "Rowset Errors <rasul@rowset.app>"
    assert settings.ANYMAIL["MAILGUN_SENDER_DOMAIN"] == "mg.rowset.app"


@pytest.mark.parametrize(
    "template",
    [
        "email_confirmation_signup",
        "email_confirmation",
        "password_reset_key",
        "account_already_exists",
    ],
)
def test_account_emails_share_configured_sender(template, monkeypatch):
    # Rendering service is external; test the real account adapter and sender wiring.
    monkeypatch.setattr("mjml.templatetags.mjml.mjml_render", lambda source: source)
    message = CustomAccountAdapter().render_mail(
        f"account/email/{template}",
        "recipient@example.com",
        {
            "site_name": "Rowset",
            "user": SimpleNamespace(username="recipient", email="recipient@example.com"),
            "activate_url": "https://rowset.app/accounts/confirm-email/test/",
            "password_reset_url": "https://rowset.app/accounts/password/reset/key/test/",
            "email": "recipient@example.com",
        },
    )
    assert message.from_email == settings.DEFAULT_FROM_EMAIL
    assert message.to == ["recipient@example.com"]
