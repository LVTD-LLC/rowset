import uuid
from pathlib import Path

from django.contrib.auth.hashers import check_password
from django.contrib.postgres.indexes import GinIndex
from django.core.files.storage import storages
from django.core.validators import MaxLengthValidator
from django.db import models, transaction
from django.db.models.functions import Lower
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.urls import reverse
from django.utils import timezone

from apps.core.base_models import BaseModel
from apps.core.models import AgentApiKey, Profile
from apps.datasets.choices import DatasetAssetStatus, DatasetMutationType
from apps.datasets.constants import (
    MAX_DATASET_DESCRIPTION_LENGTH,
    MAX_DATASET_INSTRUCTIONS_LENGTH,
)

DATASET_ASSET_STORAGE_ALIAS = "dataset_assets"


def dataset_asset_storage():
    return storages[DATASET_ASSET_STORAGE_ALIAS]


def _asset_upload_extension(filename: str, fallback: str = ".bin") -> str:
    extension = Path(filename or "").suffix.lower()
    if not extension:
        return fallback
    return extension[:16]


def dataset_asset_upload_path(instance, filename: str) -> str:
    return (
        f"dataset-assets/{instance.profile_id}/{instance.dataset_id}/"
        f"{instance.key}/original{_asset_upload_extension(filename)}"
    )


def dataset_asset_thumbnail_upload_path(instance, filename: str) -> str:
    return (
        f"dataset-assets/{instance.profile_id}/{instance.dataset_id}/"
        f"{instance.key}/thumbnail{_asset_upload_extension(filename, '.jpg')}"
    )


class Project(BaseModel):
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="projects")
    key = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        ordering = ["name", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                "profile",
                Lower("name"),
                condition=models.Q(archived_at__isnull=True),
                name="unique_active_profile_project_name_ci",
            )
        ]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("project_detail", kwargs={"project_key": self.key})

    def get_settings_url(self):
        return reverse("project_settings", kwargs={"project_key": self.key})


class ProjectSection(BaseModel):
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="project_sections")
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="sections")
    key = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        ordering = ["project__name", "name", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                "project",
                Lower("name"),
                condition=models.Q(archived_at__isnull=True),
                name="unique_active_project_section_name_ci",
            )
        ]

    def __str__(self):
        return f"{self.project.name} / {self.name}"


class Dataset(BaseModel):
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="datasets")
    created_by_agent_api_key = models.ForeignKey(
        AgentApiKey,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_datasets",
    )
    updated_by_agent_api_key = models.ForeignKey(
        AgentApiKey,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="updated_datasets",
    )
    archived_by_agent_api_key = models.ForeignKey(
        AgentApiKey,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="archived_datasets",
    )
    project = models.ForeignKey(
        Project,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="datasets",
    )
    section = models.ForeignKey(
        ProjectSection,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="datasets",
    )
    key = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    name = models.CharField(max_length=255)
    description = models.TextField(
        blank=True,
        default="",
        validators=[MaxLengthValidator(MAX_DATASET_DESCRIPTION_LENGTH)],
    )
    instructions = models.TextField(
        blank=True,
        default="",
        validators=[MaxLengthValidator(MAX_DATASET_INSTRUCTIONS_LENGTH)],
    )
    metadata = models.JSONField(default=dict, blank=True)
    headers = models.JSONField(default=list)
    column_schema = models.JSONField(default=dict)
    preview_rows = models.JSONField(default=list)
    index_column = models.CharField(max_length=255, blank=True, default="")
    index_generated = models.BooleanField(default=False)
    public_key = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    public_enabled = models.BooleanField(default=False)
    public_page_size = models.PositiveIntegerField(default=10)
    public_password_hash = models.CharField(max_length=255, blank=True, default="")
    row_count = models.PositiveIntegerField(default=0)
    archived_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            GinIndex(
                fields=["description"],
                name="dataset_desc_trgm_idx",
                opclasses=["gin_trgm_ops"],
            ),
            GinIndex(
                fields=["instructions"],
                name="dataset_instr_trgm_idx",
                opclasses=["gin_trgm_ops"],
            ),
        ]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("dataset_detail", kwargs={"dataset_key": self.key})

    def get_changes_url(self):
        return reverse("dataset_changes", kwargs={"dataset_key": self.key})

    def get_settings_url(self):
        return reverse("dataset_settings", kwargs={"dataset_key": self.key})

    def get_public_url(self):
        return reverse("public_dataset", kwargs={"public_key": self.public_key})

    @property
    def is_public_password_protected(self) -> bool:
        return bool(self.public_password_hash)

    def public_password_matches(self, password: str) -> bool:
        if not self.public_password_hash:
            return True
        return check_password(password, self.public_password_hash)

    @property
    def created_by_actor_label(self) -> str:
        return agent_actor_label(self.created_by_agent_api_key)

    @property
    def updated_by_actor_label(self) -> str:
        return agent_actor_label(self.updated_by_agent_api_key)


