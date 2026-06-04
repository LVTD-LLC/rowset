from django.db import models

from apps.core.base_models import BaseModel
from apps.core.models import Profile


class McpOAuthClient(BaseModel):
    client_id = models.CharField(max_length=128, unique=True)
    client_info = models.JSONField()

    def __str__(self):
        return self.client_id


class McpOAuthAuthorizationRequest(BaseModel):
    transaction_id = models.CharField(max_length=128, unique=True)
    client_id = models.CharField(max_length=128, db_index=True)
    scopes = models.JSONField(default=list)
    code_challenge = models.CharField(max_length=255)
    redirect_uri = models.TextField()
    redirect_uri_provided_explicitly = models.BooleanField(default=False)
    resource = models.TextField(blank=True, default="")
    state = models.TextField(blank=True, default="")
    expires_at = models.DateTimeField(db_index=True)

    def __str__(self):
        return f"{self.client_id}:{self.transaction_id}"


class McpOAuthAuthorizationCode(BaseModel):
    code_hash = models.CharField(max_length=64, unique=True)
    client_id = models.CharField(max_length=128, db_index=True)
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="mcp_oauth_codes")
    scopes = models.JSONField(default=list)
    code_challenge = models.CharField(max_length=255)
    redirect_uri = models.TextField()
    redirect_uri_provided_explicitly = models.BooleanField(default=False)
    resource = models.TextField(blank=True, default="")
    expires_at = models.DateTimeField(db_index=True)
    used_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.client_id}:{self.profile_id}"


class McpOAuthAccessToken(BaseModel):
    token_hash = models.CharField(max_length=64, unique=True)
    client_id = models.CharField(max_length=128, db_index=True)
    profile = models.ForeignKey(
        Profile,
        on_delete=models.CASCADE,
        related_name="mcp_oauth_access_tokens",
    )
    scopes = models.JSONField(default=list)
    resource = models.TextField(blank=True, default="")
    expires_at = models.DateTimeField(db_index=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.client_id}:{self.profile_id}"


class McpOAuthRefreshToken(BaseModel):
    token_hash = models.CharField(max_length=64, unique=True)
    client_id = models.CharField(max_length=128, db_index=True)
    profile = models.ForeignKey(
        Profile,
        on_delete=models.CASCADE,
        related_name="mcp_oauth_refresh_tokens",
    )
    scopes = models.JSONField(default=list)
    resource = models.TextField(blank=True, default="")
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.client_id}:{self.profile_id}"
