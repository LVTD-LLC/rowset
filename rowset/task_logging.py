from __future__ import annotations

import time
from collections.abc import Callable
from contextvars import ContextVar
from typing import Any

import structlog
from django.dispatch import receiver
from django_q.signals import post_execute_in_worker, pre_execute

from rowset.utils import get_rowset_logger

logger = get_rowset_logger(__name__)

_TASK_STARTED_AT: ContextVar[float | None] = ContextVar("rowset_task_started_at", default=None)


def _job_id(task: dict[str, Any]) -> str:
    return str(task.get("id") or "unknown")


def _job_function(func: Callable[..., Any] | str | None, task: dict[str, Any]) -> str:
    configured_function = task.get("func")
    if isinstance(configured_function, str):
        return configured_function
    if callable(func):
        return f"{func.__module__}.{func.__qualname__}"
    return "unknown"


def _job_context(func: Callable[..., Any] | str | None, task: dict[str, Any]) -> dict[str, Any]:
    return {
        "job.id": _job_id(task),
        "job.function": _job_function(func, task),
        "job.name": str(task.get("name") or ""),
        "job.group": str(task.get("group") or ""),
    }


@receiver(pre_execute, dispatch_uid="rowset.bind_task_logging_context")
def bind_task_context(
    sender: str,
    func: Callable[..., Any] | str | None,
    task: dict[str, Any],
    **kwargs: Any,
) -> None:
    structlog.contextvars.clear_contextvars()
    _TASK_STARTED_AT.set(time.perf_counter())
    structlog.contextvars.bind_contextvars(**_job_context(func, task))


@receiver(post_execute_in_worker, dispatch_uid="rowset.log_task_completion")
def log_task_completion(
    sender: str,
    func: Callable[..., Any] | str | None,
    task: dict[str, Any],
    **kwargs: Any,
) -> None:
    started_at = _TASK_STARTED_AT.get()
    _TASK_STARTED_AT.set(None)
    if not structlog.contextvars.get_contextvars():
        structlog.contextvars.bind_contextvars(**_job_context(func, task))

    success = bool(task.get("success", False))
    duration_ms = (
        round((time.perf_counter() - started_at) * 1_000, 2) if started_at is not None else 0.0
    )
    attributes: dict[str, Any] = {
        "job.success": success,
        "duration_ms": duration_ms,
        "outcome": "success" if success else "failure",
    }
    if not success:
        attributes["error.type"] = "TaskExecutionError"

    try:
        log_method = logger.info if success else logger.error
        log_method("background_job.completed", **attributes)
    finally:
        structlog.contextvars.clear_contextvars()
