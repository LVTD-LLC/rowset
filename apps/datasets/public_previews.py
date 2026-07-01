import hashlib
from collections.abc import MutableMapping
from dataclasses import dataclass
from typing import Any

from django.contrib.auth.hashers import make_password

from apps.core.models import AgentApiKey
from apps.datasets.choices import DatasetMutationType, DatasetStatus
from apps.datasets.history import record_dataset_mutation
from apps.datasets.models import Dataset
from apps.datasets.services import normalize_public_page_size

PUBLIC_ACCESS_SESSION_PREFIX = "public_dataset_access_"
PUBLIC_PREVIEW_ROBOTS_POLICY = "noindex, nofollow, noarchive"
PUBLIC_PREVIEW_SETTINGS_UPDATED_MESSAGE = "Public preview settings updated."


class PublicPreviewSettingsError(ValueError):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


@dataclass(frozen=True)
class PublicPreviewSettingsUpdate:
    settings_changed: bool
    previous_public_enabled: bool
    public_enabled: bool
    previous_public_page_size: int
    public_page_size: int
    previous_password_protected: bool
    password_protected: bool
    password_changed: bool

    @property
    def mutation_metadata(self) -> dict[str, Any]:
        return {
            "previous_public_enabled": self.previous_public_enabled,
            "public_enabled": self.public_enabled,
            "previous_public_page_size": self.previous_public_page_size,
            "public_page_size": self.public_page_size,
            "previous_password_protected": self.previous_password_protected,
            "password_protected": self.password_protected,
            "password_changed": self.password_changed,
        }


def public_preview_access_session_key(dataset: Dataset) -> str:
    return f"{PUBLIC_ACCESS_SESSION_PREFIX}{dataset.public_key}"


def public_preview_access_session_value(dataset: Dataset) -> str:
    return hashlib.sha256(dataset.public_password_hash.encode()).hexdigest()


def has_public_preview_access(session: MutableMapping[str, Any], dataset: Dataset) -> bool:
    return not dataset.is_public_password_protected or session.get(
        public_preview_access_session_key(dataset)
    ) == public_preview_access_session_value(dataset)


def grant_public_preview_access(session: MutableMapping[str, Any], dataset: Dataset) -> None:
    session[public_preview_access_session_key(dataset)] = public_preview_access_session_value(
        dataset
    )


def update_public_preview_settings(
    dataset: Dataset,
    *,
    public_enabled: bool | None = None,
    public_page_size: int | None = None,
    public_password: str | None = None,
    clear_public_password: bool = False,
    agent_api_key: AgentApiKey | None = None,
) -> PublicPreviewSettingsUpdate:
    if clear_public_password and public_password is not None:
        raise PublicPreviewSettingsError(
            400,
            "Use either public_password or clear_public_password, not both.",
        )

    previous_public_enabled = dataset.public_enabled
    previous_public_page_size = dataset.public_page_size
    previous_password_protected = dataset.is_public_password_protected
    next_public_enabled = dataset.public_enabled if public_enabled is None else public_enabled

    if next_public_enabled and dataset.status != DatasetStatus.READY:
        raise PublicPreviewSettingsError(
            409,
            "Public previews can only be enabled for ready datasets.",
        )

    dataset.public_enabled = next_public_enabled
    if public_page_size is not None:
        dataset.public_page_size = normalize_public_page_size(public_page_size)

    password_changed = False
    if clear_public_password:
        password_changed = bool(dataset.public_password_hash)
        if password_changed:
            dataset.public_password_hash = ""
    elif public_password is not None:
        normalized_password = public_password.strip()
        if not normalized_password:
            raise PublicPreviewSettingsError(400, "Public preview password cannot be blank.")
        dataset.public_password_hash = make_password(normalized_password)
        password_changed = True

    result = PublicPreviewSettingsUpdate(
        settings_changed=(
            dataset.public_enabled != previous_public_enabled
            or dataset.public_page_size != previous_public_page_size
            or password_changed
        ),
        previous_public_enabled=previous_public_enabled,
        public_enabled=dataset.public_enabled,
        previous_public_page_size=previous_public_page_size,
        public_page_size=dataset.public_page_size,
        previous_password_protected=previous_password_protected,
        password_protected=dataset.is_public_password_protected,
        password_changed=password_changed,
    )

    if result.settings_changed:
        dataset.updated_by_agent_api_key = agent_api_key
        dataset.save(
            update_fields=[
                "public_enabled",
                "public_page_size",
                "public_password_hash",
                "updated_by_agent_api_key",
                "updated_at",
            ]
        )
        record_dataset_mutation(
            dataset,
            DatasetMutationType.PUBLIC_PREVIEW_UPDATED,
            PUBLIC_PREVIEW_SETTINGS_UPDATED_MESSAGE,
            agent_api_key=agent_api_key,
            target_type="public_preview",
            metadata=result.mutation_metadata,
        )

    return result
