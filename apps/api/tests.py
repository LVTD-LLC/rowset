import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from django.db import OperationalError
from django.http import HttpRequest
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.utils import timezone

from apps.api.views import (
    delete_internal_blog_post,
    get_internal_blog_post,
    get_user_info,
    list_archived_datasets,
    list_datasets,
    list_internal_blog_posts,
    list_projects,
    patch_internal_blog_post,
    publish_internal_blog_post,
    review_internal_blog_post,
    submit_blog_post,
    update_internal_blog_post,
)
from apps.blog.choices import BlogPostStatus
from apps.core.analytics import ROWSET_GET_USER_INFO_SUCCEEDED
from apps.core.choices import AgentApiKeyAccessLevel
from apps.core.models import Feedback
from apps.datasets import models as dataset_models
from apps.datasets.choices import DatasetColumnType, DatasetStatus
from apps.datasets.embeddings import EmbeddingResult
from apps.datasets.models import Dataset, DatasetRow, Project
from apps.datasets.vector_search import DatasetRowVectorSearchHit


def test_openapi_dataset_asset_thumbnail_url_is_required_string(client):
    response = client.get("/api/openapi.json")

    assert response.status_code == 200
    asset_schema = response.json()["components"]["schemas"]["DatasetAssetOut"]
    assert "thumbnail_url" in asset_schema["required"]
    assert asset_schema["properties"]["thumbnail_url"] == {
        "title": "Thumbnail Url",
        "type": "string",
    }


def test_capabilities_endpoint_supports_current_and_legacy_api_prefixes(client):
    current_response = client.get("/api/capabilities")
    legacy_response = client.get("/api/v1/capabilities", follow=True)
    legacy_root_response = client.get("/api/v1")

    assert current_response.status_code == 200
    assert legacy_response.status_code == 200
    assert legacy_root_response.status_code == 308
    assert legacy_root_response["Location"] == "/api/"
    assert current_response.json()["product"] == "Rowset"
    assert legacy_response.json()["product"] == "Rowset"


def test_row_contracts_normalize_row_data_for_declared_headers():
    from apps.api.row_contracts import normalize_row_data_for_headers

    payload = normalize_row_data_for_headers(
        {"name": "Ada", "score": 42, "empty": None, "ignored": "value"},
        ["name", "score", "empty", "missing"],
    )

    assert payload == {
        "name": "Ada",
        "score": "42",
        "empty": "",
        "missing": "",
    }


def test_row_contracts_normalize_row_patch_ignores_unknown_headers():
    from apps.api.row_contracts import normalize_row_patch_for_headers

    payload = normalize_row_patch_for_headers(
        {"name": "Ada", "score": 42, "unknown": "value"},
        ["name", "score"],
    )

    assert payload == {"name": "Ada", "score": "42"}


def test_row_contracts_normalize_search_filters_and_operators():
    from apps.api.row_contracts import (
        normalize_search_filter_operators,
        normalize_search_filters,
    )

    filters = normalize_search_filters({" status ": " Ready ", "blank": " ", "none": None})
    operators = normalize_search_filter_operators(
        {"status": " IS ", "missing": "contains"},
        filters,
    )

    assert filters == {"status": "Ready"}
    assert operators == {"status": "is"}


def test_row_contracts_reject_blank_search_filter_headers():
    from apps.api.row_contracts import normalize_search_filters

    with pytest.raises(ValueError, match="Search filter headers must be non-empty"):
        normalize_search_filters({" ": "Ready"})


def test_row_contracts_reject_blank_search_filter_operator_headers():
    from apps.api.row_contracts import normalize_search_filter_operators

    with pytest.raises(ValueError, match="Search filter operator headers must be non-empty"):
        normalize_search_filter_operators({" ": "is"}, {"status": "Ready"})


def test_dataset_row_write_schemas_accept_json_cell_values():
    from apps.api.schemas import DatasetRowIn, DatasetRowPatchIn

    payload = {"data": {"name": "Ada", "score": 42, "empty": None, "active": True}}

    assert DatasetRowIn.model_validate(payload).model_dump() == payload
    assert DatasetRowPatchIn.model_validate(payload).model_dump() == payload


@pytest.mark.django_db
@override_settings(
    DEFAULT_FROM_EMAIL="feedback@rowset.example",
    SITE_URL="https://rowset.example",
)
def test_submit_feedback_api_creates_feedback_dataset_row(client, django_user_model):
    user = django_user_model.objects.create_user(
        username="feedback-api-user",
        email="feedback-api-user@example.com",
        password="password123",
    )
    client.force_login(user)

    response = client.post(
        "/api/submit-feedback",
        data=json.dumps({"feedback": "API feedback", "page": "/settings/"}),
        content_type="application/json",
    )

    feedback = Feedback.objects.get()
    dataset = Dataset.objects.get(name="Feedback")
    row = dataset.rows.get(index_value=str(feedback.id))
    expected_row_url = f"https://rowset.example/datasets/{dataset.key}/rows/{row.id}/"

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "message": "Feedback submitted successfully",
        "row_url": expected_row_url,
    }
    assert row.data["context"] == ""
    assert row.data["submitted_via"] == "browser"
    assert row.data["feedback"] == "API feedback"
    assert feedback.metadata == {"rowset_row_url": expected_row_url}


def test_legacy_v1_api_prefix_serves_dataset_endpoints(client):
    profile = SimpleNamespace(id=11)
    payload = {
        "count": 0,
        "total_count": 0,
        "limit": 100,
        "offset": 0,
        "has_more": False,
        "datasets": [],
    }

    with (
        patch("apps.api.auth.resolve_api_key_profile", return_value=(profile, None)),
        patch("apps.api.views.search_profile_datasets", return_value=payload),
    ):
        response = client.get(
            "/api/v1/datasets",
            follow=True,
            HTTP_AUTHORIZATION="Bearer test-key",
        )

    assert response.status_code == 200
    assert response.json()["count"] == 0


def test_unknown_api_paths_return_json_without_rendering_landing_context(client, monkeypatch):
    from apps.pages.models import ReferrerBanner

    def fail_if_queried(*args, **kwargs):
        raise AssertionError("API 404 responses must not render landing-page context")

    monkeypatch.setattr(ReferrerBanner.objects, "get", fail_if_queried)

    current_response = client.get("/api/missing-endpoint/")
    legacy_response = client.get("/api/v1/missing-endpoint/", follow=True)
    trailing_slash_response = client.get("/api/v1/datasets/", follow=True)

    assert current_response.status_code == 404
    assert legacy_response.status_code == 404
    assert trailing_slash_response.status_code == 401
    assert current_response["Content-Type"] == "application/json"
    assert legacy_response["Content-Type"] == "application/json"
    assert trailing_slash_response["Content-Type"].startswith("application/json")
    assert current_response.json() == {"detail": "Not Found"}
    assert legacy_response.json() == {"detail": "Not Found"}
    assert trailing_slash_response.json() == {"detail": "Unauthorized"}


def test_referrer_banner_ignores_database_connection_errors(monkeypatch):
    from apps.pages.context_processors import referrer_banner
    from apps.pages.models import ReferrerBanner

    def raise_database_error(*args, **kwargs):
        raise OperationalError("the connection is closed")

    monkeypatch.setattr(ReferrerBanner.objects, "get", raise_database_error)

    request = RequestFactory().get("/missing-page/")

    assert referrer_banner(request) == {}


def test_referrer_banner_ignores_database_errors_in_multiple_banner_fallback(monkeypatch):
    from apps.pages.context_processors import referrer_banner
    from apps.pages.models import ReferrerBanner

    def raise_multiple_objects(*args, **kwargs):
        raise ReferrerBanner.MultipleObjectsReturned

    def raise_database_error(*args, **kwargs):
        raise OperationalError("the connection is closed")

    monkeypatch.setattr(ReferrerBanner.objects, "get", raise_multiple_objects)
    monkeypatch.setattr(ReferrerBanner.objects, "filter", raise_database_error)

    request = RequestFactory().get("/missing-page/")

    assert referrer_banner(request) == {}


