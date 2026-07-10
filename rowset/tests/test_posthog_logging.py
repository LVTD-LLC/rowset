import logging
from enum import StrEnum
from math import inf, nan
from uuid import UUID

from rowset.posthog_logging import (
    PostHogLoggingHandler,
    build_resource_attributes,
    sanitize_log_attributes,
)


class Outcome(StrEnum):
    SUCCESS = "success"


class CollectingHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def test_sanitize_log_attributes_keeps_queryable_scalars_and_drops_sensitive_values():
    attributes = sanitize_log_attributes(
        {
            "event": "dataset.search.completed",
            "profile_id": 42,
            "posthogDistinctId": "42",
            "agent_api_key_id": 8,
            "agent_api_key_access_level": "read_write",
            "query_id": "query-123",
            "duration_ms": 12.5,
            "cached": False,
            "outcome": Outcome.SUCCESS,
            "dataset_key": UUID("12345678-1234-5678-1234-567812345678"),
            "email": "person@example.com",
            "authorization": "Bearer secret",
            "posthog_cookie": "secret-cookie",
            "api_key_prefix": "rsk_secret",
            "metadata": {"private": "value"},
            "query": "private search text",
            "rows": [{"private": "dataset value"}],
            "row_ids": [1, 2],
        }
    )

    assert attributes == {
        "event.name": "dataset.search.completed",
        "profile_id": 42,
        "posthogDistinctId": "42",
        "agent_api_key_id": 8,
        "agent_api_key_access_level": "read_write",
        "query_id": "query-123",
        "duration_ms": 12.5,
        "cached": False,
        "outcome": "success",
        "dataset_key": "12345678-1234-5678-1234-567812345678",
    }


def test_sanitize_log_attributes_drops_non_finite_numbers_and_limits_strings():
    attributes = sanitize_log_attributes(
        {
            "event": "test.event",
            "positive_infinity": inf,
            "not_a_number": nan,
            "details": "x" * 2_000,
        }
    )

    assert "positive_infinity" not in attributes
    assert "not_a_number" not in attributes
    assert attributes["details"] == "x" * 1_024


def test_build_resource_attributes_uses_posthog_facets_and_release_context():
    attributes = build_resource_attributes(
        service_name="rowset-worker",
        environment="prod",
        service_version="release-123",
        instance_id="worker-1",
    )

    assert attributes == {
        "service.name": "rowset-worker",
        "service.namespace": "rowset",
        "service.version": "release-123",
        "deployment.environment.name": "prod",
        "service.instance.id": "worker-1",
    }


def test_posthog_handler_translates_structlog_event_for_delegate_without_mutating_original():
    delegate = CollectingHandler()
    handler = PostHogLoggingHandler(delegate=delegate)
    event_dict = {
        "event": "http.request.completed",
        "request.id": "req-1",
        "profile_id": 7,
        "email": "private@example.com",
    }
    record = logging.LogRecord(
        "rowset.test",
        logging.INFO,
        __file__,
        1,
        event_dict,
        (),
        None,
    )

    handler.emit(record)

    assert record.msg is event_dict
    exported = delegate.records[0]
    assert exported.getMessage() == "http.request.completed"
    assert getattr(exported, "event.name") == "http.request.completed"
    assert getattr(exported, "request.id") == "req-1"
    assert exported.profile_id == 7
    assert not hasattr(exported, "email")


def test_posthog_handler_translates_plain_standard_logging_records():
    delegate = CollectingHandler()
    handler = PostHogLoggingHandler(delegate=delegate)
    record = logging.LogRecord(
        "rowset.test",
        logging.WARNING,
        __file__,
        1,
        "Cache retry %s",
        (2,),
        None,
    )
    record.retry_count = 2

    handler.emit(record)

    exported = delegate.records[0]
    assert exported.getMessage() == "Cache retry 2"
    assert getattr(exported, "event.name") == "Cache retry 2"
    assert exported.retry_count == 2


def test_posthog_handler_preserves_explicit_structlog_exception_information():
    delegate = CollectingHandler()
    handler = PostHogLoggingHandler(delegate=delegate)

    try:
        raise ValueError("safe failure detail")
    except ValueError:
        record = logging.LogRecord(
            "rowset.test",
            logging.ERROR,
            __file__,
            1,
            {"event": "operation.failed", "exc_info": True},
            (),
            None,
        )
        handler.emit(record)

    exported = delegate.records[0]
    assert exported.exc_info is not None
    assert exported.exc_info[0] is ValueError
