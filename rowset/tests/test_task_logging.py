import logging

import pytest
import structlog

from rowset.task_logging import bind_task_context, log_task_completion
from rowset.utils import get_rowset_logger


class CollectingHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.events: list[dict] = []

    def emit(self, record: logging.LogRecord) -> None:
        if isinstance(record.msg, dict):
            self.events.append(record.msg.copy())


@pytest.fixture
def captured_events():
    structlog.contextvars.clear_contextvars()
    rowset_logger = logging.getLogger("rowset")
    handler = CollectingHandler()
    rowset_logger.addHandler(handler)
    try:
        yield handler.events
    finally:
        rowset_logger.removeHandler(handler)
        structlog.contextvars.clear_contextvars()


def _event(events: list[dict], event_name: str) -> dict:
    return next(event for event in events if event.get("event") == event_name)


def _task() -> dict:
    return {
        "id": "task-1",
        "name": "Index vectors",
        "func": "apps.datasets.tasks.index_dataset_row_vector",
        "group": "vectors",
        "args": [123],
        "kwargs": {"token": "secret"},
    }


def test_task_completion_logs_safe_job_boundary(captured_events, monkeypatch):
    times = iter([10.0, 10.125])
    monkeypatch.setattr("rowset.task_logging.time.perf_counter", lambda: next(times))
    task = _task()

    bind_task_context(sender="django_q", func=lambda: None, task=task)
    task.update({"success": True, "result": {"private": "row data"}})
    log_task_completion(sender="django_q", func=lambda: None, task=task)

    event = _event(captured_events, "background_job.completed")
    assert event["job.id"] == "task-1"
    assert event["job.name"] == "Index vectors"
    assert event["job.function"] == "apps.datasets.tasks.index_dataset_row_vector"
    assert event["job.group"] == "vectors"
    assert event["job.success"] is True
    assert event["outcome"] == "success"
    assert event["duration_ms"] == 125.0
    assert "args" not in event
    assert "kwargs" not in event
    assert "result" not in event
    assert "secret" not in str(event)
    assert "row data" not in str(event)
    assert structlog.contextvars.get_contextvars() == {}


def test_task_context_correlates_nested_domain_logs(captured_events, monkeypatch):
    monkeypatch.setattr("rowset.task_logging.time.perf_counter", lambda: 20.0)
    task = _task()
    domain_logger = get_rowset_logger("task-test-domain")

    bind_task_context(sender="django_q", func=lambda: None, task=task)
    domain_logger.info("vector.index.completed", dataset_id=9)
    task["success"] = True
    log_task_completion(sender="django_q", func=lambda: None, task=task)

    domain_event = _event(captured_events, "vector.index.completed")
    assert domain_event["job.id"] == "task-1"
    assert domain_event["job.function"] == "apps.datasets.tasks.index_dataset_row_vector"


def test_failed_task_logs_stable_error_type_without_result(captured_events, monkeypatch):
    times = iter([30.0, 30.25])
    monkeypatch.setattr("rowset.task_logging.time.perf_counter", lambda: next(times))
    task = _task()

    bind_task_context(sender="django_q", func=lambda: None, task=task)
    task.update(
        {
            "success": False,
            "result": "ValueError: private dataset value\nfull traceback",
        }
    )
    log_task_completion(sender="django_q", func=lambda: None, task=task)

    event = _event(captured_events, "background_job.completed")
    assert event["job.success"] is False
    assert event["outcome"] == "failure"
    assert event["error.type"] == "TaskExecutionError"
    assert "private dataset value" not in str(event)
    assert event["duration_ms"] == 250.0