class DatasetRow(BaseModel):
    dataset = models.ForeignKey(Dataset, on_delete=models.CASCADE, related_name="rows")
    created_by_agent_api_key = models.ForeignKey(
        AgentApiKey,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_dataset_rows",
    )
    updated_by_agent_api_key = models.ForeignKey(
        AgentApiKey,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="updated_dataset_rows",
    )
    row_number = models.PositiveIntegerField()
    index_value = models.CharField(max_length=1024, blank=True, default="")
    data = models.JSONField(default=dict)

    class Meta:
        ordering = ["row_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["dataset", "row_number"],
                name="unique_dataset_row_number",
            ),
            models.UniqueConstraint(
                fields=["dataset", "index_value"],
                name="unique_dataset_index_value",
            ),
        ]

    def __str__(self):
        return f"{self.dataset_id} row {self.row_number}"

    def get_absolute_url(self):
        return reverse(
            "dataset_row_detail",
            kwargs={"dataset_key": self.dataset.key, "row_id": self.id},
        )

    @property
    def created_by_actor_label(self) -> str:
        return agent_actor_label(self.created_by_agent_api_key)

    @property
    def updated_by_actor_label(self) -> str:
        return agent_actor_label(self.updated_by_agent_api_key)


class DatasetAsset(BaseModel):
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="dataset_assets")
    dataset = models.ForeignKey(Dataset, on_delete=models.CASCADE, related_name="assets")
    row = models.ForeignKey(DatasetRow, on_delete=models.CASCADE, related_name="assets")
    created_by_agent_api_key = models.ForeignKey(
        AgentApiKey,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_dataset_assets",
    )
    key = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    column_name = models.CharField(max_length=255)
    file = models.FileField(
        storage=dataset_asset_storage,
        upload_to=dataset_asset_upload_path,
        max_length=500,
    )
    thumbnail = models.FileField(
        storage=dataset_asset_storage,
        upload_to=dataset_asset_thumbnail_upload_path,
        max_length=500,
        blank=True,
    )
    original_filename = models.CharField(max_length=255, blank=True, default="")
    content_type = models.CharField(max_length=100)
    byte_size = models.PositiveIntegerField(default=0)
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    checksum = models.CharField(max_length=64, db_index=True)
    status = models.CharField(
        max_length=32,
        choices=DatasetAssetStatus.choices,
        default=DatasetAssetStatus.READY,
    )

    class Meta:
        ordering = ["dataset_id", "row_id", "column_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["row", "column_name"],
                name="unique_dataset_row_asset_column",
            ),
        ]
        indexes = [
            models.Index(fields=["profile", "dataset"], name="dataset_asset_owner_idx"),
            models.Index(fields=["dataset", "row"], name="dataset_asset_row_idx"),
        ]

    def __str__(self):
        return f"{self.dataset_id} row {self.row_id} {self.column_name}"

    @property
    def asset_ref(self) -> str:
        return f"asset:{self.key}"


class DatasetAssetFileDeletion(BaseModel):
    storage_alias = models.CharField(max_length=100, default=DATASET_ASSET_STORAGE_ALIAS)
    file_name = models.CharField(max_length=500)
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True, default="")
    last_attempted_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        ordering = ["deleted_at", "created_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["storage_alias", "file_name"],
                name="unique_dataset_asset_file_del",
            ),
        ]
        indexes = [
            models.Index(
                fields=["deleted_at", "created_at"],
                name="dataset_asset_del_pending_idx",
            ),
        ]

    def __str__(self):
        return self.file_name


def record_dataset_asset_file_deletion_failure(
    storage_alias: str,
    file_name: str,
    exc: Exception,
) -> None:
    now = timezone.now()
    message = str(exc)[:1000]
    deletion, created = DatasetAssetFileDeletion.objects.get_or_create(
        storage_alias=storage_alias,
        file_name=file_name,
        defaults={
            "attempts": 1,
            "last_error": message,
            "last_attempted_at": now,
        },
    )
    if created:
        return
    DatasetAssetFileDeletion.objects.filter(pk=deletion.pk).update(
        attempts=models.F("attempts") + 1,
        last_error=message,
        last_attempted_at=now,
        deleted_at=None,
        updated_at=now,
    )


