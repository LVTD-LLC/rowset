from django.test import override_settings

from rowset import traffic_analytics


@override_settings(POSTHOG_API_KEY="phc_test", ENVIRONMENT="prod")
def test_capture_traffic_request_emits_personless_privacy_bounded_event(monkeypatch):
    captures = []
    monkeypatch.setattr(
        traffic_analytics.posthog,
        "capture",
        lambda event, **kwargs: captures.append((event, kwargs)),
    )

    captured = traffic_analytics.capture_traffic_request(
        content_group="public_dataset",
        content_id="pd_v1_0123456789abcdef01234567",
        content_surface="preview",
        outcome="success",
        request_interface="web",
        route="public_dataset",
        status_class="2xx",
        traffic_category="crawler",
    )

    assert captured is True
    assert captures == [
        (
            "rowset_traffic_request_observed",
            {
                "disable_geoip": True,
                "properties": {
                    "$process_person_profile": False,
                    "content_group": "public_dataset",
                    "content_id": "pd_v1_0123456789abcdef01234567",
                    "content_surface": "preview",
                    "environment": "prod",
                    "event_version": 1,
                    "outcome": "success",
                    "request_interface": "web",
                    "route": "public_dataset",
                    "status_class": "2xx",
                    "traffic_category": "crawler",
                },
            },
        )
    ]
    assert "distinct_id" not in captures[0][1]


@override_settings(POSTHOG_API_KEY="phc_test", ENVIRONMENT="prod")
def test_capture_traffic_request_isolates_the_final_sdk_payload(monkeypatch):
    enqueued = []
    client = traffic_analytics.posthog.Client("phc_test", send=False)
    monkeypatch.setattr(traffic_analytics.posthog, "default_client", client)
    monkeypatch.setattr(
        client,
        "_enqueue",
        lambda message, disable_geoip: enqueued.append((message, disable_geoip)),
    )

    with traffic_analytics.posthog.new_context(fresh=True):
        traffic_analytics.posthog.identify_context("private-profile-id")
        traffic_analytics.posthog.tag("private_context", "secret-value")
        captured = traffic_analytics.capture_traffic_request(
            outcome="success",
            request_interface="web",
            route="pricing",
            status_class="2xx",
            traffic_category="crawler",
        )

    assert captured is True
    message, disable_geoip = enqueued[0]
    assert disable_geoip is True
    assert message["distinct_id"] != "private-profile-id"
    assert message["properties"]["$process_person_profile"] is False
    assert "private_context" not in message["properties"]
    assert "secret-value" not in str(message)


@override_settings(POSTHOG_API_KEY="phc_test")
def test_capture_traffic_request_omits_unbounded_optional_values(monkeypatch):
    captures = []
    monkeypatch.setattr(
        traffic_analytics.posthog,
        "capture",
        lambda event, **kwargs: captures.append((event, kwargs)),
    )

    captured = traffic_analytics.capture_traffic_request(
        content_group="private_dataset",
        content_id="raw-public-key",
        content_surface="private_rows",
        outcome="success",
        request_interface="web",
        route="pricing?token=private-query-value",
        status_class="2xx",
        traffic_category="human",
    )

    assert captured is True
    properties = captures[0][1]["properties"]
    assert "content_group" not in properties
    assert "content_id" not in properties
    assert "content_surface" not in properties
    assert "route" not in properties
    assert "private" not in str(properties)


@override_settings(POSTHOG_API_KEY="phc_test")
def test_capture_traffic_request_rejects_unbounded_required_values(monkeypatch):
    captures = []
    monkeypatch.setattr(
        traffic_analytics.posthog,
        "capture",
        lambda *args, **kwargs: captures.append((args, kwargs)),
    )

    captured = traffic_analytics.capture_traffic_request(
        outcome="success",
        request_interface="private-interface",
        route="pricing",
        status_class="2xx",
        traffic_category="guessed_person",
    )

    assert captured is False
    assert captures == []


@override_settings(POSTHOG_API_KEY="phc_test")
def test_capture_traffic_request_isolates_posthog_failures(monkeypatch, captured_events):
    def fail_capture(*_args, **_kwargs):
        raise RuntimeError("private PostHog failure")

    monkeypatch.setattr(traffic_analytics.posthog, "capture", fail_capture)

    captured = traffic_analytics.capture_traffic_request(
        outcome="failure",
        request_interface="rest",
        route="api-1.0.0:datasets",
        status_class="5xx",
        traffic_category="api_client",
    )

    assert captured is False
    event = captured_events.event("posthog.traffic_request.failed")
    assert event["error_type"] == "RuntimeError"
    assert "private PostHog failure" not in str(event)


@override_settings(POSTHOG_API_KEY="")
def test_capture_traffic_request_is_optional_without_posthog_key(monkeypatch):
    captures = []
    monkeypatch.setattr(
        traffic_analytics.posthog,
        "capture",
        lambda *args, **kwargs: captures.append((args, kwargs)),
    )

    captured = traffic_analytics.capture_traffic_request(
        outcome="success",
        request_interface="web",
        route="landing",
        status_class="2xx",
        traffic_category="human",
    )

    assert captured is False
    assert captures == []
