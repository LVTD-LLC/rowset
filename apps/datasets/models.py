import uuid

from django.db import models
from django.urls import reverse

from apps.core.base_models import BaseModel
from apps.core.models import Profile
from apps.datasets.choices import DatasetStatus


class Dataset(BaseModel):
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="datasets")
    key = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    name = models.CharField(max_length=255)
    original_filename = models.CharField(max_length=255)
    source_file = models.FileField(upload_to="datasets/csv/%Y/%m/%d/")
    status = models.CharField(
        max_length=32,
        choices=DatasetStatus.choices,
        default=DatasetStatus.PREVIEWED,
    )
    headers = models.JSONField(default=list)
    preview_rows = models.JSONField(default=list)
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
    data = models.JSONField(default=dict)

    class Meta:
        ordering = ["row_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["dataset", "row_number"],
                name="unique_dataset_row_number",
            )
        ]

    def __str__(self):
        return f"{self.dataset_id} row {self.row_number}"
