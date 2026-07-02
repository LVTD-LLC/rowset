from uuid import UUID

import pytest
from django.test import override_settings

from apps.api.services import DatasetServiceError
from apps.core import services as core_services
from apps.core.choices import FeedbackSource
from apps.core.models import Feedback
from apps.core.services import (
    FEEDBACK_DATASET_HEADERS,
    FEEDBACK_DATASET_KEY,
    submit_profile_feedback,
)
from apps.datasets.choices import DatasetStatus
from apps.datasets.models import Dataset, Project, ProjectSection


@pytest.mark.django_db
@override_settings(
    SITE_URL="https://rowset.example",
)
def test_submit_profile_feedback_creates_feedback_dataset_row(
    profile,
):
    result = submit_profile_feedback(
        profile=profile,
        feedback=" Please add CSV diffs. ",
        page="/datasets/",
        source=FeedbackSource.MCP,
        metadata={"tool": "submit_feedback", "category": "exports"},
    )

    project = Project.objects.get(profile=profile, name="Rowset")
    section = ProjectSection.objects.get(profile=profile, project=project, name="CX")
    dataset = Dataset.objects.get(
        profile=profile,
        project=project,
        section=section,
        name="Feedback",
    )
    row = dataset.rows.get(index_value=str(result.feedback.id))

    assert result.feedback.feedback == "Please add CSV diffs."
    assert result.feedback.source == FeedbackSource.MCP
    assert result.feedback.metadata == {
        "tool": "submit_feedback",
        "category": "exports",
        "rowset_row_url": result.row_url,
    }
    assert result.dataset == dataset
    assert result.row == row
    assert result.row_url == f"https://rowset.example/datasets/{dataset.key}/rows/{row.id}/"
    assert dataset.headers == [
        "feedback_id",
        "submitted_at",
        "submitted_via",
        "user_email",
        "profile_id",
        "page",
        "context",
        "feedback",
    ]
    assert dataset.index_column == "feedback_id"
    assert row.data == {
        "feedback_id": str(result.feedback.id),
        "submitted_at": result.feedback.created_at.isoformat(),
        "submitted_via": "mcp",
        "user_email": profile.user.email,
        "profile_id": str(profile.id),
        "page": "/datasets/",
        "context": '{"category":"exports","tool":"submit_feedback"}',
        "feedback": "Please add CSV diffs.",
    }


@pytest.mark.django_db
@override_settings(
    SITE_URL="https://rowset.example",
)
def test_submit_profile_feedback_reuses_project_section_and_dataset(
    profile,
):
    first = submit_profile_feedback(
        profile=profile,
        feedback="First note",
        page="/one/",
        source=FeedbackSource.BROWSER,
    )
    second = submit_profile_feedback(
        profile=profile,
        feedback="Second note",
        page="/two/",
        source=FeedbackSource.MCP,
    )

    assert first.dataset == second.dataset
    assert Project.objects.filter(profile=profile, name__iexact="Rowset").count() == 1
    assert ProjectSection.objects.filter(profile=profile, name__iexact="CX").count() == 1
    assert Dataset.objects.filter(profile=profile, name__iexact="Feedback").count() == 1
    assert first.dataset.rows.count() == 2
    assert (
        first.dataset.rows.get(index_value=str(first.feedback.id)).data["submitted_via"]
        == "browser"
    )
    assert (
        first.dataset.rows.get(index_value=str(second.feedback.id)).data["submitted_via"] == "mcp"
    )


@pytest.mark.django_db
@override_settings(
    SITE_URL="https://rowset.example",
)
def test_submit_profile_feedback_writes_to_configured_dataset(django_user_model):
    owner_user = django_user_model.objects.create_user(
        username="rasul",
        email="rasul@lvtd.dev",
        password="password123",
    )
    submitter_user = django_user_model.objects.create_user(
        username="external-agent-user",
        email="external-agent@example.com",
        password="password123",
    )
    configured_dataset = Dataset.objects.create(
        profile=owner_user.profile,
        key=UUID(FEEDBACK_DATASET_KEY),
        name="Feedback",
        original_filename="Created via API",
        file_type="api",
        status=DatasetStatus.READY,
        headers=FEEDBACK_DATASET_HEADERS,
        index_column="feedback_id",
        row_count=0,
    )

    result = submit_profile_feedback(
        profile=submitter_user.profile,
        feedback="Centralize this feedback.",
        page="mcp:submit_feedback",
        source=FeedbackSource.MCP,
        metadata={"tool": "submit_feedback"},
    )

    row = configured_dataset.rows.get(index_value=str(result.feedback.id))

    assert result.dataset == configured_dataset
    assert configured_dataset.profile == owner_user.profile
    assert result.feedback.profile == submitter_user.profile
    assert result.feedback.metadata == {
        "tool": "submit_feedback",
        "rowset_row_url": result.row_url,
    }
    assert row.data["user_email"] == "external-agent@example.com"
    assert row.data["profile_id"] == str(submitter_user.profile.id)
    assert row.data["feedback"] == "Centralize this feedback."


@pytest.mark.django_db
@override_settings(SITE_URL="https://rowset.example")
def test_submit_profile_feedback_recovers_from_concurrent_dataset_create(
    profile,
    monkeypatch,
):
    first = submit_profile_feedback(profile=profile, feedback="First note")
    real_active_feedback_dataset = core_services._active_feedback_dataset
    active_calls = 0

    def stale_read_then_existing_dataset(profile, project, section):
        nonlocal active_calls
        active_calls += 1
        if active_calls == 1:
            return None
        return real_active_feedback_dataset(profile, project, section)

    def raise_dataset_name_conflict(*args, **kwargs):
        raise DatasetServiceError(409, "Dataset name already exists.")

    monkeypatch.setattr(
        "apps.core.services._active_feedback_dataset",
        stale_read_then_existing_dataset,
    )
    monkeypatch.setattr("apps.core.services.create_profile_dataset", raise_dataset_name_conflict)

    second = submit_profile_feedback(profile=profile, feedback="Second note")

    assert second.dataset == first.dataset
    assert first.dataset.rows.count() == 2
    assert first.dataset.rows.get(index_value=str(second.feedback.id)).data["feedback"] == (
        "Second note"
    )


@pytest.mark.django_db
def test_submit_profile_feedback_preserves_feedback_when_dataset_row_write_fails(
    profile,
    monkeypatch,
):
    def raise_dataset_row_error(*args, **kwargs):
        raise DatasetServiceError(503, "Feedback dataset row could not be created.")

    monkeypatch.setattr("apps.core.services.create_profile_dataset_row", raise_dataset_row_error)

    with pytest.raises(DatasetServiceError, match="Feedback dataset row could not be created"):
        submit_profile_feedback(
            profile=profile,
            feedback="Preserve this feedback even if Rowset row creation fails.",
            metadata={"tool": "submit_feedback"},
        )

    feedback = Feedback.objects.get(profile=profile)
    assert feedback.feedback == "Preserve this feedback even if Rowset row creation fails."
    assert feedback.metadata == {"tool": "submit_feedback"}
    assert Dataset.objects.count() == 0


@pytest.mark.django_db
def test_submit_profile_feedback_rejects_blank_feedback(profile):
    with pytest.raises(ValueError, match="Feedback is required"):
        submit_profile_feedback(profile=profile, feedback="   ", page="/")

    assert Feedback.objects.count() == 0
    assert Dataset.objects.count() == 0
