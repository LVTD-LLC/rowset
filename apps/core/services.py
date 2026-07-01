import base64
import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.api.services import (
    DatasetServiceError,
    create_profile_dataset,
    create_profile_dataset_row,
    create_profile_project,
    create_profile_project_section,
)
from apps.core.analytics import (
    ROWSET_AGENT_API_KEY_CREATED,
    track_activation_event,
)
from apps.core.choices import AgentApiKeyAccessLevel
from apps.core.models import AgentApiKey, Feedback, Profile
from apps.datasets.choices import DatasetColumnType, DatasetStatus
from apps.datasets.models import Dataset, DatasetRow, Project, ProjectSection
from rowset.utils import build_absolute_public_url, get_rowset_logger

AGENT_API_KEY_PREFIX = "rsk_"
AGENT_API_KEY_VISIBLE_PREFIX_LENGTH = 12
AGENT_API_KEY_LAST_USED_UPDATE_INTERVAL = timedelta(minutes=5)
logger = get_rowset_logger(__name__)
FEEDBACK_PROJECT_NAME = "Rowset"
FEEDBACK_SECTION_NAME = "CX"
FEEDBACK_DATASET_NAME = "Feedback"
FEEDBACK_DATASET_INDEX_COLUMN = "feedback_id"
FEEDBACK_DATASET_HEADERS = [
    FEEDBACK_DATASET_INDEX_COLUMN,
    "submitted_at",
    "submitted_via",
    "user_email",
    "profile_id",
    "page",
    "context",
    "feedback",
]
FEEDBACK_DATASET_COLUMN_TYPES = {
    "feedback_id": DatasetColumnType.INTEGER,
    "submitted_at": DatasetColumnType.DATETIME,
    "submitted_via": DatasetColumnType.TEXT,
    "user_email": DatasetColumnType.EMAIL,
    "profile_id": DatasetColumnType.INTEGER,
    "page": DatasetColumnType.TEXT,
    "context": DatasetColumnType.TEXT,
    "feedback": DatasetColumnType.TEXT,
}
FEEDBACK_DATASET_METADATA = {
    "system": {
        "kind": "rowset_feedback",
        "version": 1,
    }
}
MAX_FEEDBACK_CONTEXT_CHARS = 2000
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


@dataclass(frozen=True)
class FeedbackSubmissionResult:
    feedback: Feedback
    dataset: Dataset
    row: DatasetRow
    row_url: str


def _normalize_feedback_text(feedback: str) -> str:
    normalized = str(feedback or "").strip()
    if not normalized:
        raise ValueError("Feedback is required.")
    if len(normalized) > 2000:
        raise ValueError("Feedback must be 2,000 characters or fewer.")
    return normalized


def _normalize_feedback_page(page: str | None) -> str:
    normalized = str(page or "").strip()
    if len(normalized) > Feedback._meta.get_field("page").max_length:
        raise ValueError("Page must be 255 characters or fewer.")
    return normalized


def _normalize_feedback_source(submitted_via: str | None) -> str:
    normalized = str(submitted_via or "").strip().lower()
    return normalized or "unknown"


def _normalize_feedback_context(context: dict[str, Any] | None) -> dict[str, Any]:
    if context is None:
        return {}
    if not isinstance(context, dict):
        raise ValueError("Context must be a JSON object.")
    context_text = _feedback_context_text(context)
    if len(context_text) > MAX_FEEDBACK_CONTEXT_CHARS:
        raise ValueError("Context must serialize to 2,000 characters or fewer.")
    return context


def _feedback_context_text(context: dict[str, Any]) -> str:
    if not context:
        return ""
    try:
        return json.dumps(context, sort_keys=True, separators=(",", ":"))
    except TypeError as exc:
        raise ValueError("Context must be JSON serializable.") from exc


def _active_project_by_name(profile: Profile, name: str) -> Project | None:
    return (
        Project.objects.filter(
            profile=profile,
            archived_at__isnull=True,
            name__iexact=name,
        )
        .order_by("name", "id")
        .first()
    )


def _get_or_create_feedback_project(profile: Profile) -> Project:
    project = _active_project_by_name(profile, FEEDBACK_PROJECT_NAME)
    if project is not None:
        return project

    try:
        result = create_profile_project(
            profile,
            name=FEEDBACK_PROJECT_NAME,
            description="Rowset product operations and customer experience datasets.",
            metadata={"system": {"kind": "rowset_project", "version": 1}},
        )
    except DatasetServiceError as exc:
        if exc.status_code != 409:
            raise
    else:
        return Project.objects.get(profile=profile, key=result["project"]["key"])

    project = _active_project_by_name(profile, FEEDBACK_PROJECT_NAME)
    if project is None:
        raise DatasetServiceError(409, "Project name already exists.")
    return project


def _active_project_section_by_name(
    profile: Profile,
    project: Project,
    name: str,
) -> ProjectSection | None:
    return (
        ProjectSection.objects.filter(
            profile=profile,
            project=project,
            project__archived_at__isnull=True,
            archived_at__isnull=True,
            name__iexact=name,
        )
        .order_by("name", "id")
        .first()
    )


