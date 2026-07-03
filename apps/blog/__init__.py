from django.apps import AppConfig


class BlogConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.blog"
    label = "blog"

    def ready(self):
        from apps.blog import checks  # noqa: F401
