from django.contrib import admin

from apps.core.models import AgentApiKey, EmailSent

admin.site.register(AgentApiKey)
admin.site.register(EmailSent)
