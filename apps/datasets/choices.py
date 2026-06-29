from django.db import models


class DatasetStatus(models.TextChoices):
    PREVIEWED = "previewed", "Previewed"
    PROCESSING = "processing", "Processing"
    READY = "ready", "Ready"
    FAILED = "failed", "Failed"


class DatasetColumnType(models.TextChoices):
    TEXT = "text", "Text"
    CHOICE = "choice", "Choice"
    REFERENCE = "reference", "Reference"
    IMAGE = "image", "Image"
    INTEGER = "integer", "Integer"
    NUMBER = "number", "Number"
    CURRENCY = "currency", "Currency"
    BOOLEAN = "boolean", "Boolean"
    DATE = "date", "Date"
    DATETIME = "datetime", "Date/time"
    EMAIL = "email", "Email"
    URL = "url", "URL"


class DatasetAssetStatus(models.TextChoices):
    READY = "ready", "Ready"


class DatasetMutationType(models.TextChoices):
    DATASET_CREATED = "dataset.created", "Dataset created"
    DATASET_ARCHIVED = "dataset.archived", "Dataset archived"
    DATASET_RESTORED = "dataset.restored", "Dataset restored"
    DATASET_METADATA_UPDATED = "dataset.metadata_updated", "Metadata updated"
    DATASET_PROJECT_UPDATED = "dataset.project_updated", "Project updated"
    PUBLIC_PREVIEW_UPDATED = "dataset.public_preview_updated", "Public preview updated"
    RELATIONSHIP_CREATED = "relationship.created", "Relationship created"
    RELATIONSHIP_DELETED = "relationship.deleted", "Relationship deleted"
    COLUMN_TYPES_UPDATED = "schema.column_types_updated", "Column types updated"
    COLUMN_ADDED = "schema.column_added", "Column added"
    COLUMN_RENAMED = "schema.column_renamed", "Column renamed"
    COLUMN_DROPPED = "schema.column_dropped", "Column dropped"
    COLUMNS_REORDERED = "schema.columns_reordered", "Columns reordered"
    ROW_CREATED = "row.created", "Row created"
    ROW_UPDATED = "row.updated", "Row updated"
    ROW_DELETED = "row.deleted", "Row deleted"
