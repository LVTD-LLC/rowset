from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from django.http import HttpRequest
from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from apps.api.views import (
    delete_internal_blog_post,
    get_internal_blog_post,
    get_user_info,
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
from apps.datasets.choices import DatasetStatus
from apps.datasets.models import Dataset, DatasetRow, Project


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
        active_datasets.select_related.assert_called_once_with("project")
        active_datasets.select_related.return_value.only.assert_called_once()
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
            }
        ]
        projects.annotate.assert_called_once()
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


def test_superuser_api_key_auth_eager_loads_user_and_requires_superuser():
    from apps.api.auth import SuperuserAPIKeyAuth

    superuser_profile = SimpleNamespace(id=11, user=SimpleNamespace(id=21, is_superuser=True))
    regular_profile = SimpleNamespace(id=12, user=SimpleNamespace(id=22, is_superuser=False))

    with patch(
        "apps.api.auth.resolve_api_key_profile",
        return_value=(superuser_profile, None),
    ) as resolver:
        response = SuperuserAPIKeyAuth().authenticate(HttpRequest(), "secret-key")

    assert response is superuser_profile
    resolver.assert_called_once_with("secret-key")

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
    Dataset.objects.filter(id=dataset.id).update(
        updated_at=datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    )

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
