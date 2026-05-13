from django.db import models


class DatasetStatus(models.TextChoices):
    PREVIEWED = "previewed", "Previewed"
    PROCESSING = "processing", "Processing"
    READY = "ready", "Ready"
    FAILED = "failed", "Failed"
