from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from django.http import HttpRequest
from django.test import SimpleTestCase

from apps.api.views import (
    delete_internal_blog_post,
    get_internal_blog_post,
    get_user_info,
    list_datasets,
    list_internal_blog_posts,
    patch_internal_blog_post,
    publish_internal_blog_post,
    review_internal_blog_post,
    submit_blog_post,
    update_internal_blog_post,
)
from apps.blog.choices import BlogPostStatus
from apps.datasets.choices import DatasetStatus
from apps.datasets.models import Dataset, DatasetRow
from apps.datasets.services import GOOGLE_SHEETS_FILE_TYPE


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


class DatasetListApiUnitTests(SimpleTestCase):
    def test_list_datasets_returns_profile_dataset_metadata_without_rows(self):
        dataset = SimpleNamespace(
            key="6b0fe8f5-89e5-4cb1-a40d-6aa912ba31d7",
            name="Customers",
            original_filename="customers.csv",
            file_type="csv",
            status="ready",
            headers=["email", "name"],
            index_column="email",
            index_generated=False,
            row_count=42,
            public_enabled=True,
            created_at="2026-05-14T00:00:00Z",
            updated_at="2026-05-14T00:01:00Z",
            confirmed_at="2026-05-14T00:02:00Z",
            processed_at="2026-05-14T00:03:00Z",
        )
        queryset = Mock()
        queryset.count.return_value = 1
        queryset.__getitem__ = Mock(return_value=[dataset])
        datasets = Mock()
        datasets.only.return_value = queryset
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
                "original_filename": "customers.csv",
                "file_type": "csv",
                "status": "ready",
                "headers": ["email", "name"],
                "index_column": "email",
                "index_generated": False,
                "row_count": 42,
                "public_enabled": True,
                "created_at": "2026-05-14T00:00:00Z",
                "updated_at": "2026-05-14T00:01:00Z",
                "confirmed_at": "2026-05-14T00:02:00Z",
                "processed_at": "2026-05-14T00:03:00Z",
            }
        ]
        datasets.only.assert_called_once()
        queryset.__getitem__.assert_called_once_with(slice(0, 100, None))


def test_api_key_auth_returns_profile_for_valid_key():
    from apps.api.auth import APIKeyAuth
    from apps.core.models import Profile

    profile = SimpleNamespace(id=11)

    with patch("apps.api.auth.Profile.objects") as objects:
        objects.select_related.return_value.get.return_value = profile
        response = APIKeyAuth().authenticate(HttpRequest(), "secret-key")

    assert response is profile
    objects.select_related.assert_called_once_with("user")
    objects.select_related.return_value.get.assert_called_once_with(key="secret-key")

    with patch("apps.api.auth.Profile.objects") as objects:
        objects.select_related.return_value.get.side_effect = Profile.DoesNotExist
        response = APIKeyAuth().authenticate(HttpRequest(), "bad-key")

    assert response is None


def test_superuser_api_key_auth_eager_loads_user_and_requires_superuser():
    from apps.api.auth import SuperuserAPIKeyAuth
    from apps.core.models import Profile

    superuser_profile = SimpleNamespace(id=11, user=SimpleNamespace(id=21, is_superuser=True))
    regular_profile = SimpleNamespace(id=12, user=SimpleNamespace(id=22, is_superuser=False))

    with patch("apps.api.auth.Profile.objects") as objects:
        objects.select_related.return_value.get.return_value = superuser_profile
        response = SuperuserAPIKeyAuth().authenticate(HttpRequest(), "secret-key")

    assert response is superuser_profile
    objects.select_related.assert_called_once_with("user")
    objects.select_related.return_value.get.assert_called_once_with(key="secret-key")

    with patch("apps.api.auth.Profile.objects") as objects:
        objects.select_related.return_value.get.return_value = regular_profile
        response = SuperuserAPIKeyAuth().authenticate(HttpRequest(), "regular-key")

    assert response is None

    with patch("apps.api.auth.Profile.objects") as objects:
        objects.select_related.return_value.get.side_effect = Profile.DoesNotExist
        response = SuperuserAPIKeyAuth().authenticate(HttpRequest(), "bad-key")

    assert response is None


