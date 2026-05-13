from django.contrib import admin

from apps.datasets.models import Dataset, DatasetRow


@admin.register(Dataset)
class DatasetAdmin(admin.ModelAdmin):
    list_display = ("name", "profile", "status", "row_count", "public_enabled", "created_at")
    search_fields = ("name", "original_filename", "profile__user__email")
    list_filter = ("status", "public_enabled", "created_at")
    readonly_fields = (
        "key",
        "public_key",
        "headers",
        "preview_rows",
        "parse_error",
        "created_at",
        "updated_at",
    )


@admin.register(DatasetRow)
class DatasetRowAdmin(admin.ModelAdmin):
    list_display = ("dataset", "row_number", "created_at")
    search_fields = ("dataset__name",)
    list_filter = ("created_at",)
