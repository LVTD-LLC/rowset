import hashlib
import hmac
from collections.abc import MutableMapping
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.db import transaction

from apps.core.models import AgentApiKey
from apps.datasets.choices import DatasetMutationType
from apps.datasets.history import record_dataset_mutation
from apps.datasets.models import Dataset
from apps.datasets.services import normalize_public_page_size
from rowset.public_request_context import PublicDatasetContentSurface
from rowset.utils import build_absolute_public_url

PUBLIC_ACCESS_SESSION_PREFIX = "public_dataset_access_"
PUBLIC_PREVIEW_ROBOTS_POLICY = "noindex, nofollow, noarchive"
PUBLIC_PREVIEW_SETTINGS_UPDATED_MESSAGE = "Public preview settings updated."
PublicDatasetAccessState = Literal["available", "locked", "denied", "disabled", "not_found"]


def public_dataset_content_id(public_key: UUID | str) -> str:
    canonical_public_key = str(public_key).lower().encode()
    digest = hmac.new(
        settings.SECRET_KEY.encode(),
        canonical_public_key,
        hashlib.sha256,
    ).hexdigest()
    return f"pd_v1_{digest[:24]}"


def set_public_dataset_request_context(
    request: Any,
    *,
    access_state: PublicDatasetAccessState,
    content_surface: PublicDatasetContentSurface | None = None,
    dataset: Dataset | None = None,
    public_key: UUID | str | None = None,
) -> None:
    request._rowset_public_access_state = access_state
    request._rowset_public_content_surface = content_surface or ""
    content_public_key = dataset.public_key if dataset is not None else public_key
    if access_state == "available" and content_public_key is not None:
        request._rowset_public_content_id = public_dataset_content_id(content_public_key)
    elif hasattr(request, "_rowset_public_content_id"):
        del request._rowset_public_content_id


def build_public_dataset_agent_prompt(dataset: Dataset) -> str:
    public_key = str(dataset.public_key)
    metadata_url = build_absolute_public_url(f"/api/public/datasets/{public_key}")
    rows_url = build_absolute_public_url(f"/api/public/datasets/{public_key}/rows")
    access_instruction = (
        "This dataset is password protected. Ask the user for the public password separately, "
        "then send it only in X-Rowset-Public-Password on every request. Never put the password "
        "in a URL or expose it in output."
        if dataset.is_public_password_protected
        else "No API key or public password is required for these public read endpoints."
    )
    return "\n".join(
        [
            "Read this Rowset public dataset through its read-only API.",
            "",
            f"Public metadata: {metadata_url}",
            f"Public rows: {rows_url}",
            "",
            access_instruction,
            "",
            "Fetch all rows by requesting the public rows URL with limit=500 and offset=0. "
            "Append response.rows, increase offset by the number of returned rows, and repeat "
            "while has_more is true.",
            "The rows endpoint also accepts query, filters, sort, and direction parameters.",
            "Public access is read-only. Do not call authenticated or write endpoints unless the "
            "user separately authorizes and provides private credentials.",
        ]
    )


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
    normalized_password = None
    if public_password is not None:
        normalized_password = public_password.strip()
        if not normalized_password:
            raise PublicPreviewSettingsError(400, "Public preview password cannot be blank.")

    dataset.public_enabled = next_public_enabled
    if public_page_size is not None:
        dataset.public_page_size = normalize_public_page_size(public_page_size)

    password_changed = False
    if clear_public_password:
        password_changed = bool(dataset.public_password_hash)
        if password_changed:
            dataset.public_password_hash = ""
    elif normalized_password is not None:
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
        with transaction.atomic():
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
