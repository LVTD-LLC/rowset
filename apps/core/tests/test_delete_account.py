import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse


@pytest.mark.django_db
def test_delete_account_requires_confirmation(auth_client, user):
    url = reverse("delete_account")

    response = auth_client.post(url, data={"confirmation": "nope"})
    assert response.status_code == 302

    # user should still exist
    assert get_user_model().objects.filter(id=user.id).exists()


@pytest.mark.django_db
def test_delete_account_deletes_user(auth_client, user):
    url = reverse("delete_account")

    response = auth_client.post(url, data={"confirmation": "DELETE"})

    assert response.status_code == 302
    assert response["Location"].startswith(reverse("landing"))

    assert not get_user_model().objects.filter(id=user.id).exists()


@pytest.mark.django_db
@override_settings(POSTHOG_API_KEY="phc_test")
def test_delete_account_queues_snapshot_event_after_deletion_commit(
    auth_client,
    user,
    monkeypatch,
    django_capture_on_commit_callbacks,
):
    queued = []
    monkeypatch.setattr(
        "apps.core.analytics.async_task",
        lambda path, **kwargs: queued.append((path, kwargs)),
    )
    profile_id = user.profile.id
    profile_state = user.profile.state

    with django_capture_on_commit_callbacks(execute=True):
        response = auth_client.post(
            reverse("delete_account"),
            data={"confirmation": "DELETE", "posthog_session_id": "session-123"},
        )

    assert response.status_code == 302
    assert not get_user_model().objects.filter(id=user.id).exists()
    assert queued == [
        (
            "apps.core.tasks.track_account_deleted_event",
            {
                "profile_id": profile_id,
                "current_state": profile_state,
                "session_id": "session-123",
                "group": "Track Activation Event",
            },
        )
    ]
