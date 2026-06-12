from django.db import models


class DatasetStatus(models.TextChoices):
    PREVIEWED = "previewed", "Previewed"
    PROCESSING = "processing", "Processing"
    READY = "ready", "Ready"
    FAILED = "failed", "Failed"


class DatasetColumnType(models.TextChoices):
    TEXT = "text", "Text"
    INTEGER = "integer", "Integer"
    NUMBER = "number", "Number"
    CURRENCY = "currency", "Currency"
    BOOLEAN = "boolean", "Boolean"
    DATE = "date", "Date"
    DATETIME = "datetime", "Date/time"
    EMAIL = "email", "Email"
    URL = "url", "URL"