def _get_or_create_feedback_section(profile: Profile, project: Project) -> ProjectSection:
    section = _active_project_section_by_name(profile, project, FEEDBACK_SECTION_NAME)
    if section is not None:
        return section

    try:
        result = create_profile_project_section(
            profile,
            str(project.key),
            name=FEEDBACK_SECTION_NAME,
            description="Customer experience feedback submitted through Rowset.",
            metadata={"system": {"kind": "rowset_feedback_section", "version": 1}},
        )
    except DatasetServiceError as exc:
        if exc.status_code != 409:
            raise
    else:
        return ProjectSection.objects.get(profile=profile, key=result["section"]["key"])

    section = _active_project_section_by_name(profile, project, FEEDBACK_SECTION_NAME)
    if section is None:
        raise DatasetServiceError(409, "Project section name already exists.")
    return section


def _is_feedback_dataset_compatible(dataset: Dataset) -> bool:
    return (
        dataset.index_column == FEEDBACK_DATASET_INDEX_COLUMN
        and dataset.status == DatasetStatus.READY
        and all(header in dataset.headers for header in FEEDBACK_DATASET_HEADERS)
    )


def _active_feedback_dataset(
    profile: Profile,
    project: Project,
    section: ProjectSection,
) -> Dataset | None:
    candidates = Dataset.objects.filter(
        profile=profile,
        project=project,
        section=section,
        archived_at__isnull=True,
        name__iexact=FEEDBACK_DATASET_NAME,
    ).order_by("-created_at", "-id")
    for dataset in candidates:
        if _is_feedback_dataset_compatible(dataset):
            return dataset
    return None


def _get_or_create_feedback_dataset(
    profile: Profile,
    project: Project,
    section: ProjectSection,
    *,
    agent_api_key: AgentApiKey | None = None,
) -> Dataset:
    dataset = _active_feedback_dataset(profile, project, section)
    if dataset is not None:
        return dataset

    result = create_profile_dataset(
        profile,
        name=FEEDBACK_DATASET_NAME,
        description="Product feedback submitted through Rowset app and MCP surfaces.",
        instructions=(
            "Use feedback_id as the stable index. Treat rows as private product feedback "
            "for triage, follow-up, and customer experience analysis."
        ),
        metadata=FEEDBACK_DATASET_METADATA,
        headers=FEEDBACK_DATASET_HEADERS,
        rows=[],
        index_column=FEEDBACK_DATASET_INDEX_COLUMN,
        column_types=FEEDBACK_DATASET_COLUMN_TYPES,
        project_key=str(project.key),
        section_key=str(section.key),
        agent_api_key=agent_api_key,
    )
    return Dataset.objects.get(profile=profile, key=result["dataset"]["key"])


def _feedback_dataset_row_data(
    feedback: Feedback,
    submitted_via: str,
    context_text: str,
) -> dict[str, str]:
    profile = feedback.profile
    return {
        "feedback_id": str(feedback.id),
        "submitted_at": feedback.created_at.isoformat(),
        "submitted_via": submitted_via,
        "user_email": profile.user.email if profile else "",
        "profile_id": str(profile.id) if profile else "",
        "page": feedback.page,
        "context": context_text,
        "feedback": feedback.feedback,
    }


def submit_profile_feedback(
    profile: Profile,
    feedback: str,
    *,
    page: str | None = "",
    submitted_via: str | None = "web",
    context: dict[str, Any] | None = None,
    agent_api_key: AgentApiKey | None = None,
) -> FeedbackSubmissionResult:
    normalized_feedback = _normalize_feedback_text(feedback)
    normalized_page = _normalize_feedback_page(page)
    normalized_source = _normalize_feedback_source(submitted_via)
    normalized_context = _normalize_feedback_context(context)
    context_text = _feedback_context_text(normalized_context)

    project = _get_or_create_feedback_project(profile)
    section = _get_or_create_feedback_section(profile, project)
    dataset = _get_or_create_feedback_dataset(
        profile,
        project,
        section,
        agent_api_key=agent_api_key,
    )

    with transaction.atomic():
        feedback_record = Feedback(
            profile=profile,
            feedback=normalized_feedback,
            page=normalized_page,
        )
        feedback_record._skip_feedback_notification = True
        feedback_record.save()
        row_result = create_profile_dataset_row(
            profile,
            str(dataset.key),
            _feedback_dataset_row_data(feedback_record, normalized_source, context_text),
            agent_api_key=agent_api_key,
        )
        row = DatasetRow.objects.select_related("dataset").get(id=row_result["row"]["id"])
        row_url = build_absolute_public_url(row.get_absolute_url())

    feedback_record.send_notification(
        dataset_row_url=row_url,
        submitted_via=normalized_source,
        feedback_context=context_text,
    )
    return FeedbackSubmissionResult(
        feedback=feedback_record,
        dataset=dataset,
        row=row,
        row_url=row_url,
    )


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
