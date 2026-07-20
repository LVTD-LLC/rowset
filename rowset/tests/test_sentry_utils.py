import asyncio
import logging

import pytest
from fastmcp.exceptions import ToolError
from sentry_sdk.integrations.logging import LoggingIntegration

from apps.api.errors import DatasetServiceError
from rowset.sentry_utils import CustomLoggingIntegration, before_send


def _raise_tool_error_from_service_error(status_code: int):
    try:
        raise DatasetServiceError(status_code, "Dataset not found.")
    except DatasetServiceError as exc:
        raise ToolError(
            f'{{"code": "DATASET_NOT_FOUND", "details": {{"http_status": {status_code}}}}}'
        ) from exc


def _logging_integration(monkeypatch):
    handled = []
    monkeypatch.setattr(
        LoggingIntegration,
        "_handle_record",
        lambda self, record: handled.append(record),
    )
    return CustomLoggingIntegration(level=logging.INFO, event_level=logging.ERROR), handled


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


def test_before_send_drops_expected_asyncio_cancellations():
    cancellation = asyncio.CancelledError()
    event = {"exception": {"values": [{"type": "CancelledError"}]}}
    hint = {
        "exc_info": (
            asyncio.CancelledError,
            cancellation,
            cancellation.__traceback__,
        )
    }

    assert before_send(event, hint) is None


def test_custom_logging_integration_skips_records_already_sent_by_structlog(monkeypatch):
    integration, handled = _logging_integration(monkeypatch)
    record = logging.LogRecord(
        "rowset.rowset.task_logging",
        logging.ERROR,
        __file__,
        1,
        {"event": "background_job.completed", "sentry": "sent"},
        (),
        None,
    )

    integration._handle_record(record)

    assert handled == []


def test_custom_logging_integration_keeps_third_party_loggers(monkeypatch):
    integration, handled = _logging_integration(monkeypatch)
    record = logging.LogRecord(
        "django-q",
        logging.ERROR,
        __file__,
        1,
        "Task failed",
        (),
        None,
    )

    integration._handle_record(record)

    assert handled == [record]


def test_custom_logging_integration_keeps_unsent_rowset_loggers(monkeypatch):
    integration, handled = _logging_integration(monkeypatch)
    record = logging.LogRecord(
        "rowset.apps.core.tasks",
        logging.ERROR,
        __file__,
        1,
        "Direct standard-library error",
        (),
        None,
    )

    integration._handle_record(record)

    assert handled == [record]


def test_before_send_drops_background_job_completion_summaries():
    event = {
        "logger": "rowset.rowset.task_logging",
        "message": "background_job.completed",
    }

    assert before_send(event, {}) is None


def test_before_send_keeps_other_rowset_errors():
    event = {
        "logger": "rowset.apps.core.tasks",
        "message": "posthog.activation.failed",
    }

    assert before_send(event, {}) is event
