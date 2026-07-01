import pytest
from django.test import override_settings

from apps.core.models import EmailSent, Feedback
from apps.core.services import submit_profile_feedback
from apps.datasets.models import Dataset, Project, ProjectSection


@pytest.fixture
def sent_feedback_messages(monkeypatch):
    messages = []

    def fake_send_mail(subject, message, from_email, recipient_list, fail_silently=False):
        messages.append(
            {
                "subject": subject,
                "message": message,
                "from_email": from_email,
                "recipient_list": recipient_list,
                "fail_silently": fail_silently,
            }
        )
        return 1

    monkeypatch.setattr("apps.core.models.send_mail", fake_send_mail)
    return messages


@pytest.mark.django_db
@override_settings(
    DEFAULT_FROM_EMAIL="feedback@rowset.example",
    SITE_URL="https://rowset.example",
)
def test_submit_profile_feedback_creates_feedback_dataset_row(
    profile,
    sent_feedback_messages,
):
    result = submit_profile_feedback(
        profile,
        " Please add CSV diffs. ",
        page="/datasets/",
        submitted_via="mcp",
        context={"tool": "submit_feedback", "category": "exports"},
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
    assert sent_feedback_messages[0]["subject"] == "New Feedback Submitted"
    assert "User: testuser@example.com" in sent_feedback_messages[0]["message"]
    assert "Feedback: Please add CSV diffs." in sent_feedback_messages[0]["message"]
    assert "Submitted via: mcp" in sent_feedback_messages[0]["message"]
    assert (
        'Context: {"category":"exports","tool":"submit_feedback"}'
        in sent_feedback_messages[0]["message"]
    )
    assert f"Rowset row: {result.row_url}" in sent_feedback_messages[0]["message"]
    assert EmailSent.objects.filter(
        email_address="feedback@rowset.example",
        profile=profile,
    ).count() == 1


@pytest.mark.django_db
@override_settings(
    DEFAULT_FROM_EMAIL="feedback@rowset.example",
    SITE_URL="https://rowset.example",
)
def test_submit_profile_feedback_reuses_project_section_and_dataset(
    profile,
    sent_feedback_messages,
):
    first = submit_profile_feedback(profile, "First note", page="/one/", submitted_via="web")
    second = submit_profile_feedback(profile, "Second note", page="/two/", submitted_via="mcp")

    assert first.dataset == second.dataset
    assert Project.objects.filter(profile=profile, name__iexact="Rowset").count() == 1
    assert ProjectSection.objects.filter(profile=profile, name__iexact="CX").count() == 1
    assert Dataset.objects.filter(profile=profile, name__iexact="Feedback").count() == 1
    assert first.dataset.rows.count() == 2
    assert first.dataset.rows.get(index_value=str(first.feedback.id)).data["submitted_via"] == "web"
    assert (
        first.dataset.rows.get(index_value=str(second.feedback.id)).data["submitted_via"]
        == "mcp"
    )
    assert len(sent_feedback_messages) == 2


@pytest.mark.django_db
def test_submit_profile_feedback_rejects_blank_feedback(profile):
    with pytest.raises(ValueError, match="Feedback is required"):
        submit_profile_feedback(profile, "   ", page="/")

    assert Feedback.objects.count() == 0
    assert Dataset.objects.count() == 0
