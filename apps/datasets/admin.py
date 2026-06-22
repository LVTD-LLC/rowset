from django.contrib import admin

from apps.datasets.models import Dataset, DatasetRow, Project


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("name", "profile", "created_at")
    search_fields = ("name", "description", "profile__user__email")
    list_filter = ("created_at",)
    readonly_fields = ("key", "created_at", "updated_at")


@admin.register(Dataset)
class DatasetAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "profile",
        "project",
        "status",
        "row_count",
        "public_enabled",
        "created_by_agent_api_key",
        "updated_by_agent_api_key",
        "created_at",
    )
    search_fields = (
        "name",
        "original_filename",
        "project__name",
        "profile__user__email",
        "created_by_agent_api_key__name",
        "updated_by_agent_api_key__name",
    )
    list_filter = (
        "status",
        "project",
        "public_enabled",
        "created_by_agent_api_key",
        "updated_by_agent_api_key",
        "created_at",
    )
    readonly_fields = (
        "key",
        "public_key",
        "headers",
        "preview_rows",
        "parse_error",
        "created_by_agent_api_key",
        "updated_by_agent_api_key",
        "created_at",
        "updated_at",
    )


@admin.register(DatasetRow)
class DatasetRowAdmin(admin.ModelAdmin):
    list_display = (
        "dataset",
        "row_number",
        "created_by_agent_api_key",
        "updated_by_agent_api_key",
        "created_at",
    )
    search_fields = (
        "dataset__name",
        "created_by_agent_api_key__name",
        "updated_by_agent_api_key__name",
    )
    list_filter = ("created_by_agent_api_key", "updated_by_agent_api_key", "created_at")
