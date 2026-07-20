import json

from django.test import override_settings

from apps.mcp_server import analytics


def test_sanitize_mcp_event_keeps_parameter_usage_without_dataset_contents():
    event = {
        "event": "$mcp_tool_call",
        "distinct_id": "anonymous-session",
        "properties": {
            "$mcp_parameters": {
                "request": {
                    "method": "tools/call",
                    "params": {
                        "name": "create_dataset_row",
                        "arguments": {
                            "dataset_key": "private-dataset-key",
                            "data": {
                                "email": "customer@example.com",
                                "plan": "enterprise",
                            },
                            "limit": 25,
                            "archived": False,
                        },
                    },
                }
            },
            "$mcp_response": {
                "content": [{"type": "text", "text": "customer@example.com"}],
            },
        },
    }

    sanitized = analytics.sanitize_mcp_event(event)

    assert sanitized["properties"]["$mcp_parameters"] == {
        "argument_count": 4,
        "argument_names": ["archived", "data", "dataset_key", "limit"],
        "argument_types": {
            "archived": "boolean",
            "data": "object",
            "dataset_key": "string",
            "limit": "number",
        },
    }
    assert "$mcp_response" not in sanitized["properties"]
    serialized = json.dumps(sanitized)
    assert "private-dataset-key" not in serialized
    assert "customer@example.com" not in serialized
    assert "enterprise" not in serialized


def test_sanitize_mcp_event_drops_exception_payloads():
    event = {
        "event": "$exception",
        "properties": {"$exception_list": [{"value": "private row failed"}]},
    }

    assert analytics.sanitize_mcp_event(event) is None


@override_settings(POSTHOG_API_KEY="")
def test_configure_mcp_analytics_is_optional(monkeypatch):
    instrument_calls = []
    monkeypatch.setattr(
        analytics,
        "instrument",
        lambda *args, **kwargs: instrument_calls.append((args, kwargs)),
    )

    result = analytics.configure_mcp_analytics(object())

    assert result is None
    assert instrument_calls == []


@override_settings(POSTHOG_API_KEY="phc_test")
def test_configure_mcp_analytics_preserves_the_mcp_contract(monkeypatch):
    sentinel = object()
    instrument_calls = []

    def instrument(server, *, options):
        instrument_calls.append((server, options))
        return sentinel

    monkeypatch.setattr(analytics, "instrument", instrument)
    server = object()

    result = analytics.configure_mcp_analytics(server)

    assert result is sentinel
    assert len(instrument_calls) == 1
    configured_server, options = instrument_calls[0]
    assert configured_server is server
    assert options.context is False
    assert options.enable_exception_autocapture is False
    assert options.before_send is analytics.sanitize_mcp_event
