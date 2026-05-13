import hashlib
import hmac
from types import SimpleNamespace

from django.test import RequestFactory, override_settings

from apps.core.context_processors import chatwoot_config


class DummyUser:
    is_authenticated = True
    id = 42
    email = "ada@example.com"

    def get_full_name(self):
        return "Ada Lovelace"


@override_settings(CHATWOOT_WEBSITE_TOKEN="")
def test_chatwoot_context_disabled_without_token():
    request = RequestFactory().get("/")
    request.user = SimpleNamespace(is_authenticated=False)

    assert chatwoot_config(request) == {"chatwoot": {"enabled": False}}


@override_settings(
    CHATWOOT_BASE_URL="https://chatwoot.cap.gregagi.com/",
    CHATWOOT_WEBSITE_TOKEN="website-token",
    CHATWOOT_HMAC_SECRET="",
)
def test_chatwoot_context_enables_anonymous_widget():
    request = RequestFactory().get("/")
    request.user = SimpleNamespace(is_authenticated=False)

    assert chatwoot_config(request) == {
        "chatwoot": {
            "enabled": True,
            "base_url": "https://chatwoot.cap.gregagi.com",
            "website_token": "website-token",
            "user": None,
        }
    }


@override_settings(
    CHATWOOT_BASE_URL="https://chatwoot.cap.gregagi.com",
    CHATWOOT_WEBSITE_TOKEN="website-token",
    CHATWOOT_HMAC_SECRET="",
)
def test_chatwoot_context_identifies_authenticated_user_without_hmac():
    request = RequestFactory().get("/")
    request.user = DummyUser()

    assert chatwoot_config(request)["chatwoot"]["user"] == {
        "identifier": "42",
        "email": "ada@example.com",
        "name": "Ada Lovelace",
    }


@override_settings(
    CHATWOOT_BASE_URL="https://chatwoot.cap.gregagi.com",
    CHATWOOT_WEBSITE_TOKEN="website-token",
    CHATWOOT_HMAC_SECRET="secret",
)
def test_chatwoot_context_identifies_authenticated_user_with_hmac():
    request = RequestFactory().get("/")
    request.user = DummyUser()

    expected_hash = hmac.new(b"secret", b"42", hashlib.sha256).hexdigest()

    assert chatwoot_config(request)["chatwoot"]["user"] == {
        "identifier": "42",
        "email": "ada@example.com",
        "name": "Ada Lovelace",
        "identifier_hash": expected_hash,
    }
