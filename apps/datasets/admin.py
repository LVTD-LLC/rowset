from django.contrib import admin

from apps.datasets.models import Dataset, DatasetMutation, DatasetRow, Project


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
        "archived_at",
        "created_by_agent_api_key",
        "updated_by_agent_api_key",
        "archived_by_agent_api_key",
        "created_at",
    )
    list_select_related = (
        "profile__user",
        "project",
        "created_by_agent_api_key__profile__user",
        "updated_by_agent_api_key__profile__user",
        "archived_by_agent_api_key__profile__user",
    )
    search_fields = (
        "name",
        "description",
        "instructions",
        "original_filename",
        "project__name",
        "profile__user__email",
        "created_by_agent_api_key__name",
        "updated_by_agent_api_key__name",
        "archived_by_agent_api_key__name",
    )
    list_filter = (
        "status",
        "project",
        "public_enabled",
        "archived_at",
        "created_by_agent_api_key",
        "updated_by_agent_api_key",
        "archived_by_agent_api_key",
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
        "archived_by_agent_api_key",
        "archived_at",
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
    list_select_related = (
        "dataset",
        "created_by_agent_api_key__profile__user",
        "updated_by_agent_api_key__profile__user",
    )
    search_fields = (
        "dataset__name",
        "created_by_agent_api_key__name",
        "updated_by_agent_api_key__name",
    )
    list_filter = ("created_by_agent_api_key", "updated_by_agent_api_key", "created_at")


@admin.register(DatasetMutation)
class DatasetMutationAdmin(admin.ModelAdmin):
    list_display = (
        "dataset",
        "mutation_type",
        "actor_label",
        "target_type",
        "target_identifier",
        "created_at",
    )
    list_select_related = ("dataset", "profile__user", "agent_api_key__profile__user")
    search_fields = (
        "dataset__name",
        "profile__user__email",
        "agent_api_key__name",
        "actor_label",
        "summary",
        "target_identifier",
    )
    list_filter = ("mutation_type", "target_type", "agent_api_key", "created_at")
    readonly_fields = (
        "dataset",
        "profile",
        "agent_api_key",
        "actor_label",
        "mutation_type",
        "summary",
        "target_type",
        "target_identifier",
        "metadata",
        "created_at",
        "updated_at",
    )
