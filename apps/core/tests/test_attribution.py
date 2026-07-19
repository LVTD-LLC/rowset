from urllib.parse import quote

from apps.core.attribution import attribution_event_properties, parse_attribution_cookie


def test_attribution_cookie_allowlists_campaign_properties():
    value = quote(
        '{"version":1,"first_touch":{"utm_source":"google","landing_route":"/pricing",'
        '"referrer":"https://News.Example/path?secret=value","gclid":"secret-click-id"},'
        '"latest_touch":{"campaign_id":"agent-launch",'
        '"utm_campaign":"agents"}}'
    )
    result = parse_attribution_cookie(value)
    assert result == {
        "version": 1,
        "first_touch": {
            "utm_source": "google",
            "landing_route": "/pricing",
            "referrer": "https://news.example",
        },
        "latest_touch": {"campaign_id": "agent-launch", "utm_campaign": "agents"},
    }
    assert attribution_event_properties(result) == {
        "attribution_version": 1,
        "campaign_id": "agent-launch",
        "utm_campaign": "agents",
        "initial_utm_source": "google",
        "initial_landing_route": "/pricing",
        "initial_referrer": "https://news.example",
    }


def test_attribution_cookie_rejects_invalid_or_oversized_data():
    assert parse_attribution_cookie("not-json") == {}
    assert parse_attribution_cookie("x" * 4097) == {}

    unsafe_referrer = quote(
        '{"version":1,"first_touch":{"utm_source":"google",'
        '"referrer":"https://user:password@example.com/private"}}'
    )
    assert parse_attribution_cookie(unsafe_referrer) == {
        "version": 1,
        "first_touch": {"utm_source": "google"},
    }
