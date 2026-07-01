import base64
import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core.analytics import (
    ROWSET_AGENT_API_KEY_CREATED,
    track_activation_event,
)
from apps.core.choices import AgentApiKeyAccessLevel
from apps.core.models import AgentApiKey, Profile
from rowset.utils import get_rowset_logger

AGENT_API_KEY_PREFIX = "rsk_"
AGENT_API_KEY_VISIBLE_PREFIX_LENGTH = 12
AGENT_API_KEY_LAST_USED_UPDATE_INTERVAL = timedelta(minutes=5)
logger = get_rowset_logger(__name__)
AGENT_API_KEY_ACCESS_LEVEL_ORDER = {
    AgentApiKeyAccessLevel.READ: 0,
    AgentApiKeyAccessLevel.READ_WRITE: 1,
    AgentApiKeyAccessLevel.ADMIN: 2,
}
LEGACY_PROFILE_KEY_ACCESS_LEVEL = AgentApiKeyAccessLevel.READ


@dataclass(frozen=True)
class AgentApiKeyCredential:
    agent_api_key: AgentApiKey
    raw_key: str


def get_or_create_profile_for_user(user) -> Profile:
    try:
        with transaction.atomic():
            profile, _created = Profile.objects.get_or_create(user=user)
    except IntegrityError:
        logger.warning(
            "Recovering existing profile after concurrent profile creation",
            user_id=user.id,
            exc_info=True,
        )
        profile = Profile.objects.filter(user=user).first()
        if profile is None:
            raise
    return profile


def normalize_agent_api_key_name(name: str) -> str:
    normalized = (name or "").strip()
    if not normalized:
        raise ValueError("Key name is required.")
    if len(normalized) > AgentApiKey._meta.get_field("name").max_length:
        raise ValueError("Key name must be 80 characters or fewer.")
    return normalized


def normalize_agent_api_key_access_level(access_level: str | None) -> str:
    if access_level is None or str(access_level).strip() == "":
        return AgentApiKeyAccessLevel.READ_WRITE

    normalized = str(access_level).strip().lower()
    compact = normalized.replace(" ", "").replace("-", "").replace("_", "")
    aliases = {
        "read": AgentApiKeyAccessLevel.READ,
        "readonly": AgentApiKeyAccessLevel.READ,
        "readwrite": AgentApiKeyAccessLevel.READ_WRITE,
        "read+write": AgentApiKeyAccessLevel.READ_WRITE,
        "read/write": AgentApiKeyAccessLevel.READ_WRITE,
        "write": AgentApiKeyAccessLevel.READ_WRITE,
        "admin": AgentApiKeyAccessLevel.ADMIN,
    }
    try:
        return aliases[compact]
    except KeyError as exc:
        valid_labels = ", ".join(label for _value, label in AgentApiKeyAccessLevel.choices)
        raise ValueError(f"Permission must be one of: {valid_labels}.") from exc


def agent_api_key_allows(
    agent_api_key: AgentApiKey | None,
    required_access_level: str,
) -> bool:
    required = normalize_agent_api_key_access_level(required_access_level)
    actual = normalize_agent_api_key_access_level(
        LEGACY_PROFILE_KEY_ACCESS_LEVEL if agent_api_key is None else agent_api_key.access_level
    )
    return AGENT_API_KEY_ACCESS_LEVEL_ORDER[actual] >= AGENT_API_KEY_ACCESS_LEVEL_ORDER[required]


def require_agent_api_key_access(
    agent_api_key: AgentApiKey | None,
    required_access_level: str,
) -> None:
    if agent_api_key_allows(agent_api_key, required_access_level):
        return

    required = normalize_agent_api_key_access_level(required_access_level)
    required_label = AgentApiKeyAccessLevel(required).label
    actual = (
        LEGACY_PROFILE_KEY_ACCESS_LEVEL if agent_api_key is None else agent_api_key.access_level
    )
    actual_label = AgentApiKeyAccessLevel(actual).label
    raise PermissionError(
        f"This Rowset API key has {actual_label} access, but this action requires "
        f"{required_label} access."
    )


def serialize_agent_api_key(agent_api_key: AgentApiKey) -> dict:
    return {
        "uuid": str(agent_api_key.uuid),
        "name": agent_api_key.name,
        "key_prefix": agent_api_key.key_prefix,
        "access_level": agent_api_key.access_level,
        "access_level_label": agent_api_key.get_access_level_display(),
        "created_at": agent_api_key.created_at,
        "last_used_at": agent_api_key.last_used_at,
        "revoked_at": agent_api_key.revoked_at,
    }


def hash_agent_api_key(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _agent_api_key_fernet(secret_key: str) -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(secret_key.encode("utf-8")).digest())
    return Fernet(key)


def _agent_api_key_fernets() -> MultiFernet:
    secret_keys = [
        settings.SECRET_KEY,
        *getattr(settings, "SECRET_KEY_FALLBACKS", []),
    ]
    return MultiFernet([_agent_api_key_fernet(secret_key) for secret_key in secret_keys])


def encrypt_agent_api_key_token(token: str) -> str:
    return _agent_api_key_fernets().encrypt(token.encode("utf-8")).decode("utf-8")


def get_agent_api_key_token(agent_api_key: AgentApiKey) -> str | None:
    if not agent_api_key.token_ciphertext:
        return None
    try:
        return (
            _agent_api_key_fernets()
            .decrypt(agent_api_key.token_ciphertext.encode("utf-8"))
            .decode("utf-8")
        )
    except InvalidToken:
        return None


def generate_agent_api_key_token() -> str:
    return f"{AGENT_API_KEY_PREFIX}{secrets.token_urlsafe(32)}"


def create_agent_api_key(
    profile: Profile,
    name: str,
    access_level: str | None = AgentApiKeyAccessLevel.READ_WRITE,
) -> AgentApiKeyCredential:
    normalized_name = normalize_agent_api_key_name(name)
    normalized_access_level = normalize_agent_api_key_access_level(access_level)
    agent_api_key = AgentApiKey(
        profile=profile,
        name=normalized_name,
        access_level=normalized_access_level,
    )
    raw_key = generate_agent_api_key_token()
    agent_api_key.key_prefix = raw_key[:AGENT_API_KEY_VISIBLE_PREFIX_LENGTH]
    agent_api_key.token_hash = hash_agent_api_key(raw_key)
    agent_api_key.token_ciphertext = encrypt_agent_api_key_token(raw_key)
    agent_api_key.save()
    track_activation_event(
        profile,
        ROWSET_AGENT_API_KEY_CREATED,
        {
            "created_agent_api_key_id": agent_api_key.id,
            "created_agent_api_key_access_level": agent_api_key.access_level,
        },
        source_function="create_agent_api_key",
    )
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