@pytest.mark.django_db
def test_create_google_sheet_dataset_row_syncs_source(django_user_model):
    from apps.api.services import create_profile_dataset_row

    user = django_user_model.objects.create_user(
        username="sheetapiuser",
        email="sheetapiuser@example.com",
        password="password123",
    )
    dataset = Dataset.objects.create(
        profile=user.profile,
        name="People",
        original_filename="people.csv",
        file_type=GOOGLE_SHEETS_FILE_TYPE,
        source_url="https://docs.google.com/spreadsheets/d/sheet123/edit#gid=456",
        status=DatasetStatus.READY,
        headers=["email", "name"],
        index_column="email",
        row_count=0,
    )

    with patch("apps.api.services.sync_dataset_to_google_sheet", return_value="synced") as sync:
        result = create_profile_dataset_row(
            user.profile,
            str(dataset.key),
            {"email": "ada@example.com", "name": "Ada"},
        )

    sync.assert_called_once()
    assert sync.call_args.args[0].id == dataset.id
    assert "source_sync" not in result


@pytest.mark.django_db
def test_update_and_delete_google_sheet_dataset_rows_sync_source(django_user_model):
    from apps.api.services import delete_profile_dataset_row, patch_profile_dataset_row

    user = django_user_model.objects.create_user(
        username="sheetapiuser2",
        email="sheetapiuser2@example.com",
        password="password123",
    )
    dataset = Dataset.objects.create(
        profile=user.profile,
        name="People",
        original_filename="people.csv",
        file_type=GOOGLE_SHEETS_FILE_TYPE,
        source_url="https://docs.google.com/spreadsheets/d/sheet123/edit#gid=456",
        status=DatasetStatus.READY,
        headers=["email", "name"],
        index_column="email",
        row_count=1,
    )
    row = DatasetRow.objects.create(
        dataset=dataset,
        row_number=1,
        index_value="ada@example.com",
        data={"email": "ada@example.com", "name": "Ada"},
    )

    with patch("apps.api.services.sync_dataset_to_google_sheet", return_value="synced") as sync:
        patch_profile_dataset_row(user.profile, str(dataset.key), row.id, {"name": "Ada L"})
        delete_profile_dataset_row(user.profile, str(dataset.key), row.id)

    assert sync.call_count == 2


@pytest.mark.django_db
def test_google_sheet_sync_failure_returns_success_with_warning(django_user_model):
    from apps.api.services import create_profile_dataset_row
    from apps.datasets.google_sheets import GoogleSheetsSyncError

    user = django_user_model.objects.create_user(
        username="sheetapiuser3",
        email="sheetapiuser3@example.com",
        password="password123",
    )
    dataset = Dataset.objects.create(
        profile=user.profile,
        name="People",
        original_filename="people.csv",
        file_type=GOOGLE_SHEETS_FILE_TYPE,
        source_url="https://docs.google.com/spreadsheets/d/sheet123/edit#gid=456",
        status=DatasetStatus.READY,
        headers=["email", "name"],
        index_column="email",
        row_count=0,
    )

    with patch(
        "apps.api.services.sync_dataset_to_google_sheet",
        side_effect=GoogleSheetsSyncError("Could not reach Google Sheets."),
    ):
        result = create_profile_dataset_row(
            user.profile,
            str(dataset.key),
            {"email": "ada@example.com", "name": "Ada"},
        )

    assert result["status"] == "success"
    assert result["source_sync"] == {
        "status": "failed",
        "message": "Could not reach Google Sheets.",
    }
    assert DatasetRow.objects.filter(dataset=dataset, index_value="ada@example.com").exists()
