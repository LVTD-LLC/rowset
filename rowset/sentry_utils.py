import asyncio
import json
from logging import LogRecord

from sentry_sdk.integrations.logging import LoggingIntegration

try:
    from fastmcp.exceptions import ToolError
except ImportError:  # pragma: no cover - FastMCP is installed in normal Rowset runtimes.
    ToolError = None

from apps.api.errors import DatasetServiceError

_IGNORED_LOGGERS = {"ask_hn_digest"}
_IGNORED_EVENT_LOGGERS = {"rowset.rowset.task_logging"}


class CustomLoggingIntegration(LoggingIntegration):
    def _handle_record(self, record: LogRecord) -> None:
        # This match upper logger names, e.g. "celery" will match "celery.worker"
        # or "celery.worker.job"
        if record.name in _IGNORED_LOGGERS or record.name.split(".")[0] in _IGNORED_LOGGERS:
            return
        if isinstance(record.msg, dict) and record.msg.get("sentry") == "sent":
            return
        super()._handle_record(record)


def before_send(event, hint):
    if event.get("logger") in _IGNORED_EVENT_LOGGERS:
        return None

    if "exc_info" in hint:
        exc_type, exc_value, tb = hint["exc_info"]

        if isinstance(exc_value, SystemExit):  # group all SystemExits together
            event["fingerprint"] = ["system-exit"]
        if isinstance(exc_value, asyncio.CancelledError):
            return None
        if _is_expected_agent_error(exc_value):
            return None
    return event


def _is_expected_agent_error(exc: BaseException) -> bool:
    if isinstance(exc, DatasetServiceError):
        return exc.status_code < 500

    if ToolError is not None and isinstance(exc, ToolError):
        status_code = _mcp_tool_error_status_code(exc)
        if status_code is None:
            status_code = _chained_dataset_service_status_code(exc)
        return status_code is not None and status_code < 500

    return False


def _mcp_tool_error_status_code(exc: BaseException) -> int | None:
    decoder = json.JSONDecoder()
    text = str(exc)
    for index, character in enumerate(text):
        if character != "{":
            continue
        try:
            payload, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        details = payload.get("details")
        if not isinstance(details, dict):
            continue
        try:
            return int(details.get("http_status"))
        except TypeError:
            return None
        except ValueError:
            return None
    return None


def _chained_dataset_service_status_code(exc: BaseException) -> int | None:
    seen: set[int] = set()
    current = exc.__cause__ or exc.__context__
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, DatasetServiceError):
            return current.status_code
        current = current.__cause__ or current.__context__
    return None
