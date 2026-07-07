import json
from logging import LogRecord

from fastmcp.exceptions import ToolError
from sentry_sdk.integrations.logging import LoggingIntegration

_IGNORED_LOGGERS = {"ask_hn_digest"}


class CustomLoggingIntegration(LoggingIntegration):
    def _handle_record(self, record: LogRecord) -> None:
        # This match upper logger names, e.g. "celery" will match "celery.worker"
        # or "celery.worker.job"
        if record.name in _IGNORED_LOGGERS or record.name.split(".")[0] in _IGNORED_LOGGERS:
            return
        super()._handle_record(record)


def _tool_error_payload(exc_value: ToolError) -> dict:
    decoder = json.JSONDecoder()
    text = str(exc_value)
    for index, character in enumerate(text):
        if character != "{":
            continue
        try:
            payload, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return {}


def _is_expected_mcp_tool_error(exc_value: ToolError) -> bool:
    payload = _tool_error_payload(exc_value)
    http_status = payload.get("details", {}).get("http_status")
    return isinstance(http_status, int) and http_status < 500


def before_send(event, hint):
    if "exc_info" in hint:
        exc_type, exc_value, tb = hint["exc_info"]

        if isinstance(exc_value, ToolError) and _is_expected_mcp_tool_error(exc_value):
            return None

        if isinstance(exc_value, SystemExit):  # group all SystemExits together
            event["fingerprint"] = ["system-exit"]
    return event
