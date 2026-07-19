import pytest

from apps.core.services import mark_profile_setup_completed


@pytest.mark.django_db
def test_setup_completion_tracks_the_real_transition_once(profile, monkeypatch):
    tracked = []
    monkeypatch.setattr(
        "apps.core.services.track_activation_event",
        lambda profile, event_name, properties, **_kwargs: tracked.append(
            (profile.id, event_name, properties)
        ),
    )

    first = mark_profile_setup_completed(
        profile.id,
        interface="mcp",
        agent_api_key_id=12,
        agent_api_key_access_level="read_write",
    )
    second = mark_profile_setup_completed(
        profile.id,
        interface="rest",
        agent_api_key_id=12,
        agent_api_key_access_level="read_write",
    )

    profile.refresh_from_db()
    assert first is True
    assert second is False
    assert profile.setup_completed_at is not None
    assert tracked == [
        (
            profile.id,
            "rowset_agent_setup_completed",
            {
                "interface": "mcp",
                "agent_api_key_present": True,
                "agent_api_key_id": 12,
                "agent_api_key_access_level": "read_write",
            },
        )
    ]
