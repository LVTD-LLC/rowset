import pytest
from allauth.account.models import EmailAddress

from apps.core.analytics import ROWSET_TRIAL_REWARD_CLAIMED
from apps.core.choices import TrialReward
from apps.core.models import TrialRewardClaim

pytestmark = pytest.mark.django_db


def test_trial_rewards_page_shows_the_four_tasks(auth_client):
    response = auth_client.get("/trial-rewards")

    content = response.content.decode()
    assert response.status_code == 200
    assert "Earn extra trial days" in content
    assert "Verify your email" in content
    assert "Star Rowset on GitHub" in content
    assert "Join our Discord community" in content
    assert "Follow Rasul on X" in content
    assert content.count("+3 days") == 4
    assert "0 of 4 complete" in content
    assert "https://github.com/LVTD-LLC/rowset" in content
    assert "https://discord.gg/kzaHJBwMQ" in content
    assert "https://x.com/rasulkireev" in content
    assert "Open task" not in content
    assert "I did this" not in content
    assert "Star on GitHub — earn 3 days" in content
    assert "Join Discord — earn 3 days" in content
    assert "Follow on X — earn 3 days" in content
    assert content.count("data-reward-url=") == 3


def test_trial_rewards_page_requires_sign_in(client):
    response = client.get("/trial-rewards")

    assert response.status_code == 302
    assert response["Location"].startswith("/accounts/login/")


def test_htmx_claim_extends_trial_and_refreshes_reward_progress(
    auth_client,
    profile,
    monkeypatch,
):
    tracked_events = []
    monkeypatch.setattr(
        "apps.core.views.track_activation_event",
        lambda profile, event_name, properties, source_function=None: tracked_events.append(
            (profile.id, event_name, properties, source_function)
        ),
    )
    profile.trial_started_at = profile.created_at
    profile.trial_ends_at = profile.created_at
    profile.save(update_fields=["trial_started_at", "trial_ends_at", "updated_at"])

    response = auth_client.post(
        "/trial-rewards/github_star/claim",
        HTTP_HX_REQUEST="true",
    )

    profile.refresh_from_db()
    content = response.content.decode()
    assert response.status_code == 200
    assert "Star Rowset on GitHub" in content
    assert "Claimed" in content
    assert "1 of 4 complete" in content
    assert TrialRewardClaim.objects.filter(
        profile=profile,
        reward=TrialReward.GITHUB_STAR,
    ).exists()
    assert tracked_events == [
        (
            profile.id,
            ROWSET_TRIAL_REWARD_CLAIMED,
            {"reward": TrialReward.GITHUB_STAR, "days_added": 3},
            "claim_trial_reward_view",
        )
    ]


def test_non_htmx_claim_reports_the_three_day_reward(auth_client):
    response = auth_client.post(
        "/trial-rewards/github_star/claim",
        follow=True,
    )

    content = response.content.decode()
    assert response.status_code == 200
    assert "Added 3 extra days to your Rowset trial." in content


def test_unverified_email_claim_returns_an_actionable_card(auth_client, profile):
    EmailAddress.objects.update_or_create(
        user=profile.user,
        email=profile.user.email,
        defaults={"primary": True, "verified": False},
    )

    response = auth_client.post(
        "/trial-rewards/email_verified/claim",
        HTTP_HX_REQUEST="true",
    )

    content = response.content.decode()
    assert response.status_code == 200
    assert "Verify your email before claiming this reward" in content
    assert not TrialRewardClaim.objects.filter(profile=profile).exists()


def test_settings_links_to_trial_rewards(auth_client):
    response = auth_client.get("/settings")

    assert response.status_code == 200
    content = response.content.decode()
    assert 'href="/trial-rewards"' in content
    assert "Earn up to 12 extra trial days" in content
