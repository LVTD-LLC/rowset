import base64
import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import timedelta

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from django_q.tasks import async_task

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
from apps.core.choices import AgentApiKeyAccessLevel, FeedbackSource
from apps.core.models import AgentApiKey, Feedback, Profile
from apps.datasets.choices import DatasetColumnType
from apps.datasets.models import Dataset, DatasetRow, Project, ProjectSection
from rowset.utils import build_absolute_public_url, get_rowset_logger

AGENT_API_KEY_PREFIX = "rsk_"
AGENT_API_KEY_VISIBLE_PREFIX_LENGTH = 12
AGENT_API_KEY_LAST_USED_UPDATE_INTERVAL = timedelta(minutes=5)
MAX_FEEDBACK_LENGTH = 2000
MAX_FEEDBACK_PAGE_LENGTH = 255
MAX_FEEDBACK_METADATA_BYTES = 8000
logger = get_rowset_logger(__name__)
FEEDBACK_DATASET_KEY = "021e385f-83e4-4e3a-a6e0-883530222f6d"
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
FEEDBACK_ROW_URL_METADATA_KEY = "rowset_row_url"
AGENT_API_KEY_ACCESS_LEVEL_ORDER = {
    AgentApiKeyAccessLevel.READ: 0,
    AgentApiKeyAccessLevel.READ_WRITE: 1,
    AgentApiKeyAccessLevel.ADMIN: 2,
}


@dataclass(frozen=True)
class AgentApiKeyCredential:
    agent_api_key: AgentApiKey
    raw_key: str


@dataclass(frozen=True)
class FeedbackSubmissionResult:
    feedback: Feedback
    dataset: Dataset | None
    row: DatasetRow | None
    row_url: str


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

    try:
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
    except DatasetServiceError as exc:
        if exc.status_code != 409:
            raise
    else:
        return Dataset.objects.get(profile=profile, key=result["dataset"]["key"])

    dataset = _active_feedback_dataset(profile, project, section)
    if dataset is None:
        raise DatasetServiceError(409, "Dataset name already exists.")
    return dataset


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


def _configured_feedback_dataset() -> Dataset | None:
    dataset = (
        Dataset.objects.select_related("profile")
        .filter(key=FEEDBACK_DATASET_KEY, archived_at__isnull=True)
        .first()
    )
    if dataset is None:
        if getattr(settings, "ENVIRONMENT", "") == "prod":
            raise DatasetServiceError(503, "Feedback dataset is not configured.")
        return None

    if not _is_feedback_dataset_compatible(dataset):
        raise DatasetServiceError(409, "Feedback dataset schema is incompatible.")
    return dataset


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
    if agent_api_key is None:
        return False
    required = normalize_agent_api_key_access_level(required_access_level)
    actual = normalize_agent_api_key_access_level(agent_api_key.access_level)
    return AGENT_API_KEY_ACCESS_LEVEL_ORDER[actual] >= AGENT_API_KEY_ACCESS_LEVEL_ORDER[required]


def require_agent_api_key_access(
    agent_api_key: AgentApiKey | None,
    required_access_level: str,
) -> None:
    if agent_api_key_allows(agent_api_key, required_access_level):
        return

    if agent_api_key is None:
        raise PermissionError("This action requires an active Rowset agent API key.")

    required = normalize_agent_api_key_access_level(required_access_level)
    required_label = AgentApiKeyAccessLevel(required).label
    actual_label = AgentApiKeyAccessLevel(agent_api_key.access_level).label
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


def _normalize_feedback_text(feedback: str) -> str:
    normalized = str(feedback or "").strip()
    if not normalized:
        raise ValueError("Feedback is required.")
    if len(normalized) > MAX_FEEDBACK_LENGTH:
        raise ValueError(f"Feedback must be {MAX_FEEDBACK_LENGTH} characters or fewer.")
    return normalized


def _normalize_feedback_page(page: str | None) -> str:
    normalized = str(page or "").strip()
    if len(normalized) > MAX_FEEDBACK_PAGE_LENGTH:
        raise ValueError(f"Feedback page must be {MAX_FEEDBACK_PAGE_LENGTH} characters or fewer.")
    return normalized


def _normalize_feedback_source(source: str) -> str:
    try:
        return FeedbackSource(source).value
    except ValueError as exc:
        valid_sources = ", ".join(value for value, _label in FeedbackSource.choices)
        raise ValueError(f"Feedback source must be one of: {valid_sources}.") from exc