class BlogPostApiTests(SimpleTestCase):
    @staticmethod
    def _request() -> HttpRequest:
        request = HttpRequest()
        request.auth = SimpleNamespace(user=SimpleNamespace(is_superuser=True))
        return request

    @staticmethod
    def _post_data(**overrides):
        data = {
            "title": "Hello",
            "description": "Desc",
            "slug": "hello",
            "tags": "django",
            "content": "Body",
            "status": BlogPostStatus.DRAFT,
        }
        data.update(overrides)
        return SimpleNamespace(**data)

    def test_submit_blog_post_requires_superuser(self):
        request = HttpRequest()
        request.auth = SimpleNamespace(user=SimpleNamespace(is_superuser=False))

        status, payload = submit_blog_post(request, self._post_data())

        assert status == 403
        assert payload["message"] == "Forbidden: superuser access required."

    def test_submit_blog_post_creates_draft_post(self):
        request = self._request()
        data = self._post_data()

        with patch("apps.api.views.BlogPost.objects") as objects:
            response = submit_blog_post(request, data)

        assert response.status == "success"
        objects.create.assert_called_once_with(
            title="Hello",
            description="Desc",
            slug="hello",
            tags="django",
            content="Body",
            status=BlogPostStatus.DRAFT,
        )

    def test_list_internal_blog_posts_returns_serialized_items(self):
        request = self._request()
        post = SimpleNamespace(
            id=1,
            title="Hello",
            description="Desc",
            slug="hello",
            tags="django",
            content="Body",
            status=BlogPostStatus.DRAFT,
            created_at=None,
        )

        with patch("apps.api.views.BlogPost.objects") as objects:
            objects.order_by.return_value = [post]
            response = list_internal_blog_posts(request)

        assert len(response["blog_posts"]) == 1
        assert response["blog_posts"][0]["slug"] == "hello"

    def test_get_internal_blog_post_returns_404_when_missing(self):
        request = self._request()

        with patch("apps.api.views.BlogPost.objects") as objects:
            objects.get.side_effect = Exception("not found")
            # normalize to model-specific behavior
            from apps.blog.models import BlogPost

            objects.get.side_effect = BlogPost.DoesNotExist
            status, payload = get_internal_blog_post(request, blog_post_id=999)

        assert status == 404
        assert payload["message"] == "Blog post not found."

    def test_publish_internal_blog_post_sets_status_to_published(self):
        request = self._request()
        post = Mock()

        with patch("apps.api.views.BlogPost.objects") as objects:
            objects.get.return_value = post
            response = publish_internal_blog_post(request, blog_post_id=12)

        assert response["status"] == "success"
        assert post.status == BlogPostStatus.PUBLISHED
        post.save.assert_called_once_with(update_fields=["status", "updated_at"])

    def test_update_internal_blog_post_replaces_all_editable_fields(self):
        request = self._request()
        post = Mock()
        data = self._post_data(title="Updated", status=BlogPostStatus.PUBLISHED)

        with patch("apps.api.views.BlogPost.objects") as objects:
            objects.get.return_value = post
            response = update_internal_blog_post(request, blog_post_id=12, data=data)

        assert response["status"] == "success"
        assert post.title == "Updated"
        assert post.status == BlogPostStatus.PUBLISHED
        post.save.assert_called_once_with(
            update_fields=[
                "title",
                "description",
                "slug",
                "tags",
                "content",
                "status",
                "updated_at",
            ]
        )

    def test_patch_internal_blog_post_updates_only_supplied_fields(self):
        request = self._request()
        post = Mock()
        data = SimpleNamespace(
            title=None,
            description="New desc",
            slug=None,
            tags=None,
            content=None,
            status=BlogPostStatus.PUBLISHED,
        )

        with patch("apps.api.views.BlogPost.objects") as objects:
            objects.get.return_value = post
            response = patch_internal_blog_post(request, blog_post_id=12, data=data)

        assert response["status"] == "success"
        assert post.description == "New desc"
        assert post.status == BlogPostStatus.PUBLISHED
        post.save.assert_called_once_with(update_fields=["description", "status", "updated_at"])

    def test_delete_internal_blog_post_deletes_existing_post(self):
        request = self._request()

        with patch("apps.api.views.BlogPost.objects") as objects:
            objects.filter.return_value.delete.return_value = (1, {})
            response = delete_internal_blog_post(request, blog_post_id=12)

        assert response["status"] == "success"
        objects.filter.assert_called_once_with(id=12)

    def test_delete_internal_blog_post_returns_404_when_missing(self):
        request = self._request()

        with patch("apps.api.views.BlogPost.objects") as objects:
            objects.filter.return_value.delete.return_value = (0, {})
            status, payload = delete_internal_blog_post(request, blog_post_id=404)

        assert status == 404
        assert payload["message"] == "Blog post not found."

    def test_review_internal_blog_post_moves_post_to_draft(self):
        request = self._request()
        post = Mock()

        with patch("apps.api.views.BlogPost.objects") as objects:
            objects.get.return_value = post
            response = review_internal_blog_post(request, blog_post_id=12)

        assert response["status"] == "success"
        assert post.status == BlogPostStatus.DRAFT
        post.save.assert_called_once_with(update_fields=["status", "updated_at"])


class UserInfoApiUnitTests(SimpleTestCase):
    def test_get_user_info_returns_safe_profile_data(self):
        user = SimpleNamespace(
            id=7,
            email="ada@example.com",
            username="ada",
            first_name="Ada",
            last_name="Lovelace",
            date_joined="2026-05-14T00:00:00Z",
            is_staff=False,
            is_superuser=False,
            get_full_name=lambda: "Ada Lovelace",
        )
        profile = SimpleNamespace(
            id=11,
            user=user,
            state="signed_up",
            has_active_subscription=False,
        )
        request = HttpRequest()
        request.auth = profile

        with patch("apps.api.views.track_activation_event") as track_activation_event:
            response = get_user_info(request)

        assert response["email"] == "ada@example.com"
        assert response["full_name"] == "Ada Lovelace"
        assert response["profile"] == {
            "id": 11,
            "state": "signed_up",
            "has_active_subscription": False,
        }
        assert "key" not in response
        assert "is_staff" not in response
        assert "is_superuser" not in response
        track_activation_event.assert_called_once_with(
            profile,
            ROWSET_GET_USER_INFO_SUCCEEDED,
            {
                "interface": "rest",
                "agent_api_key_present": False,
                "agent_api_key_id": None,
                "agent_api_key_access_level": "",
            },
            source_function="apps.api.views.get_user_info",
        )


class DatasetListApiUnitTests(SimpleTestCase):
    @override_settings(SITE_URL="https://rowset.example")
    def test_list_datasets_returns_profile_dataset_metadata_without_rows(self):
        project = SimpleNamespace(
            key="3efc2ad0-8d28-44bc-a554-cb3eab89f45a",
            name="Launch",
            description="Launch datasets",
        )
        dataset = SimpleNamespace(
            key="6b0fe8f5-89e5-4cb1-a40d-6aa912ba31d7",
            name="Customers",
            description="Customers eligible for launch outreach.",
            instructions="Use email as the stable identity. Do not rewrite names from guesses.",
            metadata={"workflow": {"default_status": "new"}},
            project=project,
            original_filename="customers.csv",
            file_type="csv",
            status="ready",
            headers=["email", "name"],
            column_schema={
                "email": {
                    "type": "email",
                    "description": "Primary contact address for the customer.",
                },
                "name": {"type": "text"},
            },
            index_column="email",
            index_generated=False,
            row_count=42,
            public_enabled=True,
            public_key="4b7b8e47-15a5-4bd5-82cb-8c4f4fd40ce9",
            public_page_size=25,
            public_password_hash="hashed",
            created_at="2026-05-14T00:00:00Z",
            updated_at="2026-05-14T00:01:00Z",
            confirmed_at="2026-05-14T00:02:00Z",
            processed_at="2026-05-14T00:03:00Z",
            archived_at=None,
            is_public_password_protected=True,
            get_public_url=lambda: "/share/datasets/4b7b8e47-15a5-4bd5-82cb-8c4f4fd40ce9/",
        )
        queryset = Mock()
        queryset.count.return_value = 1
        queryset.__getitem__ = Mock(return_value=[dataset])
        datasets = Mock()
        active_datasets = datasets.filter.return_value
        active_datasets.select_related.return_value.only.return_value = queryset
        request = HttpRequest()
        request.auth = SimpleNamespace(datasets=datasets)

        response = list_datasets(request)

        assert response["count"] == 1
        assert response["total_count"] == 1
        assert response["limit"] == 100
        assert response["offset"] == 0
        assert response["has_more"] is False
        assert response["datasets"] == [
            {
                "key": "6b0fe8f5-89e5-4cb1-a40d-6aa912ba31d7",
                "name": "Customers",
                "description": "Customers eligible for launch outreach.",
                "instructions": (
                    "Use email as the stable identity. Do not rewrite names from guesses."
                ),
                "metadata": {"workflow": {"default_status": "new"}},
                "project": {
                    "key": "3efc2ad0-8d28-44bc-a554-cb3eab89f45a",
                    "name": "Launch",
                    "description": "Launch datasets",
                },
                "section": None,
                "original_filename": "customers.csv",
                "file_type": "csv",
                "status": "ready",
                "headers": ["email", "name"],
                "column_schema": {
                    "email": {
                        "type": "email",
                        "description": "Primary contact address for the customer.",
                    },
                    "name": {"type": "text"},
                },
                "index_column": "email",
                "index_generated": False,
                "row_count": 42,
                "public_enabled": True,
                "public_key": "4b7b8e47-15a5-4bd5-82cb-8c4f4fd40ce9",
                "public_url": (
                    "https://rowset.example/share/datasets/4b7b8e47-15a5-4bd5-82cb-8c4f4fd40ce9/"
                ),
                "public_page_size": 25,
                "public_password_protected": True,
                "created_at": "2026-05-14T00:00:00Z",
                "updated_at": "2026-05-14T00:01:00Z",
                "confirmed_at": "2026-05-14T00:02:00Z",
                "processed_at": "2026-05-14T00:03:00Z",
                "archived_at": None,
            }
        ]
        datasets.filter.assert_called_once_with(archived_at__isnull=True)
        active_datasets.select_related.assert_called_once_with("project", "section")
        active_datasets.select_related.return_value.only.assert_called_once()
        queryset.__getitem__.assert_called_once_with(slice(0, 100, None))

    @override_settings(SITE_URL="https://rowset.example")
    def test_list_archived_datasets_returns_only_archived_profile_dataset_metadata(self):
        dataset = SimpleNamespace(
            key="6b0fe8f5-89e5-4cb1-a40d-6aa912ba31d7",
            name="Archived customers",
            description="Archived customer list.",
            instructions="Restore before mutating rows.",
            metadata={"archive_reason": "cleanup"},
            project=None,
            original_filename="customers.csv",
            file_type="csv",
            status="ready",
            headers=["email", "name"],
            column_schema={
                "email": {"type": "email"},
                "name": {"type": "text"},
            },
            index_column="email",
            index_generated=False,
            row_count=42,
            public_enabled=False,
            public_key="4b7b8e47-15a5-4bd5-82cb-8c4f4fd40ce9",
            public_page_size=25,
            public_password_hash="",
            created_at="2026-05-14T00:00:00Z",
            updated_at="2026-05-14T00:01:00Z",
            confirmed_at="2026-05-14T00:02:00Z",
            processed_at="2026-05-14T00:03:00Z",
            archived_at="2026-05-15T00:00:00Z",
            is_public_password_protected=False,
            get_public_url=lambda: "/share/datasets/4b7b8e47-15a5-4bd5-82cb-8c4f4fd40ce9/",
        )
        queryset = Mock()
        queryset.count.return_value = 1
        queryset.__getitem__ = Mock(return_value=[dataset])
        datasets = Mock()
        archived_datasets = datasets.filter.return_value
        visible_archived_datasets = archived_datasets.exclude.return_value
        visible_archived_datasets.select_related.return_value.only.return_value = queryset
        request = HttpRequest()
        request.auth = SimpleNamespace(datasets=datasets)

        response = list_archived_datasets(request)

        assert response["count"] == 1
        assert response["total_count"] == 1
        assert response["datasets"][0]["name"] == "Archived customers"
        assert response["datasets"][0]["archived_at"] == "2026-05-15T00:00:00Z"
        datasets.filter.assert_called_once_with(archived_at__isnull=False)
        archived_datasets.exclude.assert_called_once_with(status=DatasetStatus.PREVIEWED)
        visible_archived_datasets.select_related.assert_called_once_with("project", "section")
        visible_archived_datasets.select_related.return_value.only.assert_called_once()
        queryset.__getitem__.assert_called_once_with(slice(0, 100, None))


