from django.contrib import admin

from apps.dataset_plugins.models import DatasetPluginActivation, ProfilePluginInstallation


@admin.register(ProfilePluginInstallation)
class ProfilePluginInstallationAdmin(admin.ModelAdmin):
    list_display = ("profile", "plugin_slug", "created_at")
    list_select_related = ("profile__user",)
    list_filter = ("plugin_slug", "created_at")
    search_fields = ("profile__user__email", "plugin_slug")
    readonly_fields = ("created_at", "updated_at")


@admin.register(DatasetPluginActivation)
class DatasetPluginActivationAdmin(admin.ModelAdmin):
    list_display = ("dataset", "plugin_slug", "enabled", "profile", "updated_at")
    list_filter = ("plugin_slug", "enabled")
    search_fields = ("dataset__name", "plugin_slug", "profile__user__email")
    readonly_fields = ("created_at", "updated_at")
