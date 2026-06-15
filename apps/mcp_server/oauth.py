from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from asgiref.sync import sync_to_async
from django.db import close_old_connections, transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from fastmcp.server.auth import AccessToken, OAuthProvider
from mcp.server.auth.provider import (
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    RefreshToken,
    RegistrationError,
    TokenError,
    construct_redirect_uri,
)
from mcp.server.auth.settings import ClientRegistrationOptions, RevocationOptions
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from apps.core.models import Profile
from apps.mcp_server.models import (
    McpOAuthAccessToken,
    McpOAuthAuthorizationCode,
    McpOAuthAuthorizationRequest,
    McpOAuthClient,
    McpOAuthRefreshToken,
)
from filebridge.utils import build_absolute_public_url

MCP_MOUNT_PATH = "/mcp"
MCP_INTERNAL_PATH = "/"
MCP_SCOPE = "rowset:mcp"
LEGACY_MCP_SCOPE = "filebridge:mcp"
AUTHORIZATION_REQUEST_TTL_SECONDS = 10 * 60
AUTHORIZATION_CODE_TTL_SECONDS = 10 * 60
ACCESS_TOKEN_TTL_SECONDS = 60 * 60
REFRESH_TOKEN_TTL_SECONDS = 30 * 24 * 60 * 60
LEGACY_API_KEY_CLIENT_ID = "rowset-api-key"


def build_mcp_base_url() -> str:
    return build_absolute_public_url(MCP_MOUNT_PATH).rstrip("/")


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_token() -> str:
    return secrets.token_urlsafe(48)


def normalize_oauth_scopes(scopes: list[str] | None) -> list[str]:
    normalized = []
    for scope in scopes or []:
        normalized_scope = MCP_SCOPE if scope == LEGACY_MCP_SCOPE else scope
        if normalized_scope not in normalized:
            normalized.append(normalized_scope)
    return normalized


def normalize_stored_oauth_scopes(token) -> list[str]:
    scopes = normalize_oauth_scopes(token.scopes)
    if scopes != token.scopes:
        token.scopes = scopes
        token.save(update_fields=["scopes", "updated_at"])
    return scopes


def expires_in(seconds: int):
    return timezone.now() + timedelta(seconds=seconds)


def unix_timestamp(value) -> int:
    return int(value.timestamp())


def serialize_client_info(client_info: OAuthClientInformationFull) -> dict:
    return client_info.model_dump(mode="json", exclude_none=True)


def deserialize_client_info(data: dict) -> OAuthClientInformationFull:
    return OAuthClientInformationFull.model_validate(data)


def run_with_fresh_db_connection(func, *args):
    close_old_connections()
    try:
        return func(*args)
    finally:
        close_old_connections()


def client_display_name(client: OAuthClientInformationFull | None) -> str:
    if not client:
        return "MCP client"
    return client.client_name or client.client_id or "MCP client"


def get_authorization_request(transaction_id: str) -> McpOAuthAuthorizationRequest | None:
    now = timezone.now()
    return (
        McpOAuthAuthorizationRequest.objects.filter(
            transaction_id=transaction_id,
            expires_at__gt=now,
        )
        .order_by("-created_at")
        .first()
    )


def get_client_for_authorization_request(
    authorization_request: McpOAuthAuthorizationRequest,
) -> OAuthClientInformationFull | None:
    try:
        client = McpOAuthClient.objects.get(client_id=authorization_request.client_id)
    except McpOAuthClient.DoesNotExist:
        return None
    return deserialize_client_info(client.client_info)


def deny_authorization_request(transaction_id: str) -> str:
    with transaction.atomic():
        authorization_request = (
            McpOAuthAuthorizationRequest.objects.select_for_update()
            .filter(transaction_id=transaction_id, expires_at__gt=timezone.now())
            .first()
        )
        if authorization_request is None:
            raise ValueError("Authorization request has expired or does not exist.")

        redirect_uri = authorization_request.redirect_uri
        state = authorization_request.state or None
        authorization_request.delete()

    return construct_redirect_uri(redirect_uri, error="access_denied", state=state)