class ProjectListApiUnitTests(SimpleTestCase):
    def test_list_projects_returns_project_metadata(self):
        project = SimpleNamespace(
            key="3efc2ad0-8d28-44bc-a554-cb3eab89f45a",
            name="Launch",
            description="Launch datasets",
            metadata={"github_repo": "https://github.com/acme/launch"},
            dataset_count=2,
            created_at="2026-05-14T00:00:00Z",
            updated_at="2026-05-14T00:01:00Z",
        )
        queryset = Mock()
        queryset.filter.return_value = queryset
        queryset.only.return_value = queryset
        queryset.count.return_value = 1
        queryset.__getitem__ = Mock(return_value=[project])
        projects = Mock()
        projects.annotate.return_value = queryset
        request = HttpRequest()
        request.auth = SimpleNamespace(projects=projects)

        response = list_projects(request)

        assert response["count"] == 1
        assert response["projects"] == [
            {
                "key": "3efc2ad0-8d28-44bc-a554-cb3eab89f45a",
                "name": "Launch",
                "description": "Launch datasets",
                "metadata": {"github_repo": "https://github.com/acme/launch"},
                "dataset_count": 2,
                "created_at": "2026-05-14T00:00:00Z",
                "updated_at": "2026-05-14T00:01:00Z",
                "archived_at": None,
            }
        ]
        projects.annotate.assert_called_once()
        queryset.filter.assert_called_once_with(archived_at__isnull=True)
        queryset.__getitem__.assert_called_once_with(slice(0, 100, None))


def test_api_key_auth_returns_profile_for_valid_key():
    from apps.api.auth import APIKeyAuth

    profile = SimpleNamespace(id=11)
    request = HttpRequest()

    with patch("apps.api.auth.resolve_api_key_profile", return_value=(profile, None)) as resolver:
        response = APIKeyAuth().authenticate(request, "secret-key")

    assert response is profile
    assert request.agent_api_key is None
    resolver.assert_called_once_with("secret-key")

    with patch("apps.api.auth.resolve_api_key_profile", return_value=None):
        response = APIKeyAuth().authenticate(HttpRequest(), "bad-key")

    assert response is None


def test_api_key_auth_enforces_required_access_level():
    from apps.api.auth import APIKeyAuth

    read_key = SimpleNamespace(
        id=1,
        access_level=AgentApiKeyAccessLevel.READ,
    )
    profile = SimpleNamespace(id=11)
    request = HttpRequest()

    with patch(
        "apps.api.auth.resolve_api_key_profile",
        return_value=(profile, read_key),
    ):
        response = APIKeyAuth(AgentApiKeyAccessLevel.READ_WRITE).authenticate(
            request,
            "read-key",
        )

    assert response is None


def test_api_key_auth_accepts_bearer_and_x_api_key_headers():
    from apps.api.auth import APIKeyAuth

    profile = SimpleNamespace(id=11)

    bearer_request = HttpRequest()
    bearer_request.META["HTTP_AUTHORIZATION"] = "Bearer secret-key"
    with patch("apps.api.auth.resolve_api_key_profile", return_value=(profile, None)) as resolver:
        response = APIKeyAuth()(bearer_request)

    assert response is profile
    resolver.assert_called_once_with("secret-key")

    header_request = HttpRequest()
    header_request.META["HTTP_X_API_KEY"] = "header-key"
    with patch("apps.api.auth.resolve_api_key_profile", return_value=(profile, None)) as resolver:
        response = APIKeyAuth()(header_request)

    assert response is profile
    resolver.assert_called_once_with("header-key")


@pytest.mark.django_db
def test_api_key_auth_accepts_named_agent_api_key(django_user_model):
    from apps.api.auth import APIKeyAuth
    from apps.core.services import create_agent_api_key

    user = django_user_model.objects.create_user(
        username="agentapiuser",
        email="agentapiuser@example.com",
        password="password123",
    )
    credential = create_agent_api_key(user.profile, "Codex")
    request = HttpRequest()

    response = APIKeyAuth().authenticate(request, credential.raw_key)

    assert response == user.profile
    assert request.agent_api_key.name == "Codex"
    request.agent_api_key.refresh_from_db()
    assert request.agent_api_key.last_used_at is not None


@pytest.mark.django_db
def test_read_only_agent_api_key_can_read_but_cannot_write(client, django_user_model):
    from apps.core.services import create_agent_api_key

    user = django_user_model.objects.create_user(
        username="readonlyapiuser",
        email="readonlyapiuser@example.com",
        password="password123",
    )
    credential = create_agent_api_key(user.profile, "Read Agent", AgentApiKeyAccessLevel.READ)

    read_response = client.get(
        "/api/user",
        HTTP_AUTHORIZATION=f"Bearer {credential.raw_key}",
    )
    write_response = client.post(
        "/api/projects",
        data=json.dumps({"name": "Launch"}),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {credential.raw_key}",
    )
    feedback_response = client.post(
        "/api/feedback",
        data=json.dumps({"feedback": "Read-only keys should not create feedback rows."}),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {credential.raw_key}",
    )

    assert read_response.status_code == 200
    assert read_response.json()["email"] == "readonlyapiuser@example.com"
    assert write_response.status_code == 401
    assert feedback_response.status_code == 401


@pytest.mark.django_db
@override_settings(SITE_URL="https://rowset.example")
def test_agent_api_key_can_submit_feedback_through_rest(client, django_user_model):
    from apps.core.choices import FeedbackSource
    from apps.core.models import Feedback
    from apps.core.services import create_agent_api_key

    user = django_user_model.objects.create_user(
        username="feedbackapiuser",
        email="feedbackapiuser@example.com",
        password="password123",
    )
    credential = create_agent_api_key(
        user.profile,
        "Feedback Agent",
        AgentApiKeyAccessLevel.READ_WRITE,
    )

    response = client.post(
        "/api/feedback",
        data=json.dumps(
            {
                "feedback": "The MCP setup prompt should mention bearer-token env vars.",
                "page": "mcp:setup",
                "context": {"tool": "get_rowset_capabilities"},
            }
        ),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {credential.raw_key}",
    )

    assert response.status_code == 201
    feedback = Feedback.objects.get(profile=user.profile)
    dataset = Dataset.objects.get(name="Feedback")
    row = dataset.rows.get(index_value=str(feedback.id))
    expected_row_url = f"https://rowset.example/datasets/{dataset.key}/rows/{row.id}/"
    assert feedback.feedback == "The MCP setup prompt should mention bearer-token env vars."
    assert feedback.page == "mcp:setup"
    assert feedback.source == FeedbackSource.API
    assert feedback.metadata == {
        "tool": "get_rowset_capabilities",
        "rowset_row_url": expected_row_url,
    }
    assert feedback.agent_api_key == credential.agent_api_key
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["feedback"]["uuid"] == str(feedback.uuid)
    assert payload["feedback"]["source"] == FeedbackSource.API
    assert payload["dataset"] == str(dataset.key)
    assert payload["row"] == row.id
    assert payload["row_url"] == expected_row_url
    assert row.created_by_agent_api_key == credential.agent_api_key
    assert row.data["context"] == '{"tool":"get_rowset_capabilities"}'
    assert row.data["submitted_via"] == "api"


@pytest.mark.django_db
def test_agent_feedback_returns_dataset_service_errors(
    client,
    django_user_model,
    monkeypatch,
):
    from apps.api.services import DatasetServiceError
    from apps.core.services import create_agent_api_key

    user = django_user_model.objects.create_user(
        username="feedbackerrorapiuser",
        email="feedbackerrorapiuser@example.com",
        password="password123",
    )
    credential = create_agent_api_key(
        user.profile,
        "Feedback Agent",
        AgentApiKeyAccessLevel.READ_WRITE,
    )

    def raise_dataset_error(*args, **kwargs):
        raise DatasetServiceError(429, "Feedback dataset quota exceeded.")

    monkeypatch.setattr("apps.api.views.submit_profile_feedback", raise_dataset_error)

    response = client.post(
        "/api/feedback",
        data=json.dumps({"feedback": "This should return a service error."}),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {credential.raw_key}",
    )

    assert response.status_code == 429
    assert response.json() == {"detail": "Feedback dataset quota exceeded."}


@pytest.mark.django_db
def test_legacy_profile_api_key_can_read_but_cannot_write(client, django_user_model):
    user = django_user_model.objects.create_user(
        username="legacyreadonlyapiuser",
        email="legacyreadonlyapiuser@example.com",
        password="password123",
    )

    read_response = client.get(
        "/api/user",
        HTTP_AUTHORIZATION=f"Bearer {user.profile.key}",
    )
    write_response = client.post(
        "/api/projects",
        data=json.dumps({"name": "Launch"}),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {user.profile.key}",
    )

    assert read_response.status_code == 200
    assert read_response.json()["email"] == "legacyreadonlyapiuser@example.com"
    assert write_response.status_code == 401


@pytest.mark.django_db
def test_admin_agent_api_key_can_create_new_agent_api_key(client, django_user_model):
    from apps.core.models import AgentApiKey
    from apps.core.services import create_agent_api_key, hash_agent_api_key

    user = django_user_model.objects.create_user(
        username="adminapiuser",
        email="adminapiuser@example.com",
        password="password123",
    )
    admin_credential = create_agent_api_key(
        user.profile,
        "Admin Agent",
        AgentApiKeyAccessLevel.ADMIN,
    )

    response = client.post(
        "/api/agent-api-keys",
        data=json.dumps(
            {
                "name": "Reporting Agent",
                "access_level": AgentApiKeyAccessLevel.READ,
            }
        ),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {admin_credential.raw_key}",
    )

    assert response.status_code == 201
    payload = response.json()
    created_key = AgentApiKey.objects.get(profile=user.profile, name="Reporting Agent")
    assert payload["agent_api_key"]["access_level"] == AgentApiKeyAccessLevel.READ
    assert payload["agent_api_key"]["key_prefix"] == created_key.key_prefix
    assert payload["api_key"].startswith("rsk_")
    assert created_key.access_level == AgentApiKeyAccessLevel.READ
    assert created_key.token_hash == hash_agent_api_key(payload["api_key"])


