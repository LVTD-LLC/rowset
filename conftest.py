import logging
import os

import pytest
import structlog


class CapturedLogEvents(list[dict]):
    def event(self, event_name: str) -> dict:
        return next(event for event in self if event.get("event") == event_name)


class CollectingLogHandler(logging.Handler):
    def __init__(self, events: CapturedLogEvents):
        super().__init__()
        self.events = events

    def emit(self, record: logging.LogRecord) -> None:
        if isinstance(record.msg, dict):
            self.events.append(record.msg.copy())


@pytest.fixture
def captured_events():
    structlog.contextvars.clear_contextvars()
    rowset_logger = logging.getLogger("rowset")
    events = CapturedLogEvents()
    handler = CollectingLogHandler(events)
    rowset_logger.addHandler(handler)
    try:
        yield events
    finally:
        rowset_logger.removeHandler(handler)
        structlog.contextvars.clear_contextvars()


def pytest_configure(config):
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "rowset.settings")

    from django.conf import settings

    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
    settings.STORAGES["staticfiles"]["BACKEND"] = (
        "django.contrib.staticfiles.storage.StaticFilesStorage"
    )
