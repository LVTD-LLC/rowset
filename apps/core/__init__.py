import posthog


from django.conf import settings
from django.apps import AppConfig

from filebridge.utils import get_filebridge_logger

logger = get_filebridge_logger(__name__)


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"
    label = "core"

    def ready(self):
        import apps.core.signals  # noqa

        import apps.core.stripe_webhooks # noqa
        

        if settings.POSTHOG_API_KEY:
            posthog.api_key = settings.POSTHOG_API_KEY
            posthog.host = "https://us.i.posthog.com"

        if settings.ENVIRONMENT == "dev":
            posthog.debug = True
        