@pytest.mark.django_db
def test_non_admin_agent_api_key_cannot_create_new_agent_api_key(client, django_user_model):
    from apps.core.models import AgentApiKey
    from apps.core.services import create_agent_api_key

    user = django_user_model.objects.create_user(
        username="writerapiuser",
        email="writerapiuser@example.com",
        password="password123",
    )
    credential = create_agent_api_key(
        user.profile,
        "Writer Agent",
        AgentApiKeyAccessLevel.READ_WRITE,
    )

    response = client.post(
        "/api/agent-api-keys",
        data=json.dumps({"name": "Denied Agent", "access_level": "read"}),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {credential.raw_key}",
    )

    assert response.status_code == 401
    assert not AgentApiKey.objects.filter(profile=user.profile, name="Denied Agent").exists()


@pytest.mark.django_db
def test_legacy_profile_api_key_cannot_create_new_agent_api_key(client, django_user_model):
    from apps.core.models import AgentApiKey

    user = django_user_model.objects.create_user(
        username="legacyapiuser",
        email="legacyapiuser@example.com",
        password="password123",
    )

    response = client.post(
        "/api/agent-api-keys",
        data=json.dumps({"name": "Denied Agent", "access_level": "read"}),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {user.profile.key}",
    )

    assert response.status_code == 401
    assert not AgentApiKey.objects.filter(profile=user.profile, name="Denied Agent").exists()


def test_superuser_api_key_auth_eager_loads_user_and_requires_superuser():
    from apps.api.auth import SuperuserAPIKeyAuth

    superuser_profile = SimpleNamespace(id=11, user=SimpleNamespace(id=21, is_superuser=True))
    regular_profile = SimpleNamespace(id=12, user=SimpleNamespace(id=22, is_superuser=False))
    admin_agent_api_key = SimpleNamespace(id=1, access_level=AgentApiKeyAccessLevel.ADMIN)

    with patch(
        "apps.api.auth.resolve_api_key_profile",
        return_value=(superuser_profile, admin_agent_api_key),
    ) as resolver:
        response = SuperuserAPIKeyAuth().authenticate(HttpRequest(), "secret-key")

    assert response is superuser_profile
    resolver.assert_called_once_with("secret-key")

    with patch("apps.api.auth.resolve_api_key_profile", return_value=(superuser_profile, None)):
        response = SuperuserAPIKeyAuth().authenticate(HttpRequest(), "legacy-key")

    assert response is None

    with patch("apps.api.auth.resolve_api_key_profile", return_value=(regular_profile, None)):
        response = SuperuserAPIKeyAuth().authenticate(HttpRequest(), "regular-key")

    assert response is None

    with patch("apps.api.auth.resolve_api_key_profile", return_value=None):
        response = SuperuserAPIKeyAuth().authenticate(HttpRequest(), "bad-key")

    assert response is None


@pytest.mark.django_db
@override_settings(SITE_URL="https://rowset.example")
def test_update_dataset_public_preview_enables_public_link(django_user_model):
    from apps.api.services import update_profile_dataset_public_preview

    user = django_user_model.objects.create_user(
        username="previewapiuser",
        email="previewapiuser@example.com",
        password="password123",
    )
    dataset = Dataset.objects.create(
        profile=user.profile,
        name="People",
        original_filename="Created via API",
        file_type="api",
        status=DatasetStatus.READY,
        headers=["email", "name"],
        index_column="email",
        row_count=0,
    )

    result = update_profile_dataset_public_preview(
        user.profile,
        str(dataset.key),
        public_enabled=True,
        public_page_size=25,
        public_password="share-secret",
    )

    dataset.refresh_from_db()
    assert dataset.public_enabled is True
    assert dataset.public_page_size == 25
    assert dataset.public_password_matches("share-secret")
    assert result["dataset"]["public_url"] == (
        f"https://rowset.example/share/datasets/{dataset.public_key}/"
    )
    assert result["dataset"]["public_password_protected"] is True


@pytest.mark.django_db
def test_update_dataset_public_preview_preserves_enabled_state_when_omitted(django_user_model):
    from apps.api.services import update_profile_dataset_public_preview

    user = django_user_model.objects.create_user(
        username="previewpartial",
        email="previewpartial@example.com",
        password="password123",
    )
    dataset = Dataset.objects.create(
        profile=user.profile,
        name="People",
        original_filename="Created via API",
        file_type="api",
        status=DatasetStatus.READY,
        headers=["email", "name"],
        index_column="email",
        row_count=0,
        public_enabled=True,
        public_page_size=10,
    )

    result = update_profile_dataset_public_preview(
        user.profile,
        str(dataset.key),
        public_page_size=25,
        public_password="share-secret",
    )

    dataset.refresh_from_db()
    assert dataset.public_enabled is True
    assert dataset.public_page_size == 25
    assert dataset.public_password_matches("share-secret")
    assert result["dataset"]["public_enabled"] is True


@pytest.mark.django_db
def test_update_dataset_public_preview_requires_ready_dataset(django_user_model):
    from apps.api.services import DatasetServiceError, update_profile_dataset_public_preview

    user = django_user_model.objects.create_user(
        username="previewblocked",
        email="previewblocked@example.com",
        password="password123",
    )
    dataset = Dataset.objects.create(
        profile=user.profile,
        name="People",
        original_filename="Created via API",
        file_type="api",
        status=DatasetStatus.PROCESSING,
        headers=["email", "name"],
        index_column="email",
        row_count=0,
    )

    with pytest.raises(DatasetServiceError) as exc:
        update_profile_dataset_public_preview(
            user.profile,
            str(dataset.key),
            public_enabled=True,
        )

    assert exc.value.status_code == 409
    assert "ready datasets" in exc.value.message


@pytest.mark.django_db
def test_dataset_lookup_resolves_owned_public_identifiers(django_user_model):
    from apps.api.services import DatasetServiceError, get_ready_profile_dataset

    owner = django_user_model.objects.create_user(
        username="publicidentifierowner",
        email="publicidentifierowner@example.com",
        password="password123",
    )
    other_user = django_user_model.objects.create_user(
        username="publicidentifierother",
        email="publicidentifierother@example.com",
        password="password123",
    )
    dataset = Dataset.objects.create(
        profile=owner.profile,
        name="People",
        original_filename="Created via API",
        file_type="api",
        status=DatasetStatus.READY,
        headers=["email", "name"],
        index_column="email",
        row_count=1,
        public_enabled=True,
    )
    row = DatasetRow.objects.create(
        dataset=dataset,
        row_number=1,
        index_value="ada@example.com",
        data={"email": "ada@example.com", "name": "Ada"},
    )
    public_dataset_url = f"https://rowset.example/share/datasets/{dataset.public_key}/"
    public_row_url = f"{public_dataset_url}rows/{row.id}/"

    assert get_ready_profile_dataset(owner.profile, str(dataset.public_key)) == dataset
    assert get_ready_profile_dataset(owner.profile, public_dataset_url) == dataset
    assert get_ready_profile_dataset(owner.profile, public_row_url) == dataset

    with pytest.raises(DatasetServiceError) as exc:
        get_ready_profile_dataset(other_user.profile, public_dataset_url)

    assert exc.value.status_code == 404
    assert exc.value.message == "Dataset not found."


@pytest.mark.django_db
@override_settings(SITE_URL="https://rowset.example")
def test_search_profile_datasets_filters_metadata_without_rows(django_user_model):
    from apps.api.services import search_profile_datasets

    user = django_user_model.objects.create_user(
        username="datasetsearchowner",
        email="datasetsearchowner@example.com",
        password="password123",
    )
    other_user = django_user_model.objects.create_user(
        username="datasetsearchother",
        email="datasetsearchother@example.com",
        password="password123",
    )
    project = Project.objects.create(
        profile=user.profile,
        name="Rowset",
        description="Rowset product work",
    )
    matching_dataset = Dataset.objects.create(
        profile=user.profile,
        project=project,
        name="Rowset Feature Suggestions",
        original_filename="Created via API",
        file_type="api",
        status=DatasetStatus.READY,
        headers=["suggestion_id", "status", "notes"],
        index_column="suggestion_id",
        row_count=2,
    )
    old_matching_dataset = Dataset.objects.create(
        profile=user.profile,
        project=project,
        name="Old Rowset Feature Suggestions",
        original_filename="Created via API",
        file_type="api",
        status=DatasetStatus.READY,
        headers=["suggestion_id", "status", "notes"],
        index_column="suggestion_id",
    )
    Dataset.objects.filter(id=old_matching_dataset.id).update(
        updated_at=timezone.now() - timedelta(days=10)
    )
    Dataset.objects.create(
        profile=user.profile,
        project=project,
        name="Rowset Feature Suggestions Archive",
        original_filename="Created via API",
        file_type="api",
        status=DatasetStatus.READY,
        headers=["suggestion_id", "status"],
        index_column="suggestion_id",
        archived_at=timezone.now(),
    )
    Dataset.objects.create(
        profile=user.profile,
        project=project,
        name="Rowset Feature Logs",
        original_filename="Created via API",
        file_type="api",
        status=DatasetStatus.READY,
        headers=["feature_id", "status"],
        index_column="feature_id",
    )
    Dataset.objects.create(
        profile=other_user.profile,
        project=None,
        name="Rowset Feature Suggestions",
        original_filename="Created via API",
        file_type="api",
        status=DatasetStatus.READY,
        headers=["suggestion_id", "status", "notes"],
        index_column="suggestion_id",
    )

    response = search_profile_datasets(
        user.profile,
        query="feature",
        project_key=str(project.key),
        header_contains="suggestion_id",
        status="READY",
        updated_after=(timezone.now() - timedelta(days=1)).isoformat(),
    )

    assert response["count"] == 1
    assert response["total_count"] == 1
    assert response["datasets"][0]["key"] == str(matching_dataset.key)
    assert response["datasets"][0]["project"]["key"] == str(project.key)
    assert "rows" not in response["datasets"][0]


@pytest.mark.django_db
@override_settings(SITE_URL="https://rowset.example")
def test_search_profile_datasets_matches_description_and_instructions(django_user_model):
    from apps.api.services import search_profile_datasets

    user = django_user_model.objects.create_user(
        username="datasetsearchmetadata",
        email="datasetsearchmetadata@example.com",
        password="password123",
    )
    Dataset.objects.create(
        profile=user.profile,
        name="Launch tasks",
        description="Persistent planning board for launch execution.",
        instructions="Use the blocked status only when another person must act.",
        original_filename="Created via API",
        file_type="api",
        status=DatasetStatus.READY,
        headers=["task_id", "status"],
        index_column="task_id",
    )
    Dataset.objects.create(
        profile=user.profile,
        name="Contacts",
        original_filename="Created via API",
        file_type="api",
        status=DatasetStatus.READY,
        headers=["email"],
        index_column="email",
    )

    description_response = search_profile_datasets(user.profile, query="planning board")
    instructions_response = search_profile_datasets(user.profile, query="blocked status")

    assert description_response["count"] == 1
    assert description_response["datasets"][0]["name"] == "Launch tasks"
    assert instructions_response["count"] == 1
    assert instructions_response["datasets"][0]["name"] == "Launch tasks"


