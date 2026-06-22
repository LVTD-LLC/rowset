from django.contrib import admin

from apps.core.models import AgentApiKey, EmailSent


@admin.register(AgentApiKey)
class AgentApiKeyAdmin(admin.ModelAdmin):
    list_display = ("name", "profile", "key_prefix", "is_active", "last_used_at", "created_at")
    list_filter = ("revoked_at", "created_at", "last_used_at")
    search_fields = ("name", "profile__user__email", "key_prefix")
    raw_id_fields = ("profile",)
    exclude = ("token_hash",)
    readonly_fields = ("key_prefix", "last_used_at", "created_at", "updated_at")

    def has_add_permission(self, request):
        return False


admin.site.register(EmailSent)
