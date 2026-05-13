import uuid

from django.core.validators import MaxLengthValidator
from django.db import models
from django.urls import reverse

from apps.core.base_models import BaseModel
from apps.core.models import Profile
from apps.datasets.choices import DatasetStatus
from apps.datasets.constants import MAX_CSV_UPLOAD_BYTES


class Dataset(BaseModel):
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="datasets")
    key = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    name = models.CharField(max_length=255)
    original_filename = models.CharField(max_length=255)
    file_type = models.CharField(max_length=32, default="csv")
    source_file = models.FileField(upload_to="datasets/csv/%Y/%m/%d/")
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
    preview_rows = models.JSONField(default=list)
    index_column = models.CharField(max_length=255, blank=True, default="")
    index_generated = models.BooleanField(default=False)
    row_count = models.PositiveIntegerField(default=0)
    parse_error = models.TextField(blank=True, default="")
    confirmed_at = models.DateTimeField(null=True, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("dataset_detail", kwargs={"dataset_key": self.key})


class DatasetRow(BaseModel):
    dataset = models.ForeignKey(Dataset, on_delete=models.CASCADE, related_name="rows")
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
            )
        ]

    def __str__(self):
        return f"{self.dataset_id} row {self.row_number}"