@pytest.mark.django_db
def test_search_profile_datasets_returns_empty_page_for_stale_project_key(django_user_model):
    from apps.api.services import search_profile_datasets

    user = django_user_model.objects.create_user(
        username="datasetsearchstaleproject",
        email="datasetsearchstaleproject@example.com",
        password="password123",
    )

    response = search_profile_datasets(
        user.profile,
        project_key="d8cb2ebe-5a4e-40fa-8844-3cfc3de3754e",
    )

    assert response["count"] == 0
    assert response["total_count"] == 0
    assert response["datasets"] == []


@pytest.mark.django_db
def test_search_profile_datasets_rejects_malformed_project_key(django_user_model):
    from apps.api.services import DatasetServiceError, search_profile_datasets

    user = django_user_model.objects.create_user(
        username="datasetsearchbadproject",
        email="datasetsearchbadproject@example.com",
        password="password123",
    )

    with pytest.raises(DatasetServiceError) as exc:
        search_profile_datasets(user.profile, project_key="not-a-uuid")

    assert exc.value.status_code == 400
    assert "project_key" in exc.value.message


@pytest.mark.django_db
@override_settings(SITE_URL="https://rowset.example", TIME_ZONE="America/New_York")
def test_search_profile_datasets_treats_naive_updated_after_as_utc(django_user_model):
    from apps.api.services import search_profile_datasets

    user = django_user_model.objects.create_user(
        username="datasetsearchutc",
        email="datasetsearchutc@example.com",
        password="password123",
    )
    dataset = Dataset.objects.create(
        profile=user.profile,
        name="UTC Search",
        original_filename="Created via API",
        file_type="api",
        status=DatasetStatus.READY,
        headers=["id"],
        index_column="id",
    )
    Dataset.objects.filter(id=dataset.id).update(updated_at=datetime(2026, 6, 1, 12, 0, tzinfo=UTC))

    response = search_profile_datasets(
        user.profile,
        updated_after="2026-06-01T10:00:00",
    )

    assert response["count"] == 1
    assert response["datasets"][0]["key"] == str(dataset.key)


@pytest.mark.django_db
def test_search_profile_datasets_ignores_blank_updated_after(django_user_model):
    from apps.api.services import search_profile_datasets

    user = django_user_model.objects.create_user(
        username="datasetsearchblankdate",
        email="datasetsearchblankdate@example.com",
        password="password123",
    )
    Dataset.objects.create(
        profile=user.profile,
        name="Blank Date Search",
        original_filename="Created via API",
        file_type="api",
        status=DatasetStatus.READY,
        headers=["id"],
        index_column="id",
    )

    response = search_profile_datasets(user.profile, updated_after="   ")

    assert response["count"] == 1


@pytest.mark.django_db
def test_search_profile_datasets_query_matches_projectless_dataset(django_user_model):
    from apps.api.services import search_profile_datasets

    user = django_user_model.objects.create_user(
        username="datasetsearchprojectless",
        email="datasetsearchprojectless@example.com",
        password="password123",
    )
    dataset = Dataset.objects.create(
        profile=user.profile,
        name="Ungrouped Feature Notes",
        original_filename="Created via API",
        file_type="api",
        status=DatasetStatus.READY,
        headers=["id"],
        index_column="id",
    )

    response = search_profile_datasets(user.profile, query="ungrouped")

    assert response["count"] == 1
    assert response["datasets"][0]["key"] == str(dataset.key)


@pytest.mark.django_db
def test_search_profile_datasets_rejects_unknown_status(django_user_model):
    from apps.api.services import DatasetServiceError, search_profile_datasets

    user = django_user_model.objects.create_user(
        username="datasetsearchstatus",
        email="datasetsearchstatus@example.com",
        password="password123",
    )

    with pytest.raises(DatasetServiceError) as exc:
        search_profile_datasets(user.profile, status="missing")

    assert exc.value.status_code == 400
    assert "Unsupported dataset status" in exc.value.message


@pytest.mark.django_db
def test_search_profile_projects_filters_owned_projects(django_user_model):
    from apps.api.services import search_profile_projects

    user = django_user_model.objects.create_user(
        username="projectsearchowner",
        email="projectsearchowner@example.com",
        password="password123",
    )
    other_user = django_user_model.objects.create_user(
        username="projectsearchother",
        email="projectsearchother@example.com",
        password="password123",
    )
    project = Project.objects.create(
        profile=user.profile,
        name="Garden of Minds",
        description="Feature loop tracking",
        metadata={"github_repo": "https://github.com/acme/feature-loop"},
    )
    Project.objects.create(
        profile=user.profile,
        name="Launch",
        description="Marketing work",
        metadata={"notion_doc": "https://notion.so/acme/launch"},
    )
    Project.objects.create(
        profile=other_user.profile,
        name="Other Feature Loop",
        description="Should not be visible",
        metadata={"github_repo": "https://github.com/other/feature-loop"},
    )

    response = search_profile_projects(user.profile, query="github.com/acme/feature-loop")

    assert response["count"] == 1
    assert response["total_count"] == 1
    assert response["projects"][0]["key"] == str(project.key)
    assert response["projects"][0]["metadata"] == {
        "github_repo": "https://github.com/acme/feature-loop"
    }


@pytest.mark.django_db
def test_update_profile_project_changes_name_and_description(django_user_model):
    from apps.api.services import update_profile_project

    user = django_user_model.objects.create_user(
        username="projectupdateowner",
        email="projectupdateowner@example.com",
        password="password123",
    )
    project = Project.objects.create(
        profile=user.profile,
        name="Launch",
        description="Initial launch datasets.",
    )

    response = update_profile_project(
        user.profile,
        str(project.key),
        name="Launch operations",
        description="Updated launch context.",
    )

    assert response["status"] == "success"
    assert response["message"] == "Project updated."
    assert response["project"]["name"] == "Launch operations"
    assert response["project"]["description"] == "Updated launch context."
    project.refresh_from_db()
    assert project.name == "Launch operations"
    assert project.description == "Updated launch context."


@pytest.mark.django_db
def test_update_profile_project_rejects_duplicate_name(django_user_model):
    from apps.api.services import DatasetServiceError, update_profile_project

    user = django_user_model.objects.create_user(
        username="projectupdateduplicate",
        email="projectupdateduplicate@example.com",
        password="password123",
    )
    Project.objects.create(profile=user.profile, name="Launch")
    project = Project.objects.create(profile=user.profile, name="Operations")

    with pytest.raises(DatasetServiceError) as exc:
        update_profile_project(user.profile, str(project.key), name="launch")

    assert exc.value.status_code == 409
    assert exc.value.message == "Project name already exists."


@pytest.mark.django_db
def test_project_section_services_create_assign_and_group_datasets(django_user_model):
    from apps.api.services import (
        create_profile_project_section,
        serialize_profile_project_detail,
        update_profile_dataset_project,
    )

    assert hasattr(dataset_models, "ProjectSection")

    user = django_user_model.objects.create_user(
        username="projectsectionowner",
        email="projectsectionowner@example.com",
        password="password123",
    )
    project = Project.objects.create(profile=user.profile, name="Rowset")
    dataset = Dataset.objects.create(
        profile=user.profile,
        project=project,
        name="Content ledger",
        original_filename="Created via API",
        file_type="api",
        status=DatasetStatus.READY,
        headers=["slug"],
        index_column="slug",
    )

    section_response = create_profile_project_section(
        user.profile,
        str(project.key),
        name="Blog",
        description="Content operations datasets.",
        metadata={"goal": "content-led growth"},
    )
    update_response = update_profile_dataset_project(
        user.profile,
        str(dataset.key),
        str(project.key),
        section_key=section_response["section"]["key"],
    )
    detail_response = serialize_profile_project_detail(user.profile, str(project.key))

    assert section_response["section"]["name"] == "Blog"
    assert section_response["section"]["dataset_count"] == 0
    assert update_response["dataset"]["section"]["key"] == section_response["section"]["key"]
    assert update_response["dataset"]["section"]["name"] == "Blog"
    dataset.refresh_from_db()
    assert dataset.section.name == "Blog"
    assert detail_response["sections"][0]["key"] == section_response["section"]["key"]
    assert detail_response["sections"][0]["dataset_count"] == 1
    assert detail_response["dataset_groups"][0]["label"] == "Blog"
    assert (
        detail_response["dataset_groups"][0]["section"]["key"]
        == (section_response["section"]["key"])
    )
    assert detail_response["dataset_groups"][0]["datasets"]["count"] == 1
    assert detail_response["dataset_groups"][0]["datasets"]["total_count"] == 1
    assert "limit" not in detail_response["dataset_groups"][0]["datasets"]
    assert "offset" not in detail_response["dataset_groups"][0]["datasets"]
    assert "has_more" not in detail_response["dataset_groups"][0]["datasets"]
    assert detail_response["dataset_groups"][0]["datasets"]["datasets"][0]["key"] == (
        str(dataset.key)
    )


@pytest.mark.django_db
def test_dataset_project_update_rejects_section_without_project(django_user_model):
    from apps.api.services import DatasetServiceError, update_profile_dataset_project

    assert hasattr(dataset_models, "ProjectSection")

    user = django_user_model.objects.create_user(
        username="sectionwithoutproject",
        email="sectionwithoutproject@example.com",
        password="password123",
    )
    project = Project.objects.create(profile=user.profile, name="Rowset")
    section = dataset_models.ProjectSection.objects.create(
        profile=user.profile,
        project=project,
        name="Blog",
    )
    dataset = Dataset.objects.create(
        profile=user.profile,
        name="Content ledger",
        original_filename="Created via API",
        file_type="api",
        status=DatasetStatus.READY,
        headers=["slug"],
        index_column="slug",
    )

    with pytest.raises(DatasetServiceError) as exc:
        update_profile_dataset_project(
            user.profile,
            str(dataset.key),
            project_key=None,
            section_key=str(section.key),
        )

    assert exc.value.status_code == 404
    assert exc.value.message == "Project section not found."


