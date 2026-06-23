import uuid

from django.contrib.auth.hashers import check_password
from django.core.validators import MaxLengthValidator
from django.db import models
from django.db.models.functions import Lower
from django.urls import reverse

from apps.core.base_models import BaseModel
from apps.core.models import AgentApiKey, Profile
from apps.datasets.choices import DatasetMutationType, DatasetStatus
from apps.datasets.constants import MAX_CSV_UPLOAD_BYTES


class Project(BaseModel):
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="projects")
    key = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["name", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                "profile",
                Lower("name"),
                name="unique_profile_project_name_ci",
            )
        ]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("project_detail", kwargs={"project_key": self.key})


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
    key = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    name = models.CharField(max_length=255)
    original_filename = models.CharField(max_length=255)
    file_type = models.CharField(max_length=32, default="csv")
    source_file = models.FileField(upload_to="datasets/csv/%Y/%m/%d/", blank=True)
    source_url = models.URLField(blank=True, default="", max_length=2000)
    source_text = models.TextField(
        blank=True,
        default="",
        validators=[MaxLengthValidator(MAX_CSV_UPLOAD_BYTES)],
    )
    status = models.CharField(
        max_length=32,
        choices=DatasetStatus.choices,
        default=DatasetStatus.PREVIEWED,
    )
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
    parse_error = models.TextField(blank=True, default="")
    confirmed_at = models.DateTimeField(null=True, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("dataset_detail", kwargs={"dataset_key": self.key})

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
        return _agent_actor_label(self.created_by_agent_api_key)

    @property
    def updated_by_actor_label(self) -> str:
        return _agent_actor_label(self.updated_by_agent_api_key)


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
        return _agent_actor_label(self.created_by_agent_api_key)

    @property
    def updated_by_actor_label(self) -> str:
        return _agent_actor_label(self.updated_by_agent_api_key)


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


def _agent_actor_label(agent_api_key: AgentApiKey | None) -> str:
    if agent_api_key is None:
        return "Account"
    return agent_api_key.name
