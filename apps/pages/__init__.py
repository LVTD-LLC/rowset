from django.apps import AppConfig
from django.core.exceptions import ImproperlyConfigured


class PagesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.pages'
    label = 'pages'

    def ready(self):
        from apps.pages import checks  # noqa: F401
        from apps.pages.use_cases import validate_use_case_page_registry

        try:
            validate_use_case_page_registry()
        except ValueError as exc:
            raise ImproperlyConfigured(str(exc)) from exc
