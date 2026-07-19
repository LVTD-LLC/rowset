import pytest
from django.contrib.auth import get_user_model
from django.test import RequestFactory

from apps.core import signals
from apps.core.choices import ProfileStates
from apps.core.models import Profile


@pytest.mark.django_db
def test_new_profile_enables_choice_colorization_by_default(django_user_model):
    user = django_user_model.objects.create_user(
        username="colorizeduser",
        email="colorizeduser@example.com",
        password="password123",
    )

    assert user.profile.choice_colorization_enabled is True


@pytest.mark.django_db
def test_user_save_does_not_revert_profile_state(sync_state_transitions):
    user_model = get_user_model()
    user = user_model.objects.create_user(
        username="signaluser",
        email="signaluser@example.com",
        password="password123",
    )
    profile = user.profile

    Profile.objects.filter(id=profile.id).update(state=ProfileStates.STRANGER)

    cached_user = user_model.objects.select_related("profile").get(id=user.id)

    Profile.objects.filter(id=profile.id).update(state=ProfileStates.SIGNED_UP)

    cached_user.save()

    profile.refresh_from_db()
    assert profile.state == ProfileStates.SIGNED_UP


@pytest.mark.django_db
def test_user_login_tracks_backend_and_browser_session(profile, monkeypatch):
    tracked = []
    monkeypatch.setattr(
        signals,
        "track_user_logged_in_event",
        lambda *args, **kwargs: tracked.append((args, kwargs)),
    )
    request = RequestFactory().post(
        "/accounts/login/",
        {"posthog_session_id": "form-session"},
        headers={"X-PostHog-Session-ID": "header-session"},
    )
    profile.user.backend = "allauth.account.auth_backends.AuthenticationBackend"

    signals.track_user_logged_in(
        sender=profile.user.__class__,
        request=request,
        user=profile.user,
    )

    assert tracked == [
        (
            (profile,),
            {
                "login_method": "AuthenticationBackend",
                "session_id": "header-session",
            },
        )
    ]
