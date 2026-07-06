from importlib import import_module

from django.apps import AppConfig
from django.conf import settings


class DatasetPluginsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.dataset_plugins"
    label = "dataset_plugins"

    def ready(self):
        from apps.dataset_plugins import builtin  # noqa: F401

        for module_path in getattr(settings, "ROWSET_DATASET_PLUGIN_MODULES", []):
            import_module(module_path)
