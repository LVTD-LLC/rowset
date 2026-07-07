from fastmcp.exceptions import ToolError

from rowset.sentry_utils import before_send


def test_before_send_drops_expected_mcp_tool_errors():
    event = {"exception": {"values": [{"type": "ToolError"}]}}
    hint = {
        "exc_info": (
            ToolError,
            ToolError(
                '{"code": "VALIDATION_ERROR", "details": {"http_status": 400}, '
                '"message": "Invalid input."}'
            ),
            None,
        )
    }

    assert before_send(event, hint) is None


def test_before_send_keeps_server_mcp_tool_errors():
    event = {"exception": {"values": [{"type": "ToolError"}]}}
    hint = {
        "exc_info": (
            ToolError,
            ToolError(
                '{"code": "ROWSET_SERVICE_ERROR", "details": {"http_status": 500}, '
                '"message": "Backend failed."}'
            ),
            None,
        )
    }

    assert before_send(event, hint) == event


def test_before_send_keeps_unstructured_mcp_tool_errors():
    event = {"exception": {"values": [{"type": "ToolError"}]}}
    hint = {"exc_info": (ToolError, ToolError("unexpected"), None)}

    assert before_send(event, hint) == event


def test_before_send_keeps_non_tool_errors():
    event = {"exception": {"values": [{"type": "ValueError"}]}}
    hint = {"exc_info": (ValueError, ValueError("unexpected"), None)}

    assert before_send(event, hint) == event
