from django.contrib import admin

from apps.dataset_plugins.models import DatasetPluginActivation


@admin.register(DatasetPluginActivation)
class DatasetPluginActivationAdmin(admin.ModelAdmin):
    list_display = ("dataset", "plugin_slug", "enabled", "profile", "updated_at")
    list_filter = ("plugin_slug", "enabled")
    search_fields = ("dataset__name", "plugin_slug", "profile__user__email")
    readonly_fields = ("created_at", "updated_at")