@pytest.mark.django_db
def test_create_profile_dataset_enqueues_vector_backfill_when_enabled(
    django_user_model,
    django_capture_on_commit_callbacks,
    monkeypatch,
):
    from apps.api.services import create_profile_dataset

    user = django_user_model.objects.create_user(
        username="vectorcreateowner",
        email="vectorcreateowner@example.com",
        password="password123",
    )
    calls = []
    monkeypatch.setattr(
        "apps.datasets.vector_tasks.async_task",
        lambda task_path, *args: calls.append((task_path, args)),
    )

    with override_settings(ROWSET_VECTOR_SEARCH_ENABLED=True):
        with django_capture_on_commit_callbacks(execute=True):
            response = create_profile_dataset(
                user.profile,
                name="Vector Tasks",
                headers=["task_id", "title"],
                index_column="task_id",
                rows=[{"task_id": "TASK-1", "title": "Index initial rows"}],
            )

    dataset = Dataset.objects.get(key=response["dataset"]["key"])
    assert calls == [("apps.datasets.tasks.backfill_dataset_vectors_task", (dataset.id,))]


@pytest.mark.django_db
def test_row_write_services_enqueue_vector_index_and_delete_when_enabled(
    django_user_model,
    django_capture_on_commit_callbacks,
    monkeypatch,
):
    from apps.api.services import (
        create_profile_dataset_row,
        delete_profile_dataset_row,
        patch_profile_dataset_row,
    )

    user = django_user_model.objects.create_user(
        username="vectorrowowner",
        email="vectorrowowner@example.com",
        password="password123",
    )
    dataset = Dataset.objects.create(
        profile=user.profile,
        name="Vector Rows",
        original_filename="rows.csv",
        status=DatasetStatus.READY,
        headers=["task_id", "title"],
        index_column="task_id",
    )
    calls = []
    monkeypatch.setattr(
        "apps.datasets.vector_tasks.async_task",
        lambda task_path, *args: calls.append((task_path, args)),
    )

    with override_settings(ROWSET_VECTOR_SEARCH_ENABLED=True):
        with django_capture_on_commit_callbacks(execute=True):
            create_response = create_profile_dataset_row(
                user.profile,
                str(dataset.key),
                {"task_id": "TASK-1", "title": "Index row"},
            )
        row_id = create_response["row"]["id"]

        with django_capture_on_commit_callbacks(execute=True):
            patch_profile_dataset_row(
                user.profile,
                str(dataset.key),
                row_id,
                {"title": "Reindex row"},
            )

        with django_capture_on_commit_callbacks(execute=True):
            delete_profile_dataset_row(user.profile, str(dataset.key), row_id)

    assert calls == [
        ("apps.datasets.tasks.index_dataset_row_vector", (row_id,)),
        ("apps.datasets.tasks.index_dataset_row_vector", (row_id,)),
        ("apps.datasets.tasks.delete_dataset_row_vectors", (dataset.id, [row_id])),
    ]


@pytest.mark.django_db
def test_archive_profile_dataset_enqueues_vector_delete_when_enabled(
    django_user_model,
    django_capture_on_commit_callbacks,
    monkeypatch,
):
    from apps.api.services import archive_profile_dataset

    user = django_user_model.objects.create_user(
        username="vectorarchiveowner",
        email="vectorarchiveowner@example.com",
        password="password123",
    )
    dataset = Dataset.objects.create(
        profile=user.profile,
        name="Archive vectors",
        original_filename="archive.csv",
        status=DatasetStatus.READY,
        headers=["id"],
        index_column="id",
    )
    calls = []
    monkeypatch.setattr(
        "apps.datasets.vector_tasks.async_task",
        lambda task_path, *args: calls.append((task_path, args)),
    )

    with override_settings(ROWSET_VECTOR_SEARCH_ENABLED=True):
        with django_capture_on_commit_callbacks(execute=True):
            archive_profile_dataset(user.profile, str(dataset.key))

    assert calls == [("apps.datasets.tasks.delete_dataset_vectors", (dataset.id,))]


@pytest.mark.django_db
def test_restore_profile_dataset_enqueues_vector_backfill_when_enabled(
    django_user_model,
    django_capture_on_commit_callbacks,
    monkeypatch,
):
    from apps.api.services import restore_profile_dataset

    user = django_user_model.objects.create_user(
        username="vectorrestoreowner",
        email="vectorrestoreowner@example.com",
        password="password123",
    )
    dataset = Dataset.objects.create(
        profile=user.profile,
        name="Restore vectors",
        original_filename="restore.csv",
        status=DatasetStatus.READY,
        headers=["id"],
        index_column="id",
        archived_at=timezone.now(),
    )
    calls = []
    monkeypatch.setattr(
        "apps.datasets.vector_tasks.async_task",
        lambda task_path, *args: calls.append((task_path, args)),
    )

    with override_settings(ROWSET_VECTOR_SEARCH_ENABLED=True):
        with django_capture_on_commit_callbacks(execute=True):
            restore_profile_dataset(user.profile, str(dataset.key))

    assert calls == [("apps.datasets.tasks.backfill_dataset_vectors_task", (dataset.id,))]


@pytest.mark.django_db
def test_schema_mutation_services_enqueue_vector_reindex_when_enabled(
    django_user_model,
    django_capture_on_commit_callbacks,
    monkeypatch,
):
    from apps.api.services import (
        add_profile_dataset_column,
        drop_profile_dataset_column,
        rename_profile_dataset_column,
        update_profile_dataset_column_types,
    )

    user = django_user_model.objects.create_user(
        username="vectorschemaowner",
        email="vectorschemaowner@example.com",
        password="password123",
    )
    dataset = Dataset.objects.create(
        profile=user.profile,
        name="Schema vectors",
        original_filename="schema.csv",
        status=DatasetStatus.READY,
        headers=["task_id", "title"],
        index_column="task_id",
    )
    DatasetRow.objects.create(
        dataset=dataset,
        row_number=1,
        index_value="TASK-1",
        data={"task_id": "TASK-1", "title": "Reindex schema changes"},
    )
    calls = []
    monkeypatch.setattr(
        "apps.datasets.vector_tasks.async_task",
        lambda task_path, *args: calls.append((task_path, args)),
    )

    with override_settings(ROWSET_VECTOR_SEARCH_ENABLED=True):
        with django_capture_on_commit_callbacks(execute=True):
            update_profile_dataset_column_types(
                user.profile,
                str(dataset.key),
                {"title": {"type": "text", "description": "Task title"}},
            )
        with django_capture_on_commit_callbacks(execute=True):
            add_profile_dataset_column(
                user.profile,
                str(dataset.key),
                name="status",
                default_value="Ready",
            )
        with django_capture_on_commit_callbacks(execute=True):
            rename_profile_dataset_column(
                user.profile,
                str(dataset.key),
                old_name="status",
                new_name="state",
            )
        with django_capture_on_commit_callbacks(execute=True):
            drop_profile_dataset_column(user.profile, str(dataset.key), name="state")

    assert calls == [
        ("apps.datasets.tasks.reindex_dataset_vectors_task", (dataset.id,)),
        ("apps.datasets.tasks.reindex_dataset_vectors_task", (dataset.id,)),
        ("apps.datasets.tasks.reindex_dataset_vectors_task", (dataset.id,)),
        ("apps.datasets.tasks.reindex_dataset_vectors_task", (dataset.id,)),
    ]


class FakeDatasetSearchEmbeddingProvider:
    model = "fake-embedding"
    dimensions = 3

    def __init__(self, vectors_by_query=None):
        self.queries = []
        self.vectors_by_query = vectors_by_query or {}

    def embed_text(self, text):
        self.queries.append(text)
        vector = self.vectors_by_query.get(text, [0.1, 0.2, 0.3])
        return EmbeddingResult(vector=vector, model=self.model, dimensions=3)


class FakeDatasetSearchVectorStore:
    def __init__(self, hits):
        self.hits = hits
        self.ensure_calls = 0
        self.searches = []

    def ensure_collection(self):
        self.ensure_calls += 1

    def search_dataset_rows(self, dataset, vector, *, limit=10):
        self.searches.append((str(dataset.key), vector, limit))
        return self.hits


class FakeDatasetSearchEvalVectorStore:
    def __init__(self, hits_by_vector):
        self.hits_by_vector = hits_by_vector
        self.ensure_calls = 0
        self.searches = []

    def ensure_collection(self):
        self.ensure_calls += 1

    def search_dataset_rows(self, dataset, vector, *, limit=10):
        self.searches.append((str(dataset.key), vector, limit))
        return self.hits_by_vector[tuple(vector)]


class FakeProfileRowSearchVectorStore:
    def __init__(self, hits):
        self.hits = hits
        self.searches = []

    def search_profile_dataset_rows(
        self,
        profile,
        vector,
        *,
        dataset_ids=None,
        dataset_status="ready",
        dataset_archived=False,
        limit=10,
    ):
        self.searches.append(
            (
                profile.id,
                vector,
                tuple(dataset_ids or ()),
                dataset_status,
                dataset_archived,
                limit,
            )
        )
        return self.hits


