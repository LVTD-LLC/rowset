from django.conf import settings
from django.db import transaction
from django_q.tasks import async_task

from rowset.utils import get_rowset_logger

logger = get_rowset_logger(__name__)


def enqueue_vector_task(task_path: str, *args) -> None:
    if not settings.ROWSET_VECTOR_SEARCH_ENABLED:
        return

    def enqueue() -> None:
        try:
            async_task(task_path, *args)
        except Exception:
            logger.exception("Failed to enqueue vector task", task_path=task_path)

    transaction.on_commit(enqueue)
