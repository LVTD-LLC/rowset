from __future__ import annotations

import copy
import logging
import os
import socket
import sys
from collections.abc import Mapping
from enum import Enum
from math import isfinite
from typing import Any
from uuid import UUID

from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource

Scalar = str | bool | int | float
MAX_ATTRIBUTE_STRING_LENGTH = 1_024

_SAFE_API_KEY_FIELDS = frozenset(
    {
        "agent_api_key_access_level",
        "agent_api_key_id",
        "agent_api_key_present",
    }
)
_SENSITIVE_EXACT_FIELDS = frozenset(
    {
        "api_key",
        "api_key_prefix",
        "args",
        "authorization",
        "body",
        "cookie",
        "cookies",
        "email",
        "email_address",
        "feedback",
        "kwargs",
        "metadata",
        "password",
        "payload",
        "posthog_cookie",
        "properties",
        "query",
        "request",
        "request_body",
        "response",
        "response_body",
        "result",
        "row_data",
        "rows",
        "secret",
        "token",
        "user_email",
    }
)
_SENSITIVE_FIELD_SUFFIXES = (
    "_authorization",
    "_body",
    "_cookie",
    "_cookies",
    "_email",
    "_email_address",
    "_password",
    "_payload",
    "_secret",
    "_token",
)
_STRUCTLOG_INTERNAL_FIELDS = frozenset(
    {
        "_from_structlog",
        "_logger",
        "_name",
        "_record",
        "event",
        "exc_info",
        "level",
        "logger",
        "stack_info",
        "timestamp",
    }
)
_LOG_RECORD_FIELDS = frozenset(
    set(vars(logging.LogRecord("", 0, "", 0, "", (), None))) | {"asctime", "message"}
)


def _normalized_field_name(key: str) -> str:
    return key.lower().replace(".", "_").replace("-", "_")


def _is_sensitive_field(key: str) -> bool:
    normalized = _normalized_field_name(key)
    if normalized in _SAFE_API_KEY_FIELDS:
        return False
    if normalized in _SENSITIVE_EXACT_FIELDS:
        return True
    if "api_key" in normalized:
        return True
    return normalized.endswith(_SENSITIVE_FIELD_SUFFIXES)


def _normalize_scalar(value: Any) -> Scalar | None:
    if isinstance(value, Enum):
        return _normalize_scalar(value.value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, str):
        return value[:MAX_ATTRIBUTE_STRING_LENGTH]
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float) and isfinite(value):
        return value
    return None


def sanitize_log_attributes(event_dict: Mapping[str, Any]) -> dict[str, Scalar]:
    attributes: dict[str, Scalar] = {}
    event_name = _normalize_scalar(event_dict.get("event"))
    if isinstance(event_name, str):
        attributes["event.name"] = event_name

    for raw_key, value in event_dict.items():
        key = str(raw_key)
        if key in _STRUCTLOG_INTERNAL_FIELDS or _is_sensitive_field(key):
            continue
        normalized = _normalize_scalar(value)
        if normalized is not None:
            attributes[key] = normalized

    return attributes


def build_resource_attributes(
    *,
    service_name: str,
    environment: str,
    service_version: str,
    instance_id: str,
) -> dict[str, str]:
    return {
        "service.name": service_name,
        "service.namespace": "rowset",
        "service.version": service_version or "unknown",
        "deployment.environment.name": environment,
        "service.instance.id": instance_id,
    }


class PostHogLoggingHandler(logging.Handler):
    def __init__(
        self,
        *,
        delegate: logging.Handler | None = None,
        endpoint: str = "",
        api_key: str = "",
        service_name: str = "rowset-web",
        environment: str = "dev",
        service_version: str = "unknown",
    ) -> None:
        super().__init__()
        self._logger_provider: LoggerProvider | None = None

        if delegate is None:
            instance_id = f"{socket.gethostname()}:{os.getpid()}"
            resource = Resource.create(
                build_resource_attributes(
                    service_name=service_name,
                    environment=environment,
                    service_version=service_version,
                    instance_id=instance_id,
                )
            )
            self._logger_provider = LoggerProvider(resource=resource)
            exporter = OTLPLogExporter(
                endpoint=endpoint,
                headers={"Authorization": f"Bearer {api_key}"},
            )
            self._logger_provider.add_log_record_processor(BatchLogRecordProcessor(exporter))
            delegate = LoggingHandler(logger_provider=self._logger_provider)

        self._delegate = delegate

    def emit(self, record: logging.LogRecord) -> None:
        try:
            exported_record = self._translate_record(record)
            self._delegate.emit(exported_record)
        except Exception:
            self.handleError(record)

    def _translate_record(self, record: logging.LogRecord) -> logging.LogRecord:
        exported_record = copy.copy(record)
        if isinstance(record.msg, Mapping):
            event_dict = record.msg
            event_name = _normalize_scalar(event_dict.get("event"))
            message = event_name if isinstance(event_name, str) else record.getMessage()
            attributes = sanitize_log_attributes(event_dict)
            explicit_exc_info = event_dict.get("exc_info")
            if not exported_record.exc_info and explicit_exc_info:
                if isinstance(explicit_exc_info, tuple):
                    exported_record.exc_info = explicit_exc_info
                elif isinstance(explicit_exc_info, BaseException):
                    exported_record.exc_info = (
                        type(explicit_exc_info),
                        explicit_exc_info,
                        explicit_exc_info.__traceback__,
                    )
                else:
                    exported_record.exc_info = sys.exc_info()
        else:
            message = record.getMessage()
            extra = {
                key: value for key, value in vars(record).items() if key not in _LOG_RECORD_FIELDS
            }
            attributes = sanitize_log_attributes({"event": message, **extra})

        exported_record.msg = message
        exported_record.args = ()
        for key, value in attributes.items():
            setattr(exported_record, key, value)
        return exported_record
