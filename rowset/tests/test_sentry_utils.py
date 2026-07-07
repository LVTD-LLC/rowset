from fastmcp.exceptions import ToolError

from rowset.sentry_utils import before_send


def test_before_send_drops_expected_mcp_tool_errors():
    event = {"exception": {"values": [{"type": "ToolError"}]}}
    hint = {"exc_info": (ToolError, ToolError("validation failed"), None)}

    assert before_send(event, hint) is None


def test_before_send_keeps_non_tool_errors():
    event = {"exception": {"values": [{"type": "ValueError"}]}}
    hint = {"exc_info": (ValueError, ValueError("unexpected"), None)}

    assert before_send(event, hint) == event
