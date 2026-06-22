import base64
import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.utils import timezone

from apps.core.models import AgentApiKey, Profile

AGENT_API_KEY_PREFIX = "rsk_"
AGENT_API_KEY_VISIBLE_PREFIX_LENGTH = 12
AGENT_API_KEY_LAST_USED_UPDATE_INTERVAL = timedelta(minutes=5)


@dataclass(frozen=True)
class AgentApiKeyCredential:
    agent_api_key: AgentApiKey
    raw_key: str


def normalize_agent_api_key_name(name: str) -> str:
    normalized = (name or "").strip()
    if not normalized:
        raise ValueError("Agent name is required.")
    if len(normalized) > AgentApiKey._meta.get_field("name").max_length:
        raise ValueError("Agent name must be 80 characters or fewer.")
    return normalized


def hash_agent_api_key(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _agent_api_key_fernet() -> Fernet:
    key = base64.urlsafe_b64encode(
        hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
    )
    return Fernet(key)


def encrypt_agent_api_key_token(token: str) -> str:
    return _agent_api_key_fernet().encrypt(token.encode("utf-8")).decode("utf-8")


def get_agent_api_key_token(agent_api_key: AgentApiKey) -> str | None:
    if not agent_api_key.token_ciphertext:
        return None
    try:
        return (
            _agent_api_key_fernet()
            .decrypt(agent_api_key.token_ciphertext.encode("utf-8"))
            .decode("utf-8")
        )
    except InvalidToken:
        return None


def generate_agent_api_key_token() -> str:
    return f"{AGENT_API_KEY_PREFIX}{secrets.token_urlsafe(32)}"


def create_agent_api_key(profile: Profile, name: str) -> AgentApiKeyCredential:
    normalized_name = normalize_agent_api_key_name(name)
    agent_api_key = AgentApiKey(
        profile=profile,
        name=normalized_name,
    )
    raw_key = generate_agent_api_key_token()
    agent_api_key.key_prefix = raw_key[:AGENT_API_KEY_VISIBLE_PREFIX_LENGTH]
    agent_api_key.token_hash = hash_agent_api_key(raw_key)
    agent_api_key.token_ciphertext = encrypt_agent_api_key_token(raw_key)
    agent_api_key.save()
    return AgentApiKeyCredential(agent_api_key=agent_api_key, raw_key=raw_key)


def _resolve_agent_api_key_by_hash(token: str) -> AgentApiKey | None:
    return (
        AgentApiKey.objects.select_related("profile__user")
        .filter(
            token_hash=hash_agent_api_key(token),
            revoked_at__isnull=True,
        )
        .first()
    )


def _mark_agent_api_key_used(agent_api_key: AgentApiKey) -> None:
    now = timezone.now()
    if (
        agent_api_key.last_used_at
        and agent_api_key.last_used_at > now - AGENT_API_KEY_LAST_USED_UPDATE_INTERVAL
    ):
        return
    AgentApiKey.objects.filter(pk=agent_api_key.pk).update(last_used_at=now, updated_at=now)
    agent_api_key.last_used_at = now
    agent_api_key.updated_at = now


def resolve_api_key_profile(raw_key: str) -> tuple[Profile, AgentApiKey | None] | None:
    token = (raw_key or "").strip()
    if not token:
        return None

    agent_api_key = _resolve_agent_api_key_by_hash(token)
    if agent_api_key is not None:
        _mark_agent_api_key_used(agent_api_key)
        return agent_api_key.profile, agent_api_key

    try:
        return Profile.objects.select_related("user").get(key=token), None
    except Profile.DoesNotExist:
        return None