def approve_authorization_request(transaction_id: str, profile: Profile) -> str:
    with transaction.atomic():
        authorization_request = (
            McpOAuthAuthorizationRequest.objects.select_for_update()
            .filter(transaction_id=transaction_id, expires_at__gt=timezone.now())
            .first()
        )
        if authorization_request is None:
            raise ValueError("Authorization request has expired or does not exist.")

        if not McpOAuthClient.objects.filter(client_id=authorization_request.client_id).exists():
            raise ValueError("OAuth client no longer exists.")

        code = generate_token()
        McpOAuthAuthorizationCode.objects.create(
            code_hash=hash_token(code),
            client_id=authorization_request.client_id,
            profile=profile,
            scopes=authorization_request.scopes,
            code_challenge=authorization_request.code_challenge,
            redirect_uri=authorization_request.redirect_uri,
            redirect_uri_provided_explicitly=(
                authorization_request.redirect_uri_provided_explicitly
            ),
            resource=authorization_request.resource,
            expires_at=expires_in(AUTHORIZATION_CODE_TTL_SECONDS),
        )
        redirect_uri = authorization_request.redirect_uri
        state = authorization_request.state or None
        authorization_request.delete()

    return construct_redirect_uri(redirect_uri, code=code, state=state)


class RowsetOAuthProvider(OAuthProvider):
    def __init__(self, *, base_url: str | None = None):
        super().__init__(
            base_url=base_url or build_mcp_base_url(),
            client_registration_options=ClientRegistrationOptions(
                enabled=True,
                valid_scopes=[MCP_SCOPE],
                default_scopes=[MCP_SCOPE],
            ),
            revocation_options=RevocationOptions(enabled=True),
            required_scopes=[MCP_SCOPE],
        )

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        return await self._run_sync(self._get_client_sync, client_id)

    async def _run_sync(self, func, *args):
        return await sync_to_async(run_with_fresh_db_connection, thread_sensitive=True)(
            func,
            *args,
        )

    def _get_client_sync(self, client_id: str) -> OAuthClientInformationFull | None:
        try:
            client = McpOAuthClient.objects.get(client_id=client_id)
        except McpOAuthClient.DoesNotExist:
            return None
        return deserialize_client_info(client.client_info)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        await self._run_sync(self._register_client_sync, client_info)

    def _register_client_sync(self, client_info: OAuthClientInformationFull) -> None:
        if not client_info.client_id:
            raise RegistrationError(
                "invalid_client_metadata",
                "OAuth client_id is required.",
            )

        McpOAuthClient.objects.update_or_create(
            client_id=client_info.client_id,
            defaults={"client_info": serialize_client_info(client_info)},
        )

    async def authorize(
        self,
        client: OAuthClientInformationFull,
        params: AuthorizationParams,
    ) -> str:
        if not client.client_id:
            raise AuthorizeError("invalid_request", "OAuth client_id is required.")

        resource_url = str(self._resource_url or "").rstrip("/")
        requested_resource = (params.resource or "").rstrip("/")
        if requested_resource and resource_url and requested_resource != resource_url:
            raise AuthorizeError("invalid_request", "Invalid resource parameter.")

        transaction_id = generate_token()
        await self._run_sync(
            self._create_authorization_request_sync,
            transaction_id,
            client,
            params,
        )

        authorize_path = reverse("mcp_oauth_authorize")
        return build_absolute_public_url(f"{authorize_path}?transaction={transaction_id}")

    def _create_authorization_request_sync(
        self,
        transaction_id: str,
        client: OAuthClientInformationFull,
        params: AuthorizationParams,
    ) -> None:
        McpOAuthAuthorizationRequest.objects.create(
            transaction_id=transaction_id,
            client_id=client.client_id,
            scopes=params.scopes or [MCP_SCOPE],
            code_challenge=params.code_challenge,
            redirect_uri=str(params.redirect_uri),
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            resource=params.resource or "",
            state=params.state or "",
            expires_at=expires_in(AUTHORIZATION_REQUEST_TTL_SECONDS),
        )

    async def load_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: str,
    ) -> AuthorizationCode | None:
        return await self._run_sync(
            self._load_authorization_code_sync,
            client,
            authorization_code,
        )

    def _load_authorization_code_sync(
        self,
        client: OAuthClientInformationFull,
        authorization_code: str,
    ) -> AuthorizationCode | None:
        if not client.client_id:
            return None

        code = (
            McpOAuthAuthorizationCode.objects.filter(
                code_hash=hash_token(authorization_code),
                client_id=client.client_id,
                used_at__isnull=True,
                expires_at__gt=timezone.now(),
            )
            .select_related("profile")
            .first()
        )
        if code is None:
            return None

        scopes = normalize_stored_oauth_scopes(code)
        return AuthorizationCode(
            code=authorization_code,
            scopes=scopes,
            expires_at=code.expires_at.timestamp(),
            client_id=code.client_id,
            code_challenge=code.code_challenge,
            redirect_uri=code.redirect_uri,
            redirect_uri_provided_explicitly=code.redirect_uri_provided_explicitly,
            resource=code.resource or None,
            subject=str(code.profile_id),
        )

    async def exchange_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: AuthorizationCode,
    ) -> OAuthToken:
        return await self._run_sync(
            self._exchange_authorization_code_sync,
            client,
            authorization_code,
        )

    def _exchange_authorization_code_sync(
        self,
        client: OAuthClientInformationFull,
        authorization_code: AuthorizationCode,
    ) -> OAuthToken:
        with transaction.atomic():
            code = (
                McpOAuthAuthorizationCode.objects.select_for_update()
                .select_related("profile")
                .filter(
                    code_hash=hash_token(authorization_code.code),
                    client_id=authorization_code.client_id,
                    used_at__isnull=True,
                    expires_at__gt=timezone.now(),
                )
                .first()
            )
            if code is None:
                raise TokenError("invalid_grant", "authorization code does not exist")

            code.used_at = timezone.now()
            code.save(update_fields=["used_at", "updated_at"])
            return self._issue_tokens(
                client_id=client.client_id or authorization_code.client_id,
                profile=code.profile,
                scopes=normalize_stored_oauth_scopes(code),
                resource=code.resource,
            )

    async def load_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: str,
    ) -> RefreshToken | None:
        return await self._run_sync(
            self._load_refresh_token_sync,
            client,
            refresh_token,
        )

    def _load_refresh_token_sync(
        self,
        client: OAuthClientInformationFull,
        refresh_token: str,
    ) -> RefreshToken | None:
        if not client.client_id:
            return None

        token = (
            McpOAuthRefreshToken.objects.filter(
                token_hash=hash_token(refresh_token),
                client_id=client.client_id,
                revoked_at__isnull=True,
            )
            .filter(models_refresh_token_not_expired())
            .select_related("profile")
            .first()
        )
        if token is None:
            return None

        scopes = normalize_stored_oauth_scopes(token)
        return RefreshToken(
            token=refresh_token,
            client_id=token.client_id,
            scopes=scopes,
            expires_at=unix_timestamp(token.expires_at) if token.expires_at else None,
            subject=str(token.profile_id),
        )

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        return await self._run_sync(
            self._exchange_refresh_token_sync,
            client,
            refresh_token,
            scopes,
        )

    def _exchange_refresh_token_sync(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        with transaction.atomic():
            stored_refresh_token = (
                McpOAuthRefreshToken.objects.select_for_update()
                .select_related("profile")
                .filter(
                    token_hash=hash_token(refresh_token.token),
                    client_id=refresh_token.client_id,
                    revoked_at__isnull=True,
                )
                .filter(models_refresh_token_not_expired())
                .first()
            )
            if stored_refresh_token is None:
                raise TokenError("invalid_grant", "refresh token does not exist")

            # RFC 6749 section 6 treats an omitted refresh scope as the original grant.
            stored_scopes = normalize_stored_oauth_scopes(stored_refresh_token)
            requested_scopes = normalize_oauth_scopes(scopes)
            effective_scopes = requested_scopes if requested_scopes else stored_scopes
            for scope in effective_scopes:
                if scope not in stored_scopes:
                    raise TokenError("invalid_scope", f"cannot request scope `{scope}`")

            stored_refresh_token.revoked_at = timezone.now()
            stored_refresh_token.save(update_fields=["revoked_at", "updated_at"])
            return self._issue_tokens(
                client_id=client.client_id or refresh_token.client_id,
                profile=stored_refresh_token.profile,
                scopes=effective_scopes,
                resource=stored_refresh_token.resource,
            )

    async def load_access_token(self, token: str) -> AccessToken | None:
        return await self._run_sync(self._load_access_token_sync, token)

    def _load_access_token_sync(self, token: str) -> AccessToken | None:
        access_token = (
            McpOAuthAccessToken.objects.filter(
                token_hash=hash_token(token),
                revoked_at__isnull=True,
                expires_at__gt=timezone.now(),
            )
            .select_related("profile__user")
            .first()
        )
        if access_token is not None:
            return self._to_access_token(token, access_token)

        try:
            profile = Profile.objects.select_related("user").get(key=token)
        except Profile.DoesNotExist:
            return None

        return AccessToken(
            token=token,
            client_id=LEGACY_API_KEY_CLIENT_ID,
            scopes=[MCP_SCOPE],
            expires_at=None,
            resource=str(self._resource_url) if self._resource_url else None,
            subject=str(profile.id),
            claims={
                "iss": str(self.base_url),
                "sub": str(profile.id),
                "profile_id": profile.id,
                "email": profile.user.email,
                "legacy_api_key": True,
            },
        )

    async def revoke_token(
        self,
        token: AccessToken | RefreshToken,
    ) -> None:
        await self._run_sync(self._revoke_token_sync, token)

    def _revoke_token_sync(self, token: AccessToken | RefreshToken) -> None:
        now = timezone.now()
        token_hash = hash_token(token.token)
        McpOAuthAccessToken.objects.filter(token_hash=token_hash).update(revoked_at=now)
        McpOAuthRefreshToken.objects.filter(token_hash=token_hash).update(revoked_at=now)

    def _issue_tokens(
        self,
        *,
        client_id: str,
        profile: Profile,
        scopes: list[str],
        resource: str,
    ) -> OAuthToken:
        access_token = generate_token()
        refresh_token = generate_token()
        scopes = normalize_oauth_scopes(scopes)
        McpOAuthAccessToken.objects.create(
            token_hash=hash_token(access_token),
            client_id=client_id,
            profile=profile,
            scopes=scopes,
            resource=resource,
            expires_at=expires_in(ACCESS_TOKEN_TTL_SECONDS),
        )
        McpOAuthRefreshToken.objects.create(
            token_hash=hash_token(refresh_token),
            client_id=client_id,
            profile=profile,
            scopes=scopes,
            resource=resource,
            expires_at=expires_in(REFRESH_TOKEN_TTL_SECONDS),
        )
        return OAuthToken(
            access_token=access_token,
            expires_in=ACCESS_TOKEN_TTL_SECONDS,
            scope=" ".join(scopes),
            refresh_token=refresh_token,
        )

    def _to_access_token(
        self,
        raw_token: str,
        stored_token: McpOAuthAccessToken,
    ) -> AccessToken:
        profile = stored_token.profile
        scopes = normalize_stored_oauth_scopes(stored_token)
        return AccessToken(
            token=raw_token,
            client_id=stored_token.client_id,
            scopes=scopes,
            expires_at=unix_timestamp(stored_token.expires_at),
            resource=stored_token.resource or None,
            subject=str(profile.id),
            claims={
                "iss": str(self.base_url),
                "sub": str(profile.id),
                "profile_id": profile.id,
                "email": profile.user.email,
            },
        )


def models_refresh_token_not_expired():
    return Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now())


def prune_expired_oauth_artifacts() -> dict[str, int]:
    now = timezone.now()
    return {
        "authorization_requests": McpOAuthAuthorizationRequest.objects.filter(
            expires_at__lte=now
        ).delete()[0],
        "authorization_codes": McpOAuthAuthorizationCode.objects.filter(
            Q(expires_at__lte=now) | Q(used_at__isnull=False)
        ).delete()[0],
        "access_tokens": McpOAuthAccessToken.objects.filter(
            Q(expires_at__lte=now) | Q(revoked_at__isnull=False)
        ).delete()[0],
        "refresh_tokens": McpOAuthRefreshToken.objects.filter(
            Q(expires_at__lte=now) | Q(revoked_at__isnull=False)
        ).delete()[0],
    }


mcp_auth = RowsetOAuthProvider()