def retry_dataset_asset_file_deletions(limit: int = 100) -> dict[str, int]:
    pending = list(
        DatasetAssetFileDeletion.objects.filter(deleted_at__isnull=True).order_by(
            "created_at", "id"
        )[:limit]
    )
    result = {"attempted": len(pending), "deleted": 0, "failed": 0}
    for deletion in pending:
        now = timezone.now()
        try:
            storages[deletion.storage_alias].delete(deletion.file_name)
        except Exception as exc:
            deletion.attempts += 1
            deletion.last_error = str(exc)[:1000]
            deletion.last_attempted_at = now
            deletion.save(
                update_fields=[
                    "attempts",
                    "last_error",
                    "last_attempted_at",
                    "updated_at",
                ]
            )
            result["failed"] += 1
        else:
            deletion.deleted_at = now
            deletion.last_error = ""
            deletion.last_attempted_at = now
            deletion.save(
                update_fields=[
                    "deleted_at",
                    "last_error",
                    "last_attempted_at",
                    "updated_at",
                ]
            )
            result["deleted"] += 1
    return result


@receiver(post_delete, sender=DatasetAsset)
def delete_dataset_asset_files(sender, instance: DatasetAsset, **kwargs) -> None:
    file_names = [
        (DATASET_ASSET_STORAGE_ALIAS, field.name)
        for field in (instance.file, instance.thumbnail)
        if field and field.name
    ]
    if not file_names:
        return

    def delete_files() -> None:
        # Asset paths include the immutable asset key, so a replacement asset
        # for the same row and column cannot reuse these captured file names.
        for storage_alias, name in file_names:
            try:
                storages[storage_alias].delete(name)
            except Exception as exc:
                record_dataset_asset_file_deletion_failure(storage_alias, name, exc)

    transaction.on_commit(delete_files)


class DatasetRelationship(BaseModel):
    profile = models.ForeignKey(
        Profile,
        on_delete=models.CASCADE,
        related_name="dataset_relationships",
    )
    key = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    source_dataset = models.ForeignKey(
        Dataset,
        on_delete=models.CASCADE,
        related_name="outgoing_relationships",
    )
    target_dataset = models.ForeignKey(
        Dataset,
        on_delete=models.CASCADE,
        related_name="incoming_relationships",
    )
    name = models.CharField(max_length=120)
    source_column = models.CharField(max_length=255)
    target_index_column = models.CharField(max_length=255)
    enforce_integrity = models.BooleanField(default=True)

    class Meta:
        ordering = ["source_dataset__name", "name", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                "source_dataset",
                Lower("name"),
                name="unique_dataset_relationship_name_ci",
            ),
            models.UniqueConstraint(
                fields=[
                    "source_dataset",
                    "source_column",
                    "target_dataset",
                    "target_index_column",
                ],
                name="unique_dataset_relationship_path",
            ),
        ]
        indexes = [
            models.Index(
                fields=["profile", "source_dataset"],
                name="dataset_rel_source_idx",
            ),
            models.Index(
                fields=["profile", "target_dataset"],
                name="dataset_rel_target_idx",
            ),
        ]

    def __str__(self):
        return f"{self.source_dataset_id}.{self.source_column} -> {self.target_dataset_id}"


class DatasetMutation(BaseModel):
    dataset = models.ForeignKey(Dataset, on_delete=models.CASCADE, related_name="mutations")
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="dataset_mutations")
    agent_api_key = models.ForeignKey(
        AgentApiKey,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="dataset_mutations",
    )
    actor_label = models.CharField(max_length=120, default="Account")
    mutation_type = models.CharField(max_length=64, choices=DatasetMutationType.choices)
    summary = models.CharField(max_length=255)
    target_type = models.CharField(max_length=32, blank=True, default="")
    target_identifier = models.CharField(max_length=255, blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(
                fields=["dataset", "-created_at"],
                name="dataset_mut_dataset_time_idx",
            )
        ]

    def __str__(self):
        return f"{self.dataset_id} {self.mutation_type}"


def agent_actor_label(agent_api_key: AgentApiKey | None) -> str:
    if agent_api_key is None:
        return "Account"
    return agent_api_key.name
