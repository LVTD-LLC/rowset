from django.contrib import admin

from apps.core.models import AgentApiKey, EmailSent, Feedback


@admin.register(AgentApiKey)
class AgentApiKeyAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "profile",
        "key_prefix",
        "access_level",
        "is_active",
        "last_used_at",
        "created_at",
    )
    list_filter = ("access_level", "revoked_at", "created_at", "last_used_at")
    search_fields = ("name", "profile__user__email", "key_prefix")
    raw_id_fields = ("profile",)
    exclude = ("token_hash", "token_ciphertext")
    readonly_fields = ("key_prefix", "last_used_at", "created_at", "updated_at")

    def has_add_permission(self, request):
        return False


admin.site.register(EmailSent)


@admin.register(Feedback)
class FeedbackAdmin(admin.ModelAdmin):
    list_display = ("created_at", "source", "profile", "agent_api_key", "page")
    list_filter = ("source", "created_at")
    search_fields = ("feedback", "page", "profile__user__email", "agent_api_key__name")
    raw_id_fields = ("profile", "agent_api_key")
    readonly_fields = ("created_at", "updated_at")