@pytest.mark.django_db
def test_search_profile_rows_searches_ready_datasets_and_filters_vector_hits(django_user_model):
    from apps.api.services import search_profile_rows

    user = django_user_model.objects.create_user(
        username="profilewidevectorowner",
        email="profilewidevectorowner@example.com",
        password="password123",
    )
    tasks = Dataset.objects.create(
        profile=user.profile,
        name="Launch tasks",
        original_filename="tasks.csv",
        status=DatasetStatus.READY,
        headers=["task_id", "status", "title"],
        index_column="task_id",
    )
    customers = Dataset.objects.create(
        profile=user.profile,
        name="Customer risks",
        original_filename="customers.csv",
        status=DatasetStatus.READY,
        headers=["customer_id", "status", "notes"],
        index_column="customer_id",
    )
    missing_filter_header = Dataset.objects.create(
        profile=user.profile,
        name="Research notes",
        original_filename="notes.csv",
        status=DatasetStatus.READY,
        headers=["note_id", "body"],
        index_column="note_id",
    )
    archived = Dataset.objects.create(
        profile=user.profile,
        name="Archived tasks",
        original_filename="archived.csv",
        status=DatasetStatus.READY,
        headers=["task_id", "status", "title"],
        index_column="task_id",
        archived_at=timezone.now(),
    )
    task_row = DatasetRow.objects.create(
        dataset=tasks,
        row_number=1,
        index_value="TASK-1",
        data={"task_id": "TASK-1", "status": "Ready", "title": "Backfill hybrid row search"},
    )
    customer_row = DatasetRow.objects.create(
        dataset=customers,
        row_number=1,
        index_value="CUST-1",
        data={
            "customer_id": "CUST-1",
            "status": "Ready",
            "notes": "Renewal risk from legal review",
        },
    )
    missing_filter_row = DatasetRow.objects.create(
        dataset=missing_filter_header,
        row_number=1,
        index_value="NOTE-1",
        data={"note_id": "NOTE-1", "body": "Renewal risk but no status column"},
    )
    archived_row = DatasetRow.objects.create(
        dataset=archived,
        row_number=1,
        index_value="ARCH-1",
        data={"task_id": "ARCH-1", "status": "Ready", "title": "Archived renewal risk"},
    )
    provider = FakeDatasetSearchEmbeddingProvider()
    store = FakeProfileRowSearchVectorStore(
        [
            DatasetRowVectorSearchHit(
                point_id="archived-point",
                score=0.99,
                payload={"row_id": archived_row.id, "chunk_index": 0, "content_hash": "archived"},
            ),
            DatasetRowVectorSearchHit(
                point_id="missing-filter-point",
                score=0.98,
                payload={
                    "row_id": missing_filter_row.id,
                    "chunk_index": 0,
                    "content_hash": "missing-filter",
                },
            ),
            DatasetRowVectorSearchHit(
                point_id="customer-point",
                score=0.95,
                payload={"row_id": customer_row.id, "chunk_index": 0, "content_hash": "customer"},
            ),
            DatasetRowVectorSearchHit(
                point_id="task-point",
                score=0.9,
                payload={"row_id": task_row.id, "chunk_index": 0, "content_hash": "task"},
            ),
        ]
    )

    response = search_profile_rows(
        user.profile,
        query="renewal risk",
        filters={"status": "Ready"},
        limit=5,
        embedding_provider=provider,
        vector_store=store,
    )

    assert provider.queries == ["renewal risk"]
    assert store.searches == [
        (
            user.profile.id,
            [0.1, 0.2, 0.3],
            (tasks.id, customers.id),
            DatasetStatus.READY,
            False,
            15,
        )
    ]
    assert response["dataset_filters"]["archived"] is False
    assert response["filters"] == {"status": "Ready"}
    assert [result["row"]["id"] for result in response["results"]] == [
        customer_row.id,
        task_row.id,
    ]
    assert response["results"][0]["dataset"]["key"] == str(customers.key)
    assert response["results"][0]["match"]["source"] == "hybrid"
    assert response["results"][1]["match"]["source"] == "vector"


@pytest.mark.django_db
def test_search_profile_rows_logs_no_matches_without_query(django_user_model, monkeypatch):
    from apps.api.services import search_profile_rows

    user = django_user_model.objects.create_user(
        username="profilewidenomatchowner",
        email="profilewidenomatchowner@example.com",
        password="password123",
    )
    log_events = []

    class FakeLogger:
        def info(self, message, **fields):
            log_events.append((message, fields))

    monkeypatch.setattr("apps.api.services.logger", FakeLogger())
    response = search_profile_rows(
        user.profile,
        query="private customer phrase",
        dataset_key="00000000-0000-0000-0000-000000000000",
        embedding_provider=FakeDatasetSearchEmbeddingProvider(),
        vector_store=FakeProfileRowSearchVectorStore([]),
    )

    assert response["count"] == 0
    assert len(log_events) == 1
    message, fields = log_events[0]
    assert message == "Profile row hybrid search complete"
    assert len(fields["query_id"]) == 32
    assert fields["eligible_dataset_count"] == 0
    assert fields["vector_hit_count"] == 0
    assert fields["lexical_candidate_count"] == 0
    assert fields["result_count"] == 0
    assert fields["dataset_filters"]["dataset_key"] == "00000000-0000-0000-0000-000000000000"
    assert "private customer phrase" not in str(fields)


@pytest.mark.django_db
def test_search_profile_rows_skips_incompatible_filter_operator_datasets(django_user_model):
    from apps.api.services import search_profile_rows

    user = django_user_model.objects.create_user(
        username="profilewidefilterowner",
        email="profilewidefilterowner@example.com",
        password="password123",
    )
    scored = Dataset.objects.create(
        profile=user.profile,
        name="Scored accounts",
        original_filename="scored.csv",
        status=DatasetStatus.READY,
        headers=["id", "score", "notes"],
        column_schema={"score": {"type": DatasetColumnType.NUMBER}},
        index_column="id",
    )
    tagged = Dataset.objects.create(
        profile=user.profile,
        name="Tagged accounts",
        original_filename="tagged.csv",
        status=DatasetStatus.READY,
        headers=["id", "score", "notes"],
        column_schema={"score": {"type": DatasetColumnType.TEXT}},
        index_column="id",
    )
    scored_row = DatasetRow.objects.create(
        dataset=scored,
        row_number=1,
        index_value="SCORED-1",
        data={"id": "SCORED-1", "score": "12", "notes": "Target renewal account"},
    )
    tagged_row = DatasetRow.objects.create(
        dataset=tagged,
        row_number=1,
        index_value="TAGGED-1",
        data={"id": "TAGGED-1", "score": "high", "notes": "Target renewal account"},
    )
    response = search_profile_rows(
        user.profile,
        query="target renewal",
        filters={"score": "10"},
        filter_operators={"score": "above"},
        limit=5,
        embedding_provider=FakeDatasetSearchEmbeddingProvider(),
        vector_store=FakeProfileRowSearchVectorStore(
            [
                DatasetRowVectorSearchHit(
                    point_id="tagged-point",
                    score=0.99,
                    payload={"row_id": tagged_row.id, "chunk_index": 0, "content_hash": "tagged"},
                ),
                DatasetRowVectorSearchHit(
                    point_id="scored-point",
                    score=0.95,
                    payload={"row_id": scored_row.id, "chunk_index": 0, "content_hash": "scored"},
                ),
            ]
        ),
    )

    assert [result["row"]["id"] for result in response["results"]] == [scored_row.id]
    assert response["results"][0]["match"]["source"] == "hybrid"


@pytest.mark.django_db
def test_search_profile_dataset_rows_fuses_exact_and_vector_matches(django_user_model):
    from apps.api.services import search_profile_dataset_rows

    user = django_user_model.objects.create_user(
        username="vectorsearchowner",
        email="vectorsearchowner@example.com",
        password="password123",
    )
    dataset = Dataset.objects.create(
        profile=user.profile,
        name="Vector Search Tasks",
        original_filename="tasks.csv",
        status=DatasetStatus.READY,
        headers=["task_id", "status", "title"],
        index_column="task_id",
    )
    exact_row = DatasetRow.objects.create(
        dataset=dataset,
        row_number=1,
        index_value="ROW-VEC-001",
        data={"task_id": "ROW-VEC-001", "status": "Ready", "title": "Define product scope"},
    )
    semantic_row = DatasetRow.objects.create(
        dataset=dataset,
        row_number=2,
        index_value="ROW-VEC-008",
        data={"task_id": "ROW-VEC-008", "status": "Ready", "title": "Remove stale vectors"},
    )
    provider = FakeDatasetSearchEmbeddingProvider()
    store = FakeDatasetSearchVectorStore(
        [
            DatasetRowVectorSearchHit(
                point_id="semantic-point",
                score=0.92,
                payload={"row_id": semantic_row.id, "chunk_index": 0, "content_hash": "sem"},
            ),
            DatasetRowVectorSearchHit(
                point_id="exact-point",
                score=0.5,
                payload={"row_id": exact_row.id, "chunk_index": 0, "content_hash": "exact"},
            ),
        ]
    )

    response = search_profile_dataset_rows(
        user.profile,
        str(dataset.key),
        query="ROW-VEC-001",
        embedding_provider=provider,
        vector_store=store,
    )

    assert provider.queries == ["ROW-VEC-001"]
    assert store.ensure_calls == 0
    assert store.searches == [(str(dataset.key), [0.1, 0.2, 0.3], 30)]
    assert [result["row"]["id"] for result in response["results"]] == [
        exact_row.id,
        semantic_row.id,
    ]
    assert response["results"][0]["match"]["source"] == "hybrid"
    assert response["results"][0]["match"]["lexical_rank"] == 1
    assert response["results"][0]["match"]["vector_rank"] == 2


