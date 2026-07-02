from typing import Protocol, cast

import posthog
from django.apps import AppConfig
from django.conf import settings

from rowset.utils import get_rowset_logger

logger = get_rowset_logger(__name__)


class _PostHogClient(Protocol):
    api_key: str
    debug: bool
    host: str

    def alias(self, previous_id: str, distinct_id: str) -> object: ...

    def capture(
        self,
        *,
        event: str,
        distinct_id: str,
        properties: dict[str, object],
    ) -> object: ...


def _posthog_client() -> _PostHogClient:
    return cast(_PostHogClient, posthog)


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"
    label = "core"

    def ready(self):
        import apps.core.signals  # noqa

        import apps.core.stripe_webhooks  # noqa

        if settings.POSTHOG_API_KEY:
            posthog_config = _posthog_client()
            posthog_config.api_key = settings.POSTHOG_API_KEY
            posthog_config.host = "https://us.i.posthog.com"

        if settings.ENVIRONMENT == "dev":
            _posthog_client().debug = True
