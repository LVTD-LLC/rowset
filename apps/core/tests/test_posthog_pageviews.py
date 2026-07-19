from types import SimpleNamespace

import pytest
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, override_settings

from apps.core.context_processors import posthog_api_key
from apps.datasets.tests.factories import create_dataset


def _request(*, route: str, url_name: str, user_agent: str = "Mozilla/5.0 Chrome/126.0"):
    request = RequestFactory().get(f"/{route}", HTTP_USER_AGENT=user_agent)
    request.user = AnonymousUser()
    request.resolver_match = SimpleNamespace(route=route, url_name=url_name)
    return request


@override_settings(POSTHOG_API_KEY="phc_test")
def test_posthog_context_enables_normalized_marketing_route():
    context = posthog_api_key(_request(route="docs/<slug:slug>", url_name="docs_page"))

    assert context["posthog_pageview_enabled"] is True
    assert context["posthog_pageview_route"] == "/docs/:slug"
    assert context["posthog_content_group"] == "docs"
    assert context["posthog_traffic_category"] == "human"


@override_settings(POSTHOG_API_KEY="phc_test")
def test_posthog_context_uses_server_derived_ai_agent_category():
    context = posthog_api_key(
        _request(route="pricing", url_name="pricing", user_agent="ChatGPT-User/1.0")
    )

    assert context["posthog_traffic_category"] == "ai_agent"


@override_settings(POSTHOG_API_KEY="phc_test")
def test_posthog_context_reuses_request_middleware_traffic_category():
    request = _request(route="pricing", url_name="pricing")
    request.traffic_category = "crawler"

    context = posthog_api_key(request)

    assert context["posthog_traffic_category"] == "crawler"


@override_settings(POSTHOG_API_KEY="phc_test")
def test_posthog_context_normalizes_sensitive_auth_route_parameters():
    context = posthog_api_key(
        _request(
            route="accounts/password/reset/key/<uidb36>/<key>/",
            url_name="account_reset_password_from_key",
        )
    )

    assert context["posthog_pageview_enabled"] is True
    assert context["posthog_pageview_route"] == "/accounts/password/reset/key/:uidb36/:key/"
    assert context["posthog_content_group"] == "auth"


@override_settings(POSTHOG_API_KEY="phc_test")
def test_posthog_context_enables_public_dataset_without_exposing_identifiers():
    context = posthog_api_key(
        _request(
            route="share/datasets/<uuid:public_key>/rows/<int:row_id>/",
            url_name="public_dataset_row_detail",
        )
    )

    assert context["posthog_pageview_enabled"] is True
    assert context["posthog_pageview_route"] == "/share/datasets/:public_key/rows/:row_id/"
    assert context["posthog_content_group"] == "public_dataset"


@override_settings(POSTHOG_API_KEY="phc_test")
def test_posthog_context_excludes_private_app_routes():
    context = posthog_api_key(
        _request(route="datasets/<uuid:dataset_key>/", url_name="dataset_detail")
    )

    assert context["posthog_pageview_enabled"] is False
    assert context["posthog_pageview_route"] == ""
    assert context["posthog_content_group"] == ""


@pytest.mark.django_db
@override_settings(POSTHOG_API_KEY="phc_test")
def test_public_dataset_page_wires_normalized_pageview_context(client, profile):
    dataset = create_dataset(profile, public_enabled=True)

    response = client.get(dataset.get_public_url())
    content = response.content.decode()

    assert response.status_code == 200
    assert 'src="/static/js/posthog-pageviews.js"' in content
    assert 'data-posthog-pageview-enabled="true"' in content
    assert 'data-posthog-route="/share/datasets/:public_key/"' in content
    assert 'data-posthog-content-group="public_dataset"' in content
    assert 'data-posthog-traffic-category="unknown_automation"' in content
