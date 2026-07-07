from django.contrib import admin

from apps.datasets.models import (
    Dataset,
    DatasetAsset,
    DatasetAssetFileDeletion,
    DatasetMutation,
    DatasetRow,
    Project,
    ProjectSection,
)


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("name", "profile", "created_at")
    search_fields = ("name", "description", "profile__user__email")
    list_filter = ("created_at",)
    readonly_fields = ("key", "created_at", "updated_at")


@admin.register(ProjectSection)
class ProjectSectionAdmin(admin.ModelAdmin):
    list_display = ("name", "project", "profile", "archived_at", "created_at")
    list_select_related = ("project", "profile__user")
    search_fields = ("name", "description", "project__name", "profile__user__email")
    list_filter = ("project", "archived_at", "created_at")
    readonly_fields = ("key", "created_at", "updated_at")


@admin.register(Dataset)
class DatasetAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "profile",
        "project",
        "section",
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
        "section",
        "created_by_agent_api_key__profile__user",
        "updated_by_agent_api_key__profile__user",
        "archived_by_agent_api_key__profile__user",
    )
    search_fields = (
        "name",
        "description",
        "instructions",
        "project__name",
        "section__name",
        "profile__user__email",
        "created_by_agent_api_key__name",
        "updated_by_agent_api_key__name",
        "archived_by_agent_api_key__name",
    )
    list_filter = (
        "project",
        "section",
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


@admin.register(DatasetAsset)
class DatasetAssetAdmin(admin.ModelAdmin):
    list_display = (
        "dataset",
        "row",
        "column_name",
        "content_type",
        "byte_size",
        "status",
        "created_at",
    )
    list_select_related = ("dataset", "row", "profile__user", "created_by_agent_api_key")
    search_fields = (
        "dataset__name",
        "profile__user__email",
        "column_name",
        "original_filename",
        "checksum",
    )
    list_filter = ("content_type", "status", "created_at")
    readonly_fields = (
        "key",
        "profile",
        "dataset",
        "row",
        "created_by_agent_api_key",
        "checksum",
        "created_at",
        "updated_at",
    )


@admin.register(DatasetAssetFileDeletion)
class DatasetAssetFileDeletionAdmin(admin.ModelAdmin):
    list_display = (
        "file_name",
        "storage_alias",
        "attempts",
        "deleted_at",
        "last_attempted_at",
        "created_at",
    )
    search_fields = ("file_name", "storage_alias", "last_error")
    list_filter = ("storage_alias", "deleted_at", "created_at")
    readonly_fields = (
        "storage_alias",
        "file_name",
        "attempts",
        "last_error",
        "last_attempted_at",
        "deleted_at",
        "created_at",
        "updated_at",
    )


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
