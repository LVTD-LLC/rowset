import pytest
from fastmcp.exceptions import ToolError

from apps.api.errors import DatasetServiceError
from rowset.sentry_utils import before_send


def _raise_tool_error_from_service_error(status_code: int):
    try:
        raise DatasetServiceError(status_code, "Dataset not found.")
    except DatasetServiceError as exc:
        raise ToolError(
            f'{{"code": "DATASET_NOT_FOUND", "details": {{"http_status": {status_code}}}}}'
        ) from exc


def test_before_send_drops_expected_mcp_tool_errors():
    with pytest.raises(ToolError) as exc_info:
        _raise_tool_error_from_service_error(404)

    event = {"exception": {"values": [{"type": "ToolError"}]}}
    hint = {
        "exc_info": (
            ToolError,
            exc_info.value,
            exc_info.value.__traceback__,
        )
    }

    assert before_send(event, hint) is None


def test_before_send_keeps_server_mcp_tool_errors():
    with pytest.raises(ToolError) as exc_info:
        _raise_tool_error_from_service_error(500)

    event = {"exception": {"values": [{"type": "ToolError"}]}}
    hint = {
        "exc_info": (
            ToolError,
            exc_info.value,
            exc_info.value.__traceback__,
        )
    }

    assert before_send(event, hint) is event
