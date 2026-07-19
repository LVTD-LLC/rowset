from types import SimpleNamespace

from django.test import override_settings

from apps.pages import views as page_views


@override_settings(POSTHOG_API_KEY="phc_test")
def test_landing_context_does_not_create_posthog_alias():
    profile = SimpleNamespace(id=42)
    view = page_views.LandingPageView()
    view.request = SimpleNamespace(
        user=SimpleNamespace(is_authenticated=True, profile=profile),
        COOKIES={"sessionid": "private"},
        GET={},
    )
    view.get_context_data()


def test_signup_tracking_uses_single_canonical_event(monkeypatch):
    tracked = []
    monkeypatch.setattr(
        page_views,
        "track_activation_event",
        lambda *args, **kwargs: tracked.append((args, kwargs)),
    )

    profile = SimpleNamespace(
        id=42,
        user=SimpleNamespace(email="user@example.com", username="user"),
    )
    tracking = page_views.SignupTrackingMixin()
    tracking.user = SimpleNamespace(profile=profile)
    tracking.request = SimpleNamespace(COOKIES={"sessionid": "private"})
    tracking._track_signup()

    assert len(tracked) == 1
    assert tracked[0][0][1] == "rowset_signup_completed"
    assert tracked[0][0][2] == {"signup_method": "signup"}


def test_signup_tracking_only_persists_attribution_with_granted_consent(monkeypatch):
    synchronized = []
    monkeypatch.setattr(
        page_views,
        "sync_profile_marketing_attribution",
        lambda *args: synchronized.append(args),
    )
    monkeypatch.setattr(page_views, "track_activation_event", lambda *args, **kwargs: None)
    profile = SimpleNamespace(id=42)
    tracking = page_views.SignupTrackingMixin()
    tracking.user = SimpleNamespace(profile=profile)

    for consent in (None, "denied"):
        cookies = {"rowset_marketing_attribution": "encoded-attribution"}
        if consent:
            cookies["rowset_analytics_consent"] = consent
        tracking.request = SimpleNamespace(COOKIES=cookies)
        tracking._track_signup()

    assert synchronized == []

    tracking.request = SimpleNamespace(
        COOKIES={
            "rowset_analytics_consent": "granted",
            "rowset_marketing_attribution": "encoded-attribution",
        }
    )
    tracking._track_signup()

    assert synchronized == [(profile, "encoded-attribution")]
