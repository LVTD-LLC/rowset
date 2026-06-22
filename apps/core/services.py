import base64
import binascii
import hashlib
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac

from apps.core.models import AgentApiKey, Profile

AGENT_API_KEY_PREFIX = "rsk_"
AGENT_API_KEY_VISIBLE_PREFIX_LENGTH = 12
AGENT_API_KEY_LAST_USED_UPDATE_INTERVAL = timedelta(minutes=5)
AGENT_API_KEY_SIGNATURE_LENGTH = 32
AGENT_API_KEY_SIGNATURE_SALT = "apps.core.agent_api_key"


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


def _agent_api_key_signature(uuid_text: str) -> str:
    return salted_hmac(
        AGENT_API_KEY_SIGNATURE_SALT,
        uuid_text,
        algorithm="sha256",
    ).hexdigest()[:AGENT_API_KEY_SIGNATURE_LENGTH]


def _encode_agent_api_key_uuid(uuid_text: str) -> str:
    return base64.urlsafe_b64encode(uuid_text.encode("ascii")).decode("ascii").rstrip("=")


def _decode_agent_api_key_uuid(encoded_uuid: str) -> str | None:
    padding = "=" * (-len(encoded_uuid) % 4)
    try:
        decoded = base64.urlsafe_b64decode(f"{encoded_uuid}{padding}").decode("ascii")
        return str(UUID(decoded))
    except (ValueError, UnicodeDecodeError, binascii.Error):
        return None


def generate_agent_api_key_token(agent_api_key: AgentApiKey) -> str:
    uuid_text = str(agent_api_key.uuid)
    encoded_uuid = _encode_agent_api_key_uuid(uuid_text)
    signature = _agent_api_key_signature(uuid_text)
    return f"{AGENT_API_KEY_PREFIX}{encoded_uuid}.{signature}"


def get_agent_api_key_token(agent_api_key: AgentApiKey) -> str:
    return generate_agent_api_key_token(agent_api_key)


def parse_agent_api_key_token(token: str) -> UUID | None:
    if not token.startswith(AGENT_API_KEY_PREFIX):
        return None

    try:
        encoded_uuid, provided_signature = token[len(AGENT_API_KEY_PREFIX) :].split(".", 1)
    except ValueError:
        return None

    uuid_text = _decode_agent_api_key_uuid(encoded_uuid)
    if uuid_text is None:
        return None

    expected_signature = _agent_api_key_signature(uuid_text)
    if not constant_time_compare(provided_signature, expected_signature):
        return None
    return UUID(uuid_text)


def create_agent_api_key(profile: Profile, name: str) -> AgentApiKeyCredential:
    normalized_name = normalize_agent_api_key_name(name)
    agent_api_key = AgentApiKey(
        profile=profile,
        name=normalized_name,
    )
    raw_key = generate_agent_api_key_token(agent_api_key)
    agent_api_key.key_prefix = raw_key[:AGENT_API_KEY_VISIBLE_PREFIX_LENGTH]
    agent_api_key.token_hash = hash_agent_api_key(raw_key)
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


def _resolve_agent_api_key_by_signed_token(token: str) -> AgentApiKey | None:
    agent_api_key_uuid = parse_agent_api_key_token(token)
    if agent_api_key_uuid is None:
        return None
    return (
        AgentApiKey.objects.select_related("profile__user")
        .filter(
            uuid=agent_api_key_uuid,
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

    agent_api_key = (
        _resolve_agent_api_key_by_hash(token)
        or _resolve_agent_api_key_by_signed_token(token)
    )
    if agent_api_key is not None:
        _mark_agent_api_key_used(agent_api_key)
        return agent_api_key.profile, agent_api_key

    try:
        return Profile.objects.select_related("user").get(key=token), None
    except Profile.DoesNotExist:
        return None
