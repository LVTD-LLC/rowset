from urllib.parse import quote

from apps.core.attribution import attribution_event_properties, parse_attribution_cookie


def test_attribution_cookie_allowlists_campaign_properties():
    value = quote(
        '{"version":1,"first_touch":{"utm_source":"google","landing_route":"/pricing",'
        '"gclid":"secret-click-id"},"latest_touch":{"utm_campaign":"agents"}}'
    )
    result = parse_attribution_cookie(value)
    assert result == {
        "version": 1,
        "first_touch": {"utm_source": "google", "landing_route": "/pricing"},
        "latest_touch": {"utm_campaign": "agents"},
    }
    assert attribution_event_properties(result) == {
        "attribution_version": 1,
        "utm_campaign": "agents",
        "initial_utm_source": "google",
        "initial_landing_route": "/pricing",
    }


def test_attribution_cookie_rejects_invalid_or_oversized_data():
    assert parse_attribution_cookie("not-json") == {}
    assert parse_attribution_cookie("x" * 4097) == {}
