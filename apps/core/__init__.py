import atexit

import posthog
from django.apps import AppConfig
from django.conf import settings
from django.db.models.signals import post_migrate

from rowset.utils import get_rowset_logger

logger = get_rowset_logger(__name__)


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"
    label = "core"

    def ready(self):
        import apps.core.signals  # noqa
        import apps.core.stripe_webhooks  # noqa
        import rowset.task_logging  # noqa: F401
        from apps.core.site_config import sync_site_from_settings

        post_migrate.connect(
            sync_site_from_settings,
            sender=self,
            dispatch_uid="rowset.sync_site_from_settings",
        )

        if settings.POSTHOG_API_KEY:
            posthog.api_key = settings.POSTHOG_API_KEY
            posthog.host = settings.POSTHOG_HOST
            atexit.register(posthog.shutdown)

        if settings.POSTHOG_AI_OBSERVABILITY_ENABLED and settings.POSTHOG_API_KEY:
            from apps.core.ai_observability import configure_ai_observability

            configure_ai_observability()

        if settings.ENVIRONMENT == "dev":
            posthog.debug = True