def _normalize_feedback_metadata(metadata: dict | None) -> dict:
    if metadata is None:
        return {}
    if not isinstance(metadata, dict):
        raise ValueError("Feedback context must be a JSON object.")
    try:
        serialized = json.dumps(metadata, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise ValueError("Feedback context must be JSON-serializable.") from exc
    if len(serialized.encode("utf-8")) > MAX_FEEDBACK_METADATA_BYTES:
        raise ValueError(f"Feedback context must be {MAX_FEEDBACK_METADATA_BYTES} bytes or fewer.")
    return json.loads(serialized)


def _feedback_metadata_text(metadata: dict) -> str:
    if not metadata:
        return ""
    return json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def serialize_feedback(feedback: Feedback) -> dict:
    return {
        "uuid": str(feedback.uuid),
        "source": feedback.source,
        "created_at": feedback.created_at.isoformat(),
    }


def serialize_feedback_submission_result(
    result: FeedbackSubmissionResult,
    *,
    feedback_context: dict | None = None,
    include_feedback_id: bool = False,
) -> dict:
    feedback_payload = serialize_feedback(result.feedback)
    feedback_payload["page"] = result.feedback.page
    if include_feedback_id:
        feedback_payload["id"] = result.feedback.id
    if feedback_context is not None:
        feedback_payload["context"] = feedback_context

    return {
        "status": "success",
        "message": "Feedback submitted successfully.",
        "feedback": feedback_payload,
        "dataset": str(result.dataset.key) if result.dataset else "",
        "row": result.row.id if result.row else None,
        "row_url": result.row_url,
    }


def queue_feedback_notification(feedback: Feedback) -> None:
    if not getattr(settings, "ROWSET_FEEDBACK_APPRISE_URLS", ()):
        return

    transaction.on_commit(
        lambda: async_task(
            "apps.core.tasks.notify_feedback_apprise",
            feedback.id,
            group="Feedback Notification",
        )
    )


def submit_profile_feedback(
    *,
    profile: Profile | None,
    feedback: str,
    page: str | None = "",
    source: str = FeedbackSource.BROWSER,
    metadata: dict | None = None,
    agent_api_key: AgentApiKey | None = None,
) -> FeedbackSubmissionResult:
    if profile is not None and agent_api_key is not None and agent_api_key.profile_id != profile.id:
        raise ValueError("Agent API key does not belong to this profile.")

    normalized_source = _normalize_feedback_source(source)
    normalized_feedback = _normalize_feedback_text(feedback)
    normalized_page = _normalize_feedback_page(page)
    normalized_metadata = _normalize_feedback_metadata(metadata)
    context_text = _feedback_metadata_text(normalized_metadata)

    feedback_record = Feedback.objects.create(
        profile=profile,
        agent_api_key=agent_api_key if profile is not None else None,
        source=normalized_source,
        feedback=normalized_feedback,
        page=normalized_page,
        metadata=normalized_metadata,
    )
    if profile is None:
        queue_feedback_notification(feedback_record)
        return FeedbackSubmissionResult(
            feedback=feedback_record,
            dataset=None,
            row=None,
            row_url="",
        )

    with transaction.atomic():
        dataset = _configured_feedback_dataset()
        if dataset is None:
            target_profile = profile
            Profile.objects.select_for_update().only("id").get(id=target_profile.id)
            project = _get_or_create_feedback_project(target_profile)
            section = _get_or_create_feedback_section(target_profile, project)
            dataset = _get_or_create_feedback_dataset(
                target_profile,
                project,
                section,
                agent_api_key=agent_api_key,
            )
        else:
            target_profile = dataset.profile
            Profile.objects.select_for_update().only("id").get(id=target_profile.id)

        row_result = create_profile_dataset_row(
            target_profile,
            str(dataset.key),
            _feedback_dataset_row_data(feedback_record, normalized_source, context_text),
            agent_api_key=agent_api_key,
        )
        row = DatasetRow.objects.select_related("dataset").get(id=row_result["row"]["id"])
        row_url = build_absolute_public_url(row.get_absolute_url())
        feedback_record.metadata = {
            **normalized_metadata,
            FEEDBACK_ROW_URL_METADATA_KEY: row_url,
        }
        feedback_record.save(update_fields=["metadata", "updated_at"])
        queue_feedback_notification(feedback_record)

    return FeedbackSubmissionResult(
        feedback=feedback_record,
        dataset=dataset,
        row=row,
        row_url=row_url,
    )


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


def resolve_api_key_profile(raw_key: str) -> tuple[Profile, AgentApiKey] | None:
    token = (raw_key or "").strip()
    if not token:
        return None

    agent_api_key = _resolve_agent_api_key_by_hash(token)
    if agent_api_key is not None:
        _mark_agent_api_key_used(agent_api_key)
        return agent_api_key.profile, agent_api_key

    return None