@pytest.mark.django_db
def test_search_quality_eval_fixtures_keep_expected_rows_on_top(django_user_model):
    from apps.api.services import search_profile_dataset_rows

    user = django_user_model.objects.create_user(
        username="vectorqualityowner",
        email="vectorqualityowner@example.com",
        password="password123",
    )
    dataset = Dataset.objects.create(
        profile=user.profile,
        name="Search Quality Fixtures",
        original_filename="quality.csv",
        status=DatasetStatus.READY,
        headers=["record_id", "kind", "title", "notes"],
        index_column="record_id",
    )
    fixture_rows = {}
    for row_number, data in enumerate(
        [
            {
                "record_id": "ROW-VEC-001",
                "kind": "taskboard",
                "title": "Define v1 hybrid search product scope",
                "notes": "Narrow the first product surface for agent-native dataset search.",
            },
            {
                "record_id": "ROW-VEC-008",
                "kind": "taskboard",
                "title": "Handle deletion, archival, and stale vectors",
                "notes": "Deleted or archived rows must not leak from the retrieval index.",
            },
            {
                "record_id": "ROW-VEC-013",
                "kind": "taskboard",
                "title": "Create search quality fixtures and evals",
                "notes": "Small regression checks should catch ranking quality drift.",
            },
            {
                "record_id": "CRM-001",
                "kind": "crm",
                "title": "Acme renewal risk",
                "notes": "Procurement is stalled and the champion asked for a security review.",
            },
        ],
        start=1,
    ):
        fixture_rows[data["record_id"]] = DatasetRow.objects.create(
            dataset=dataset,
            row_number=row_number,
            index_value=data["record_id"],
            data=data,
        )

    eval_cases = [
        {
            "query": "ROW-VEC-001",
            "expected_top": "ROW-VEC-001",
            "vector_ranked_ids": ["ROW-VEC-008", "ROW-VEC-001"],
        },
        {
            "query": "how do we avoid stale vectors?",
            "expected_top": "ROW-VEC-008",
            "vector_ranked_ids": ["ROW-VEC-008", "ROW-VEC-013"],
        },
        {
            "query": "search quality regression baseline",
            "expected_top": "ROW-VEC-013",
            "vector_ranked_ids": ["ROW-VEC-013", "ROW-VEC-001"],
        },
        {
            "query": "renewal risk procurement",
            "expected_top": "CRM-001",
            "vector_ranked_ids": ["CRM-001", "ROW-VEC-008"],
        },
    ]
    vectors_by_query = {
        case["query"]: [float(index), 0.0, 0.0] for index, case in enumerate(eval_cases, start=1)
    }
    hits_by_vector = {}
    for case in eval_cases:
        hits_by_vector[tuple(vectors_by_query[case["query"]])] = [
            DatasetRowVectorSearchHit(
                point_id=f"{record_id}-point",
                score=1 - (rank * 0.1),
                payload={
                    "row_id": fixture_rows[record_id].id,
                    "chunk_index": 0,
                    "content_hash": f"{record_id}-hash",
                },
            )
            for rank, record_id in enumerate(case["vector_ranked_ids"], start=1)
        ]

    provider = FakeDatasetSearchEmbeddingProvider(vectors_by_query=vectors_by_query)
    store = FakeDatasetSearchEvalVectorStore(hits_by_vector)
    actual_top_by_query = {}
    for case in eval_cases:
        response = search_profile_dataset_rows(
            user.profile,
            str(dataset.key),
            query=case["query"],
            limit=3,
            embedding_provider=provider,
            vector_store=store,
        )
        actual_top_by_query[case["query"]] = response["results"][0]["row"]["index_value"]

    assert actual_top_by_query == {case["query"]: case["expected_top"] for case in eval_cases}
    assert provider.queries == [case["query"] for case in eval_cases]
    assert store.ensure_calls == 0


@pytest.mark.django_db
def test_search_profile_dataset_rows_logs_safe_observability_fields(
    django_user_model,
    monkeypatch,
):
    from apps.api.services import search_profile_dataset_rows

    user = django_user_model.objects.create_user(
        username="vectorlogowner",
        email="vectorlogowner@example.com",
        password="password123",
    )
    dataset = Dataset.objects.create(
        profile=user.profile,
        name="Search Logs",
        original_filename="logs.csv",
        status=DatasetStatus.READY,
        headers=["id", "title"],
        index_column="id",
    )
    row = DatasetRow.objects.create(
        dataset=dataset,
        row_number=1,
        index_value="LOG-1",
        data={"id": "LOG-1", "title": "Safe diagnostic row"},
    )
    log_events = []

    class FakeLogger:
        def info(self, message, **fields):
            log_events.append((message, fields))

    monkeypatch.setattr("apps.api.services.logger", FakeLogger())
    response = search_profile_dataset_rows(
        user.profile,
        str(dataset.key),
        query="private customer phrase",
        embedding_provider=FakeDatasetSearchEmbeddingProvider(),
        vector_store=FakeDatasetSearchVectorStore(
            [
                DatasetRowVectorSearchHit(
                    point_id="log-point",
                    score=0.91,
                    payload={"row_id": row.id, "chunk_index": 0, "content_hash": "log"},
                )
            ]
        ),
    )

    assert response["count"] == 1
    assert len(log_events) == 1
    message, fields = log_events[0]
    assert message == "Dataset hybrid search complete"
    assert len(fields["query_id"]) == 32
    assert fields["dataset_key"] == str(dataset.key)
    assert fields["vector_hit_count"] == 1
    assert fields["lexical_candidate_count"] == 0
    assert fields["result_count"] == 1
    assert fields["hydration_misses"] == 0
    assert fields["top_source"] == "vector"
    assert fields["top_vector_score"] == 0.91
    assert fields["embedding_model"] == "fake-embedding"
    assert fields["embedding_dimensions"] == 3
    assert "private customer phrase" not in str(fields)


@pytest.mark.django_db
def test_search_profile_dataset_rows_applies_canonical_filters_to_vector_hits(
    django_user_model,
):
    from apps.api.services import search_profile_dataset_rows

    user = django_user_model.objects.create_user(
        username="vectorfilterowner",
        email="vectorfilterowner@example.com",
        password="password123",
    )
    dataset = Dataset.objects.create(
        profile=user.profile,
        name="Filtered Search Tasks",
        original_filename="tasks.csv",
        status=DatasetStatus.READY,
        headers=["task_id", "status", "title"],
        column_schema={"status": {"type": "choice", "choices": ["Ready", "Blocked"]}},
        index_column="task_id",
    )
    ready_row = DatasetRow.objects.create(
        dataset=dataset,
        row_number=1,
        index_value="TASK-1",
        data={"task_id": "TASK-1", "status": "Ready", "title": "Allowed semantic match"},
    )
    blocked_row = DatasetRow.objects.create(
        dataset=dataset,
        row_number=2,
        index_value="TASK-2",
        data={"task_id": "TASK-2", "status": "Blocked", "title": "Filtered semantic match"},
    )
    store = FakeDatasetSearchVectorStore(
        [
            DatasetRowVectorSearchHit(
                point_id="blocked-point",
                score=0.99,
                payload={"row_id": blocked_row.id, "chunk_index": 0, "content_hash": "blocked"},
            ),
            DatasetRowVectorSearchHit(
                point_id="ready-point",
                score=0.7,
                payload={"row_id": ready_row.id, "chunk_index": 0, "content_hash": "ready"},
            ),
        ]
    )

    response = search_profile_dataset_rows(
        user.profile,
        str(dataset.key),
        query="semantic",
        filters={"status": "Ready"},
        embedding_provider=FakeDatasetSearchEmbeddingProvider(),
        vector_store=store,
    )

    assert response["filters"] == {"status": "Ready"}
    assert [result["row"]["id"] for result in response["results"]] == [ready_row.id]
    assert response["results"][0]["match"]["point_id"] == "ready-point"


@pytest.mark.django_db
def test_dataset_search_endpoint_delegates_to_search_service(
    client,
    django_user_model,
    monkeypatch,
):
    user = django_user_model.objects.create_user(
        username="vectorendpointowner",
        email="vectorendpointowner@example.com",
        password="password123",
    )
    calls = []

    def search_rows(profile, dataset_key, *, query, filters=None, limit=10):
        calls.append((profile.id, dataset_key, query, filters, limit))
        return {
            "dataset": dataset_key,
            "query": query,
            "filters": filters or {},
            "limit": limit,
            "count": 1,
            "results": [
                {
                    "rank": 1,
                    "score": 0.03,
                    "row": {
                        "id": 123,
                        "row_number": 1,
                        "index_value": "TASK-1",
                        "data": {"task_id": "TASK-1"},
                        "assets": [],
                    },
                    "match": {
                        "source": "hybrid",
                        "vector_rank": 1,
                        "lexical_rank": 1,
                        "snippet": "task_id: TASK-1",
                    },
                }
            ],
        }

    monkeypatch.setattr("apps.api.views.search_profile_dataset_rows", search_rows)

    response = client.post(
        f"/api/datasets/dataset-key/search?api_key={user.profile.key}",
        data={"query": "TASK-1", "filters": {"status": "Ready"}, "limit": 5},
        content_type="application/json",
    )

    assert response.status_code == 200
    assert response.json()["results"][0]["match"]["source"] == "hybrid"
    assert calls == [(user.profile.id, "dataset-key", "TASK-1", {"status": "Ready"}, 5)]


@pytest.mark.django_db
def test_profile_search_endpoint_delegates_to_profile_row_search_service(
    client,
    django_user_model,
    monkeypatch,
):
    user = django_user_model.objects.create_user(
        username="profilesearchendpointowner",
        email="profilesearchendpointowner@example.com",
        password="password123",
    )
    calls = []

    def search_rows(
        profile,
        *,
        query,
        filters=None,
        filter_operators=None,
        dataset_key=None,
        project_key=None,
        section_key=None,
        status=None,
        archived=False,
        sort=None,
        direction=None,
        limit=10,
    ):
        calls.append(
            (
                profile.id,
                query,
                filters,
                filter_operators,
                dataset_key,
                project_key,
                section_key,
                status,
                archived,
                sort,
                direction,
                limit,
            )
        )
        return {
            "query": query,
            "filters": filters or {},
            "filter_operators": filter_operators or {},
            "dataset_filters": {
                "dataset_key": dataset_key,
                "project_key": project_key,
                "section_key": section_key,
                "status": status or "ready",
                "archived": archived,
            },
            "sort": sort or "rank",
            "direction": direction or "desc",
            "limit": limit,
            "count": 1,
            "results": [
                {
                    "rank": 1,
                    "score": 0.03,
                    "dataset": {
                        "key": "dataset-key",
                        "name": "Tasks",
                        "project": None,
                        "section": None,
                        "status": "ready",
                        "headers": ["task_id"],
                        "index_column": "task_id",
                        "row_count": 1,
                        "public_enabled": False,
                        "created_at": None,
                        "updated_at": None,
                        "archived_at": None,
                    },
                    "row": {
                        "id": 123,
                        "row_number": 1,
                        "index_value": "TASK-1",
                        "data": {"task_id": "TASK-1"},
                        "assets": [],
                    },
                    "match": {"source": "hybrid", "vector_rank": 1, "lexical_rank": 1},
                }
            ],
        }

    monkeypatch.setattr("apps.api.views.search_profile_rows", search_rows)

    response = client.post(
        f"/api/search?api_key={user.profile.key}",
        data={
            "query": "stale vectors",
            "filters": {"status": "Ready"},
            "filter_operators": {"status": "is"},
            "dataset_key": "dataset-key",
            "project_key": "project-key",
            "section_key": "section-key",
            "status": "ready",
            "archived": False,
            "sort": "rank",
            "direction": "desc",
            "limit": 5,
        },
        content_type="application/json",
    )

    assert response.status_code == 200
    assert response.json()["results"][0]["dataset"]["key"] == "dataset-key"
    assert calls == [
        (
            user.profile.id,
            "stale vectors",
            {"status": "Ready"},
            {"status": "is"},
            "dataset-key",
            "project-key",
            "section-key",
            "ready",
            False,
            "rank",
            "desc",
            5,
        )
    ]
