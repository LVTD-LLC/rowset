from types import SimpleNamespace

import pytest
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, override_settings
from django.urls import reverse

from apps.core.context_processors import posthog_api_key
from apps.datasets.tests.factories import create_dataset, create_dataset_row


def _request(*, route: str, url_name: str):
    request = RequestFactory().get(f"/{route}")
    request.user = AnonymousUser()
    request.resolver_match = SimpleNamespace(route=route, url_name=url_name)
    return request


@override_settings(POSTHOG_API_KEY="phc_test")
def test_posthog_context_enables_normalized_marketing_route():
    context = posthog_api_key(_request(route="docs/<slug:slug>", url_name="docs_page"))

    assert context["posthog_pageview_enabled"] is True
    assert context["posthog_pageview_route"] == "/docs/:slug"
    assert context["posthog_content_group"] == "docs"


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
    request = _request(
        route="share/datasets/<uuid:public_key>/rows/<int:row_id>/",
        url_name="public_dataset_row_detail",
    )
    request._rowset_public_access_state = "available"
    request._rowset_public_content_id = "pd_v1_0123456789abcdef01234567"
    request._rowset_public_content_surface = "row_detail"

    context = posthog_api_key(request)

    assert context["posthog_pageview_enabled"] is True
    assert context["posthog_pageview_route"] == "/share/datasets/:public_key/rows/:row_id/"
    assert context["posthog_content_group"] == "public_dataset"
    assert context["posthog_content_id"] == "pd_v1_0123456789abcdef01234567"
    assert context["posthog_content_surface"] == "row_detail"


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
    assert f'data-posthog-content-id="{response.context["posthog_content_id"]}"' in content
    assert 'data-posthog-content-surface="preview"' in content
    assert response.context["posthog_content_id"].startswith("pd_v1_")


@pytest.mark.django_db
@override_settings(POSTHOG_API_KEY="phc_test")
def test_locked_public_dataset_does_not_enable_pageview_capture(client, profile):
    dataset = create_dataset(profile, public_enabled=True, public_password_hash="locked")

    response = client.get(dataset.get_public_url())
    content = response.content.decode()

    assert response.status_code == 200
    assert response.context["posthog_pageview_enabled"] is False
    assert "data-posthog-content-id" not in content
    assert "data-posthog-content-surface" not in content


@pytest.mark.django_db
@override_settings(POSTHOG_API_KEY="phc_test")
def test_public_row_detail_reuses_dataset_identity_without_row_identity(client, profile):
    dataset = create_dataset(profile, public_enabled=True)
    row = create_dataset_row(dataset, data={"name": "Private row value"})

    response = client.get(reverse("public_dataset_row_detail", args=[dataset.public_key, row.id]))
    content = response.content.decode()

    assert response.status_code == 200
    assert response.context["posthog_content_surface"] == "row_detail"
    assert f'data-posthog-content-id="{response.context["posthog_content_id"]}"' in content
    assert 'data-posthog-content-surface="row_detail"' in content
    assert f'data-posthog-row-id="{row.id}"' not in content
