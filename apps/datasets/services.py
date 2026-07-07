import base64
import binascii
import csv
import hashlib
import io
import json
import re
import sqlite3
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import UUID
from xml.sax.saxutils import escape

import polars as pl
from django.conf import settings
from django.db.models import (
    Case,
    DateTimeField,
    F,
    FloatField,
    Func,
    Q,
    TextField,
    Value,
    When,
)
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Cast, Concat, Lower, Replace, Substr, Trim
from django.utils import timezone
from PIL import Image, ImageOps, UnidentifiedImageError

from apps.datasets.choices import DatasetColumnType
from apps.datasets.constants import (
    MAX_COLUMN_DESCRIPTION_LENGTH,
    MAX_DATASET_IMAGE_BYTES,
    MAX_DATASET_IMAGE_PIXELS,
)
from apps.datasets.embeddings import (
    EmbeddingProvider,
    EmbeddingProviderError,
    get_embedding_provider,
)
from apps.datasets.vector_search import (
    DatasetRowVector,
    QdrantVectorStore,
    VectorStoreError,
    build_dataset_row_search_document,
)


class DatasetValidationError(ValueError):
    pass


class DatasetRowQueryError(ValueError):
    pass


class DatasetImageError(ValueError):
    pass


@dataclass(frozen=True)
class _DatasetRowsQueryContext:
    dataset_id: int
    headers: list[str]
    column_map: dict[str, dict[str, Any]]
    filters: dict[str, str]
    filter_operators: dict[str, str]


@dataclass(frozen=True)
class VectorBackfillError:
    row_id: int
    message: str


@dataclass(frozen=True)
class VectorBackfillResult:
    rows_seen: int = 0
    indexed: int = 0
    would_index: int = 0
    failed: int = 0
    errors: list[VectorBackfillError] = field(default_factory=list)


DEFAULT_VECTOR_BACKFILL_BATCH_SIZE = 100
GENERATED_INDEX_BASENAME = "rowset_id"
DEFAULT_PUBLIC_PAGE_SIZE = 10
MAX_PUBLIC_PAGE_SIZE = 100
DATASET_ASSET_REF_PREFIX = "asset:"
DATASET_ASSET_KEY_ERRORS = (AttributeError, TypeError, ValueError)
DATASET_ASSET_CACHE_CONTROL = "private, max-age=86400, immutable"
DATASET_IMAGE_THUMBNAIL_SIZE = (512, 512)
DATASET_IMAGE_ALLOWED_FORMATS = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
}
COLUMN_TYPE_SAMPLE_LIMIT = 200
COLUMN_SCHEMA_TYPE_KEY = "type"
COLUMN_SCHEMA_CHOICES_KEY = "choices"
COLUMN_SCHEMA_DESCRIPTION_KEY = "description"
COLUMN_SCHEMA_REFERENCE_TARGET_KEY = "target"
DATASET_REFERENCE_TARGET = "dataset"
PROJECT_REFERENCE_TARGET = "project"
ROW_DEFAULT_SORT = "row_number"
ROW_SORT_DESC = "desc"
ROW_SEARCH_COLUMN_LIMIT = 20


def project_section_dataset_groups(
    sections: list[Any],
    datasets: list[Any],
    *,
    unsectioned_dataset_count: int | None = None,
) -> list[dict[str, Any]]:
    """Group project datasets by active section, with unmatched datasets left unsectioned."""
    section_ids = {getattr(section, "id", None) for section in sections}
    datasets_by_section_id: dict[int, list[Any]] = {}
    unsectioned_datasets = []

    for dataset in datasets:
        section_id = getattr(dataset, "section_id", None)
        if section_id in section_ids:
            datasets_by_section_id.setdefault(section_id, []).append(dataset)
        else:
            unsectioned_datasets.append(dataset)

    groups = []
    for section in sections:
        section_datasets = datasets_by_section_id.get(section.id, [])
        dataset_count = getattr(section, "dataset_count", None)
        if dataset_count is None:
            dataset_count = len(section_datasets)
        if not section_datasets and not dataset_count:
            continue
        groups.append(
            {
                "label": section.name,
                "section": section,
                "dataset_count": dataset_count,
                "datasets": section_datasets,
            }
        )

    dataset_count = (
        unsectioned_dataset_count
        if unsectioned_dataset_count is not None
        else len(unsectioned_datasets)
    )
    if unsectioned_datasets or dataset_count:
        groups.append(
            {
                "label": "Unsectioned",
                "section": None,
                "dataset_count": dataset_count,
                "datasets": unsectioned_datasets,
            }
        )

    return groups


ROW_FILTER_ABOVE = "above"
ROW_FILTER_BELOW = "below"
ROW_FILTER_CONTAINS = "contains"
ROW_FILTER_IS = "is"
ROW_BOOLEAN_TRUE_VALUES = ("true", "1", "yes", "y")
ROW_BOOLEAN_FALSE_VALUES = ("false", "0", "no", "n")
ROW_NUMERIC_SORT_TYPES = {
    DatasetColumnType.CURRENCY,
    DatasetColumnType.INTEGER,
    DatasetColumnType.NUMBER,
}
ROW_DATETIME_SORT_TYPES = {
    DatasetColumnType.DATE,
    DatasetColumnType.DATETIME,
}
ROW_ORDERED_FILTER_TYPES = ROW_NUMERIC_SORT_TYPES | ROW_DATETIME_SORT_TYPES
ROW_NUMERIC_SORT_PATTERN = r"^-?\d+(\.\d+)?$"
ROW_NUMERIC_FILTER_PATTERN = r"-?\d+(\.\d+)?"
ROW_YEAR_PATTERN = r"(000[1-9]|00[1-9][0-9]|0[1-9][0-9]{2}|[1-9][0-9]{3})"
ROW_NON_CENTURY_LEAP_YEAR_PATTERN = r"[0-9]{2}(0[48]|[2468][048]|[13579][26])"
ROW_CENTURY_LEAP_YEAR_PATTERN = r"(0[48]|[2468][048]|[13579][26])00"
ROW_LEAP_YEAR_PATTERN = rf"({ROW_NON_CENTURY_LEAP_YEAR_PATTERN}|{ROW_CENTURY_LEAP_YEAR_PATTERN})"
ROW_MONTH_DAY_PATTERN = (
    r"((01|03|05|07|08|10|12)-(0[1-9]|[12][0-9]|3[01])"
    r"|(04|06|09|11)-(0[1-9]|[12][0-9]|30)"
    r"|02-(0[1-9]|1[0-9]|2[0-8]))"
)
ROW_SLASH_MONTH_DAY_PATTERN = (
    r"((0?[13578]|1[02])/(0?[1-9]|[12][0-9]|3[01])"
    r"|(0?[469]|11)/(0?[1-9]|[12][0-9]|30)"
    r"|0?2/(0?[1-9]|1[0-9]|2[0-8]))"
)
ROW_ISO_DATE_PATTERN = (
    rf"({ROW_YEAR_PATTERN}-{ROW_MONTH_DAY_PATTERN}|{ROW_LEAP_YEAR_PATTERN}-02-29)"
)
ROW_TIME_PATTERN = (
    r"([T ]([01][0-9]|2[0-3]):[0-5][0-9]"
    r"(:[0-5][0-9](\.[0-9]{1,6})?)?"
    r"(Z|[+-]([01][0-9]|2[0-3]):[0-5][0-9])?)?"
)
ROW_SPACE_TIME_PATTERN = (
    r"( ([01]?[0-9]|2[0-3]):[0-5]?[0-9]"
    r"(:[0-5]?[0-9](\.[0-9]{1,6})?)?)?"
)
ROW_DATETIME_SORT_PATTERN = rf"^{ROW_ISO_DATE_PATTERN}{ROW_TIME_PATTERN}$"
ROW_SLASH_YMD_DATE_PATTERN = (
    rf"({ROW_YEAR_PATTERN}/{ROW_SLASH_MONTH_DAY_PATTERN}|{ROW_LEAP_YEAR_PATTERN}/0?2/0?29)"
)
ROW_SLASH_MDY_DATE_PATTERN = (
    rf"({ROW_SLASH_MONTH_DAY_PATTERN}/{ROW_YEAR_PATTERN}|0?2/0?29/{ROW_LEAP_YEAR_PATTERN})"
)
ROW_SLASH_YMD_DATETIME_SORT_PATTERN = rf"^{ROW_SLASH_YMD_DATE_PATTERN}{ROW_SPACE_TIME_PATTERN}$"
ROW_SLASH_MDY_DATETIME_SORT_PATTERN = rf"^{ROW_SLASH_MDY_DATE_PATTERN}{ROW_SPACE_TIME_PATTERN}$"
ROW_FILTER_OPERATOR_ALIASES = {
    "eq": ROW_FILTER_IS,
    "equals": ROW_FILTER_IS,
    "gt": ROW_FILTER_ABOVE,
    "greater_than": ROW_FILTER_ABOVE,
    "lt": ROW_FILTER_BELOW,
    "less_than": ROW_FILTER_BELOW,
}

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
INTEGER_RE = re.compile(r"^[+-]?\d+$")
NUMBER_RE = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)$")
CURRENCY_SYMBOLS = "$€£¥₹"
COLUMN_TYPE_ALIASES = {
    "bool": DatasetColumnType.BOOLEAN,
    "decimal": DatasetColumnType.NUMBER,
    "enum": DatasetColumnType.CHOICE,
    "float": DatasetColumnType.NUMBER,
    "money": DatasetColumnType.CURRENCY,
    "select": DatasetColumnType.CHOICE,
    "single_select": DatasetColumnType.CHOICE,
    "dataset_reference": DatasetColumnType.REFERENCE,
    "project_reference": DatasetColumnType.REFERENCE,
    "rowset_reference": DatasetColumnType.REFERENCE,
    "rowset_project": DatasetColumnType.REFERENCE,
    "image_url": DatasetColumnType.IMAGE,
    "img": DatasetColumnType.IMAGE,
    "str": DatasetColumnType.TEXT,
    "string": DatasetColumnType.TEXT,
    "timestamp": DatasetColumnType.DATETIME,
}
REFERENCE_TYPE_TARGET_ALIASES = {
    "dataset_reference": DATASET_REFERENCE_TARGET,
    "rowset_reference": DATASET_REFERENCE_TARGET,
    "project_reference": PROJECT_REFERENCE_TARGET,
    "rowset_project": PROJECT_REFERENCE_TARGET,
}
REFERENCE_TARGET_ALIASES = {
    "dataset": DATASET_REFERENCE_TARGET,
    "datasets": DATASET_REFERENCE_TARGET,
    "rowset_dataset": DATASET_REFERENCE_TARGET,
    "project": PROJECT_REFERENCE_TARGET,
    "projects": PROJECT_REFERENCE_TARGET,
    "rowset_project": PROJECT_REFERENCE_TARGET,
}
BOOLEAN_VALUES = {"true", "false", "yes", "no", "y", "n", "1", "0"}
TEXTUAL_BOOLEAN_VALUES = BOOLEAN_VALUES - {"1", "0"}
CURRENCY_HEADER_TOKENS = {
    "amount",
    "cost",
    "currency",
    "fee",
    "money",
    "price",
    "revenue",
    "total",
}


def _validate_vector_backfill_dataset(dataset) -> None:
    if dataset.archived_at is not None:
        raise ValueError("Vector backfill cannot index archived datasets.")


def _dataset_rows_for_vector_backfill(dataset, *, limit: int | None = None):
    rows = dataset.rows.order_by("row_number", "id").only(
        "id",
        "dataset_id",
        "row_number",
        "index_value",
        "data",
    )
    if limit is not None:
        rows = rows[:limit]
    return rows


def _index_vector_backfill_batch(
    *,
    dataset,
    rows,
    embedding_provider: EmbeddingProvider,
    vector_store: QdrantVectorStore,
    stop_on_error: bool,
) -> tuple[int, list[VectorBackfillError]]:
    documents = [
        build_dataset_row_search_document(
            dataset,
            row,
            embedding_model=embedding_provider.model,
            embedding_dimensions=embedding_provider.dimensions,
        )
        for row in rows
    ]
    try:
        embeddings = embedding_provider.embed_texts([document.text for document in documents])
        if len(embeddings) != len(rows):
            raise ValueError(
                f"Embedding provider returned {len(embeddings)} result(s) for {len(rows)} row(s)."
            )
    except (EmbeddingProviderError, ValueError) as exc:
        if stop_on_error:
            raise
        return 0, [VectorBackfillError(row_id=row.id, message=str(exc)) for row in rows]

    row_vectors = [
        DatasetRowVector(
            row=row,
            vector=embedding.vector,
            embedding_model=embedding.model,
            embedding_dimensions=embedding.dimensions,
        )
        for row, embedding in zip(rows, embeddings, strict=True)
    ]
    try:
        vector_store.upsert_dataset_row_vectors(dataset, row_vectors)
    except (VectorStoreError, ValueError) as exc:
        if stop_on_error:
            raise
        return (
            0,
            [
                VectorBackfillError(row_id=row_vector.row.id, message=str(exc))
                for row_vector in row_vectors
            ],
        )

    return len(row_vectors), []


def backfill_dataset_vectors(
    dataset,
    *,
    embedding_provider: EmbeddingProvider | None = None,
    vector_store: QdrantVectorStore | None = None,
    dry_run: bool = False,
    limit: int | None = None,
    batch_size: int = DEFAULT_VECTOR_BACKFILL_BATCH_SIZE,
    stop_on_error: bool = False,
) -> VectorBackfillResult:
    _validate_vector_backfill_dataset(dataset)
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1.")
    if limit is not None and limit < 1:
        raise ValueError("limit must be at least 1 when provided.")

    provider = None if dry_run else embedding_provider or get_embedding_provider()
    store = None
    if not dry_run:
        store = vector_store or QdrantVectorStore(
            embedding_model=provider.model,
            embedding_dimensions=provider.dimensions,
        )
        store.ensure_collection()

    rows_seen = 0
    indexed = 0
    would_index = 0
    errors: list[VectorBackfillError] = []
    batch = []

    rows = _dataset_rows_for_vector_backfill(dataset, limit=limit)
    for row in rows.iterator(chunk_size=batch_size):
        rows_seen += 1
        if dry_run:
            would_index += 1
            continue

        batch.append(row)
        if len(batch) < batch_size:
            continue

        indexed_count, batch_errors = _index_vector_backfill_batch(
            dataset=dataset,
            rows=batch,
            embedding_provider=provider,
            vector_store=store,
            stop_on_error=stop_on_error,
        )
        indexed += indexed_count
        errors.extend(batch_errors)
        batch = []

    if batch:
        indexed_count, batch_errors = _index_vector_backfill_batch(
            dataset=dataset,
            rows=batch,
            embedding_provider=provider,
            vector_store=store,
            stop_on_error=stop_on_error,
        )
        indexed += indexed_count
        errors.extend(batch_errors)

    return VectorBackfillResult(
        rows_seen=rows_seen,
        indexed=indexed,
        would_index=would_index,
        failed=len(errors),
        errors=errors,
    )


def index_dataset_row_vector(
    row,
    *,
    embedding_provider: EmbeddingProvider | None = None,
    vector_store: QdrantVectorStore | None = None,
) -> None:
    dataset = row.dataset
    _validate_vector_backfill_dataset(dataset)
    provider = embedding_provider or get_embedding_provider()
    store = vector_store or QdrantVectorStore(
        embedding_model=provider.model,
        embedding_dimensions=provider.dimensions,
    )
    store.ensure_collection()
    document = build_dataset_row_search_document(
        dataset,
        row,
        embedding_model=provider.model,
        embedding_dimensions=provider.dimensions,
    )
    embedding = provider.embed_text(document.text)
    store.upsert_dataset_row_vector(
        dataset,
        row,
        embedding.vector,
        embedding_model=embedding.model,
        embedding_dimensions=embedding.dimensions,
    )


def delete_dataset_row_vectors(
    dataset,
    row_ids: list[int],
    *,
    vector_store: QdrantVectorStore | None = None,
) -> None:
    if not row_ids:
        return
    store = vector_store or QdrantVectorStore()
    store.delete_dataset_row_vectors(dataset, row_ids)


def delete_dataset_vectors(
    dataset,
    *,
    vector_store: QdrantVectorStore | None = None,
) -> None:
    store = vector_store or QdrantVectorStore()
    store.delete_dataset_vectors(dataset)


@dataclass(frozen=True)
class PreparedDatasetImage:
    filename: str
    content_type: str
    image_bytes: bytes
    thumbnail_bytes: bytes | None
    byte_size: int
    width: int
    height: int
    checksum: str


def ordered_row_values(headers: list[str], row_data: dict[str, object]) -> list[object]:
    return [row_data.get(header, "") for header in headers]


def _collect_column_samples(column_samples: dict[str, list[str]], row: dict[str, str]) -> None:
    for header, value in row.items():
        samples = column_samples.setdefault(header, [])
        normalized = str(value or "").strip()
        if normalized and len(samples) < COLUMN_TYPE_SAMPLE_LIMIT:
            samples.append(normalized)


def _header_tokens(header: str) -> set[str]:
    return {token for token in re.split(r"[^a-z0-9]+", header.lower()) if token}


def _looks_like_email(value: str) -> bool:
    return bool(EMAIL_RE.match(value))


def _looks_like_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _is_integer(value: str) -> bool:
    return bool(INTEGER_RE.match(value.replace(",", "")))


def _is_number(value: str) -> bool:
    return bool(NUMBER_RE.match(value.replace(",", "")))


def _decimal_from_currency(value: str) -> Decimal | None:
    normalized = value.strip()
    is_negative = normalized.startswith("(") and normalized.endswith(")")
    normalized = normalized.strip("()").strip()
    for symbol in CURRENCY_SYMBOLS:
        normalized = normalized.replace(symbol, "")
    normalized = normalized.replace(",", "").strip()
    if not normalized:
        return None
    try:
        decimal = Decimal(normalized)
    except InvalidOperation:
        return None
    return -decimal if is_negative else decimal


def _is_currency(value: str) -> bool:
    return _decimal_from_currency(value) is not None


def _has_currency_marker(value: str) -> bool:
    return any(symbol in value for symbol in CURRENCY_SYMBOLS)


def _has_decimal_component(value: str) -> bool:
    return not _is_integer(value) and _is_number(value)


def _parse_datetime(value: str) -> datetime | None:
    normalized = value.strip()
    if INTEGER_RE.match(normalized):
        return None

    normalized = normalized.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        pass

    formats = (
        "%Y/%m/%d",
        "%m/%d/%Y",
        "%Y/%m/%d %H:%M:%S.%f",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%m/%d/%Y %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y %H:%M",
    )
    for date_format in formats:
        try:
            return datetime.strptime(normalized, date_format)
        except ValueError:
            continue
    return None


def _is_date_only(value: str) -> bool:
    return "T" not in value and ":" not in value


def infer_column_type(header: str, values: list[str]) -> str:
    non_empty_values = [str(value or "").strip() for value in values if str(value or "").strip()]
    if not non_empty_values:
        return DatasetColumnType.TEXT

    tokens = _header_tokens(header)
    lowered = [value.lower() for value in non_empty_values]

    if all(_looks_like_email(value) for value in non_empty_values):
        return DatasetColumnType.EMAIL

    if all(_looks_like_url(value) for value in non_empty_values):
        return DatasetColumnType.URL

    if all(value in BOOLEAN_VALUES for value in lowered) and (
        any(value in TEXTUAL_BOOLEAN_VALUES for value in lowered)
        or bool(tokens & {"active", "archived", "enabled", "has", "is", "paid", "published"})
    ):
        return DatasetColumnType.BOOLEAN

    if all(_is_currency(value) for value in non_empty_values) and (
        any(_has_currency_marker(value) for value in non_empty_values)
        or bool(tokens & CURRENCY_HEADER_TOKENS)
        and any(_has_decimal_component(value) for value in non_empty_values)
    ):
        return DatasetColumnType.CURRENCY

    if all(_is_integer(value) for value in non_empty_values):
        return DatasetColumnType.INTEGER

    if all(_is_number(value) for value in non_empty_values):
        return DatasetColumnType.NUMBER

    parsed_datetimes = [_parse_datetime(value) for value in non_empty_values]
    if all(parsed_datetimes):
        if all(_is_date_only(value) for value in non_empty_values):
            return DatasetColumnType.DATE
        return DatasetColumnType.DATETIME

    return DatasetColumnType.TEXT


def _infer_column_schema_from_samples(
    headers: list[str],
    column_samples: dict[str, list[str]],
) -> dict[str, dict[str, Any]]:
    return {
        header: {COLUMN_SCHEMA_TYPE_KEY: infer_column_type(header, column_samples.get(header, []))}
        for header in headers
    }


def infer_column_schema(
    headers: list[str],
    rows: list[dict[str, str]],
) -> dict[str, dict[str, Any]]:
    column_samples: dict[str, list[str]] = {header: [] for header in headers}
    for row in rows:
        _collect_column_samples(column_samples, row)
    return _infer_column_schema_from_samples(headers, column_samples)


def normalize_column_type(column_type: str | None) -> str:
    normalized = str(column_type or "").strip().lower()
    normalized = COLUMN_TYPE_ALIASES.get(normalized, normalized)
    if normalized not in DatasetColumnType.values:
        allowed = ", ".join(DatasetColumnType.values)
        raise DatasetValidationError(
            f"Unsupported column type '{column_type}'. Use one of: {allowed}."
        )
    return normalized


def _column_type_from_schema_entry(entry, fallback_entry=None) -> str | None:
    if isinstance(entry, dict):
        raw_type = entry.get(COLUMN_SCHEMA_TYPE_KEY)
        if raw_type is None and isinstance(fallback_entry, dict):
            return fallback_entry.get(COLUMN_SCHEMA_TYPE_KEY)
        return raw_type
    return entry


def _normalize_column_description(header: str, raw_description) -> str:
    if raw_description is None:
        return ""
    if not isinstance(raw_description, str):
        raise DatasetValidationError(f"Column '{header}' description must be a string.")
    description = raw_description.strip()
    if len(description) > MAX_COLUMN_DESCRIPTION_LENGTH:
        raise DatasetValidationError(
            f"Column '{header}' description must be "
            f"{MAX_COLUMN_DESCRIPTION_LENGTH} characters or fewer."
        )
    return description


def _column_description_from_schema_entry(header: str, entry, fallback_entry) -> str:
    raw_description = None
    if isinstance(entry, dict) and COLUMN_SCHEMA_DESCRIPTION_KEY in entry:
        raw_description = entry.get(COLUMN_SCHEMA_DESCRIPTION_KEY)
    elif isinstance(fallback_entry, dict) and COLUMN_SCHEMA_DESCRIPTION_KEY in fallback_entry:
        raw_description = fallback_entry.get(COLUMN_SCHEMA_DESCRIPTION_KEY)
    return _normalize_column_description(header, raw_description)


def _normalize_choice_values(header: str, raw_choices) -> list[str]:
    if not isinstance(raw_choices, (list, tuple)):
        raise DatasetValidationError(f"Choice column '{header}' choices must be a list.")

    choices = []
    seen = set()
    duplicates = set()
    for raw_choice in raw_choices:
        choice = str("" if raw_choice is None else raw_choice).strip()
        if not choice:
            raise DatasetValidationError(
                f"Choice column '{header}' choices must be non-empty strings."
            )
        if choice in seen:
            duplicates.add(choice)
        seen.add(choice)
        choices.append(choice)

    if not choices:
        raise DatasetValidationError(f"Choice column '{header}' requires at least one choice.")

    if duplicates:
        joined = ", ".join(sorted(duplicates))
        raise DatasetValidationError(f"Choice column '{header}' choices must be unique: {joined}.")

    return choices


def _choice_source_entry(header: str, entry, fallback_entry):
    if isinstance(entry, dict) and COLUMN_SCHEMA_CHOICES_KEY in entry:
        return entry
    if isinstance(fallback_entry, dict) and COLUMN_SCHEMA_CHOICES_KEY in fallback_entry:
        return fallback_entry
    raise DatasetValidationError(f"Choice column '{header}' requires at least one choice.")


def _reference_target_from_schema_entry(entry, fallback_entry):
    if isinstance(entry, dict) and COLUMN_SCHEMA_REFERENCE_TARGET_KEY in entry:
        return entry.get(COLUMN_SCHEMA_REFERENCE_TARGET_KEY)
    if inferred_target := _reference_target_from_type_entry(entry):
        return inferred_target
    if isinstance(fallback_entry, dict) and COLUMN_SCHEMA_REFERENCE_TARGET_KEY in fallback_entry:
        return fallback_entry.get(COLUMN_SCHEMA_REFERENCE_TARGET_KEY)
    if inferred_target := _reference_target_from_type_entry(fallback_entry):
        return inferred_target
    return DATASET_REFERENCE_TARGET


def _reference_target_from_type_entry(entry) -> str:
    raw_type = entry.get(COLUMN_SCHEMA_TYPE_KEY) if isinstance(entry, dict) else entry
    normalized_type = str(raw_type or "").strip().lower()
    return REFERENCE_TYPE_TARGET_ALIASES.get(normalized_type, "")


def _normalize_reference_target(header: str, raw_target) -> str:
    normalized_target = str(raw_target or "").strip().lower()
    normalized_target = REFERENCE_TARGET_ALIASES.get(normalized_target, normalized_target)
    allowed_targets = {DATASET_REFERENCE_TARGET, PROJECT_REFERENCE_TARGET}
    if normalized_target not in allowed_targets:
        allowed = ", ".join(sorted(allowed_targets))
        raise DatasetValidationError(
            f"Reference column '{header}' target must be one of: {allowed}."
        )
    return normalized_target


def _normalize_column_schema_entry(header: str, entry, fallback_entry) -> dict[str, Any]:
    raw_type = _column_type_from_schema_entry(entry, fallback_entry)
    if raw_type is None:
        raw_type = DatasetColumnType.TEXT
    column_type = normalize_column_type(raw_type)
    normalized_entry: dict[str, Any] = {COLUMN_SCHEMA_TYPE_KEY: column_type}
    description = _column_description_from_schema_entry(header, entry, fallback_entry)
    if description:
        normalized_entry[COLUMN_SCHEMA_DESCRIPTION_KEY] = description
    if column_type == DatasetColumnType.CHOICE:
        source_entry = _choice_source_entry(header, entry, fallback_entry)
        normalized_entry[COLUMN_SCHEMA_CHOICES_KEY] = _normalize_choice_values(
            header,
            source_entry.get(COLUMN_SCHEMA_CHOICES_KEY),
        )
    if column_type == DatasetColumnType.REFERENCE:
        normalized_entry[COLUMN_SCHEMA_REFERENCE_TARGET_KEY] = _normalize_reference_target(
            header,
            _reference_target_from_schema_entry(entry, fallback_entry),
        )
    return normalized_entry


def dataset_asset_ref(asset_key) -> str:
    return f"{DATASET_ASSET_REF_PREFIX}{asset_key}"


def dataset_asset_key_from_ref(value: object) -> str:
    text = str(value or "").strip()
    if not text.startswith(DATASET_ASSET_REF_PREFIX):
        return ""
    raw_key = text.removeprefix(DATASET_ASSET_REF_PREFIX).strip()
    try:
        return str(UUID(raw_key))
    except DATASET_ASSET_KEY_ERRORS:
        return ""


def is_dataset_asset_ref(value: object) -> bool:
    return bool(dataset_asset_key_from_ref(value))


def image_columns_from_schema(headers: list[str], column_schema: dict | None) -> list[str]:
    normalized_schema = normalize_column_schema(headers, column_schema)
    return [
        header
        for header in headers
        if normalized_schema[header].get(COLUMN_SCHEMA_TYPE_KEY) == DatasetColumnType.IMAGE
    ]


def validate_image_row_values(
    headers: list[str],
    column_schema: dict | None,
    row_data: dict,
    *,
    columns: list[str] | set[str] | None = None,
    allow_asset_refs: bool = False,
) -> None:
    selected_columns = set(columns) if columns is not None else None
    for header in image_columns_from_schema(headers, column_schema):
        if selected_columns is not None and header not in selected_columns:
            continue
        value = str(row_data.get(header, "") or "").strip()
        if not value:
            continue
        if allow_asset_refs and is_dataset_asset_ref(value):
            continue
        raise DatasetValidationError(
            f"Column '{header}' is an image column. Leave it blank and attach an image asset."
        )


def normalize_column_schema(
    headers: list[str],
    column_schema: dict | None = None,
    *,
    fallback_schema: dict | None = None,
    reject_unknown: bool = False,
) -> dict[str, dict[str, Any]]:
    raw_schema = column_schema or {}
    fallback = fallback_schema or {}
    if reject_unknown:
        unknown_headers = sorted(set(raw_schema) - set(headers))
        if unknown_headers:
            joined = ", ".join(unknown_headers)
            raise DatasetValidationError(f"Column types include unknown headers: {joined}.")

    normalized_schema = {}
    for header in headers:
        raw_entry = None
        fallback_entry = fallback.get(header)
        if header in raw_schema:
            raw_entry = raw_schema[header]
        elif header in fallback:
            raw_entry = fallback_entry
        normalized_schema[header] = _normalize_column_schema_entry(
            header,
            raw_entry,
            fallback_entry,
        )
    return normalized_schema


def column_definitions(
    headers: list[str],
    column_schema: dict | None,
) -> list[dict[str, Any]]:
    normalized_schema = normalize_column_schema(headers, column_schema)
    labels = dict(DatasetColumnType.choices)
    definitions = []
    for header in headers:
        schema_entry = normalized_schema[header]
        definition = {
            "name": header,
            "type": schema_entry[COLUMN_SCHEMA_TYPE_KEY],
            "type_label": labels.get(schema_entry[COLUMN_SCHEMA_TYPE_KEY], "Text"),
            "description": schema_entry.get(COLUMN_SCHEMA_DESCRIPTION_KEY, ""),
        }
        if schema_entry[COLUMN_SCHEMA_TYPE_KEY] == DatasetColumnType.CHOICE:
            definition["choices"] = schema_entry[COLUMN_SCHEMA_CHOICES_KEY]
        if schema_entry[COLUMN_SCHEMA_TYPE_KEY] == DatasetColumnType.REFERENCE:
            definition["target"] = schema_entry[COLUMN_SCHEMA_REFERENCE_TARGET_KEY]
        definitions.append(definition)
    return definitions


def decode_image_base64(image_base64: str) -> bytes:
    payload = str(image_base64 or "").strip()
    if not payload:
        raise DatasetImageError("Image data is required.")
    if "," in payload and payload.split(",", 1)[0].lower().startswith("data:image/"):
        payload = payload.split(",", 1)[1]
    try:
        return base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise DatasetImageError("Image data must be valid base64.") from exc


def _safe_image_filename(filename: str | None, content_type: str) -> str:
    original = str(filename or "").strip().replace("\\", "/").rsplit("/", 1)[-1]
    original = re.sub(r"[^A-Za-z0-9._ -]+", "-", original).strip(" .")
    extension = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
    }[content_type]
    if not original:
        return f"image{extension}"
    if not Path(original).suffix:
        return f"{original}{extension}"
    return original[:255]


def _image_save_kwargs(image_format: str) -> dict[str, Any]:
    if image_format == "JPEG":
        return {"format": image_format, "quality": 90, "optimize": True}
    if image_format == "WEBP":
        return {"format": image_format, "quality": 90, "method": 4}
    return {"format": image_format, "optimize": True}


def _rgb_image(image: Image.Image) -> Image.Image:
    if image.mode in {"RGBA", "LA"}:
        background = Image.new("RGB", image.size, (255, 255, 255))
        alpha = image.getchannel("A") if "A" in image.getbands() else None
        background.paste(image, mask=alpha)
        return background
    if image.mode != "RGB":
        return image.convert("RGB")
    return image


def _encoded_image_bytes(image: Image.Image, image_format: str) -> bytes:
    output = io.BytesIO()
    if image_format == "JPEG":
        image = _rgb_image(image)
    image.save(output, **_image_save_kwargs(image_format))
    return output.getvalue()


def _thumbnail_bytes(image: Image.Image, original_bytes: bytes) -> bytes | None:
    thumbnail = image.copy()
    thumbnail.thumbnail(DATASET_IMAGE_THUMBNAIL_SIZE)
    output = io.BytesIO()
    _rgb_image(thumbnail).save(output, format="JPEG", quality=85, optimize=True)
    thumbnail_bytes = output.getvalue()
    if len(thumbnail_bytes) >= len(original_bytes):
        return None
    return thumbnail_bytes


def prepare_dataset_image(
    *,
    image_bytes: bytes,
    filename: str | None = None,
    content_type: str | None = None,
) -> PreparedDatasetImage:
    if not image_bytes:
        raise DatasetImageError("Image data is required.")
    if len(image_bytes) > MAX_DATASET_IMAGE_BYTES:
        raise DatasetImageError(
            f"Images must be {MAX_DATASET_IMAGE_BYTES // (1024 * 1024)} MB or smaller."
        )

    try:
        with Image.open(io.BytesIO(image_bytes)) as opened:
            image_format = str(opened.format or "").upper()
            if image_format not in DATASET_IMAGE_ALLOWED_FORMATS:
                raise DatasetImageError("Image must be a JPEG, PNG, or WebP file.")
            detected_content_type = DATASET_IMAGE_ALLOWED_FORMATS[image_format]
            supplied_content_type = str(content_type or "").split(";", 1)[0].strip().lower()
            if supplied_content_type and supplied_content_type != detected_content_type:
                raise DatasetImageError("Image content type does not match the uploaded file.")
            image = ImageOps.exif_transpose(opened)
            image.load()
            width, height = image.size
            if width <= 0 or height <= 0 or width * height > MAX_DATASET_IMAGE_PIXELS:
                raise DatasetImageError(
                    f"Images must be {MAX_DATASET_IMAGE_PIXELS:,} pixels or fewer."
                )
            sanitized_bytes = _encoded_image_bytes(image, image_format)
            if len(sanitized_bytes) > MAX_DATASET_IMAGE_BYTES:
                raise DatasetImageError(
                    f"Images must be {MAX_DATASET_IMAGE_BYTES // (1024 * 1024)} MB or smaller."
                )
            thumbnail_bytes = _thumbnail_bytes(image, sanitized_bytes)
    except DatasetImageError:
        raise
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise DatasetImageError("Image data could not be read safely.") from exc

    return PreparedDatasetImage(
        filename=_safe_image_filename(filename, detected_content_type),
        content_type=detected_content_type,
        image_bytes=sanitized_bytes,
        thumbnail_bytes=thumbnail_bytes,
        byte_size=len(sanitized_bytes),
        width=width,
        height=height,
        checksum=hashlib.sha256(sanitized_bytes).hexdigest(),
    )


def _choice_cell_value(value) -> str:
    if value is None:
        return ""
    return str(value)


def _choice_value_match_key(value: str) -> str:
    normalized = re.sub(r"[\s_-]+", " ", value.strip()).strip()
    return normalized.casefold()


def _canonical_choice_value(value: str, choices: list[str]) -> str | None:
    if value in choices:
        return value

    match_key = _choice_value_match_key(value)
    matches = [choice for choice in choices if _choice_value_match_key(choice) == match_key]
    if len(matches) == 1:
        return matches[0]
    return None


def choice_constraints_from_schema(
    headers: list[str],
    column_schema: dict | None,
    *,
    normalized: bool = False,
) -> dict[str, list[str]]:
    if normalized:
        normalized_schema = column_schema or {}
    else:
        normalized_schema = normalize_column_schema(headers, column_schema)
    constraints = {}
    for header in headers:
        schema_entry = normalized_schema.get(header, {})
        if not isinstance(schema_entry, dict):
            continue
        if schema_entry.get(COLUMN_SCHEMA_TYPE_KEY) == DatasetColumnType.CHOICE:
            constraints[header] = schema_entry[COLUMN_SCHEMA_CHOICES_KEY]
    return constraints


def validate_and_canonicalize_choice_row_values(
    headers: list[str],
    column_schema: dict | None,
    row_data: dict,
    *,
    columns: list[str] | set[str] | None = None,
    choice_constraints: dict[str, list[str]] | None = None,
) -> None:
    """Validate choice values and mutate row_data to store canonical schema labels."""
    constraints = choice_constraints
    if constraints is None:
        constraints = choice_constraints_from_schema(headers, column_schema)
    selected_columns = set(columns or constraints)
    for header, choices in constraints.items():
        if header not in selected_columns:
            continue
        value = _choice_cell_value(row_data.get(header, ""))
        if value == "":
            continue
        canonical_value = _canonical_choice_value(value, choices)
        if canonical_value is None:
            allowed = ", ".join(choices)
            raise DatasetValidationError(f"Column '{header}' must be blank or one of: {allowed}.")
        row_data[header] = canonical_value


def validate_choice_row_values(
    headers: list[str],
    column_schema: dict | None,
    row_data: dict,
    *,
    columns: list[str] | set[str] | None = None,
    choice_constraints: dict[str, list[str]] | None = None,
) -> None:
    """Backward-compatible alias for choice validation with canonicalization."""
    validate_and_canonicalize_choice_row_values(
        headers,
        column_schema,
        row_data,
        columns=columns,
        choice_constraints=choice_constraints,
    )


def invalid_choice_values_by_column(
    headers: list[str],
    column_schema: dict | None,
    rows: list[dict] | Any,
) -> dict[str, set[str]]:
    choice_columns = choice_constraints_from_schema(headers, column_schema)
    if not choice_columns:
        return {}

    invalid_values: dict[str, set[str]] = {header: set() for header in choice_columns}
    for row_data in rows:
        for header, choices in choice_columns.items():
            value = _choice_cell_value((row_data or {}).get(header, ""))
            if value and _canonical_choice_value(value, choices) is None:
                invalid_values[header].add(value)

    return {header: values for header, values in invalid_values.items() if values}


def normalize_dataset_row_filters(
    headers: list[str],
    filters: dict | None,
    *,
    strict: bool = False,
) -> dict[str, str]:
    normalized_filters = {}
    header_set = set(headers)
    for raw_header, raw_value in (filters or {}).items():
        header = str(raw_header or "").strip()
        if not header:
            if strict:
                raise DatasetRowQueryError("Row filter headers must be non-empty.")
            continue
        if header not in header_set:
            if strict:
                raise DatasetRowQueryError(f"Column '{header}' is not in this dataset.")
            continue
        value = "" if raw_value is None else str(raw_value).strip()
        if value:
            normalized_filters[header] = value
    return normalized_filters


def default_dataset_row_filter_operator(column_type: str) -> str:
    if column_type in {DatasetColumnType.BOOLEAN, DatasetColumnType.CHOICE}:
        return ROW_FILTER_IS
    return ROW_FILTER_CONTAINS


def dataset_row_filter_operators(column_type: str) -> tuple[str, ...]:
    if column_type in {DatasetColumnType.BOOLEAN, DatasetColumnType.CHOICE}:
        return (ROW_FILTER_IS,)
    if column_type in ROW_ORDERED_FILTER_TYPES:
        return (ROW_FILTER_CONTAINS, ROW_FILTER_ABOVE, ROW_FILTER_BELOW)
    return (ROW_FILTER_CONTAINS,)


def normalize_dataset_row_filter_operator(
    column_type: str,
    operator: str | None,
    *,
    strict: bool = False,
) -> str:
    normalized_operator = str(operator or "").strip().lower()
    normalized_operator = ROW_FILTER_OPERATOR_ALIASES.get(normalized_operator, normalized_operator)
    default_operator = default_dataset_row_filter_operator(column_type)
    if not normalized_operator:
        return default_operator
    if normalized_operator in dataset_row_filter_operators(column_type):
        return normalized_operator
    if strict:
        allowed = ", ".join(dataset_row_filter_operators(column_type))
        raise DatasetRowQueryError(
            f"Unsupported row filter operator '{operator}'. Use one of: {allowed}."
        )
    return default_operator


def normalize_dataset_row_filter_operators(
    headers: list[str],
    column_schema: dict | None,
    filters: dict[str, str],
    filter_operators: dict | None,
    *,
    strict: bool = False,
) -> dict[str, str]:
    column_map = {column["name"]: column for column in column_definitions(headers, column_schema)}
    normalized_operators = {}
    for header in filters:
        column = column_map[header]
        normalized_operators[header] = normalize_dataset_row_filter_operator(
            str(column["type"]),
            (filter_operators or {}).get(header),
            strict=strict,
        )
    return normalized_operators


def normalize_dataset_row_sort(
    headers: list[str],
    sort: str | None,
    *,
    strict: bool = False,
) -> str:
    selected_sort = str(sort or ROW_DEFAULT_SORT).strip()
    if not selected_sort or selected_sort == ROW_DEFAULT_SORT:
        return ROW_DEFAULT_SORT
    if selected_sort in headers:
        return selected_sort
    if selected_sort.startswith("col_"):
        try:
            column_index = int(selected_sort.removeprefix("col_"))
        except ValueError:
            column_index = -1
        if 0 <= column_index < len(headers):
            return selected_sort
    if strict:
        raise DatasetRowQueryError("Row sort must be 'row_number' or one of the dataset headers.")
    return ROW_DEFAULT_SORT


def normalize_dataset_row_sort_direction(direction: str | None, *, strict: bool = False) -> str:
    normalized_direction = str(direction or "asc").strip().lower()
    if normalized_direction in {"", "asc"}:
        return "asc"
    if normalized_direction == ROW_SORT_DESC:
        return ROW_SORT_DESC
    if strict:
        raise DatasetRowQueryError("Row sort direction must be 'asc' or 'desc'.")
    return "asc"


def _dataset_row_sort_header(headers: list[str], selected_sort: str) -> str | None:
    if selected_sort == ROW_DEFAULT_SORT:
        return None
    if selected_sort in headers:
        return selected_sort
    if selected_sort.startswith("col_"):
        column_index = int(selected_sort.removeprefix("col_"))
        return headers[column_index]
    return None


def _normalized_numeric_text_expression(alias: str):
    empty_text = Value("", output_field=TextField())
    expression = Trim(Cast(alias, TextField()))
    for symbol in CURRENCY_SYMBOLS:
        expression = Replace(
            expression,
            Value(symbol, output_field=TextField()),
            empty_text,
            output_field=TextField(),
        )
    return Replace(
        expression,
        Value(",", output_field=TextField()),
        empty_text,
        output_field=TextField(),
    )


def _normalize_numeric_filter_value(value: str) -> float | None:
    normalized = str(value or "").strip()
    for symbol in CURRENCY_SYMBOLS:
        normalized = normalized.replace(symbol, "")
    normalized = normalized.replace(",", "").strip()
    if not re.fullmatch(ROW_NUMERIC_FILTER_PATTERN, normalized):
        return None
    return float(normalized)


def _normalize_datetime_filter_value(value: str) -> datetime | None:
    parsed = _parse_datetime(str(value or "").strip())
    if parsed is None:
        return None
    if settings.USE_TZ and timezone.is_naive(parsed):
        return timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def _slash_ymd_datetime_text_expression(alias: str):
    return Replace(
        Cast(alias, TextField()),
        Value("/", output_field=TextField()),
        Value("-", output_field=TextField()),
        output_field=TextField(),
    )


def _split_part_expression(expression, delimiter: str, field: int):
    return Func(
        expression,
        Value(delimiter, output_field=TextField()),
        Value(field),
        function="split_part",
        output_field=TextField(),
    )


def _slash_mdy_datetime_text_expression(alias: str):
    text_expression = Cast(alias, TextField())
    year_and_time = _split_part_expression(text_expression, "/", 3)
    separator = Value("-", output_field=TextField())
    return Concat(
        _split_part_expression(year_and_time, " ", 1),
        separator,
        _split_part_expression(text_expression, "/", 1),
        separator,
        _split_part_expression(text_expression, "/", 2),
        Substr(year_and_time, 5),
        output_field=TextField(),
    )


def _datetime_expression(alias: str):
    return Case(
        When(
            **{
                f"{alias}__regex": ROW_DATETIME_SORT_PATTERN,
                "then": Cast(alias, DateTimeField()),
            }
        ),
        When(
            **{
                f"{alias}__regex": ROW_SLASH_YMD_DATETIME_SORT_PATTERN,
                "then": Cast(_slash_ymd_datetime_text_expression(alias), DateTimeField()),
            }
        ),
        When(
            **{
                f"{alias}__regex": ROW_SLASH_MDY_DATETIME_SORT_PATTERN,
                "then": Cast(_slash_mdy_datetime_text_expression(alias), DateTimeField()),
            }
        ),
        default=Value(None),
        output_field=DateTimeField(),
    )


def _or_header_value_search(queryset, headers: list[str], search_query: str):
    if not headers:
        return queryset.none()

    search_filter = Q()
    for index, header in enumerate(headers[:ROW_SEARCH_COLUMN_LIMIT]):
        alias = f"rowset_search_{index}"
        queryset = queryset.annotate(**{alias: KeyTextTransform(header, "data")})
        search_filter |= Q(**{f"{alias}__icontains": search_query})
    if not search_filter:
        return queryset
    return queryset.filter(search_filter)


def _boolean_filter_query(alias: str, value: str) -> Q | None:
    normalized = value.lower()
    if normalized in ROW_BOOLEAN_TRUE_VALUES:
        values = ROW_BOOLEAN_TRUE_VALUES
    elif normalized in ROW_BOOLEAN_FALSE_VALUES:
        values = ROW_BOOLEAN_FALSE_VALUES
    else:
        return None

    query = Q()
    for candidate in values:
        query |= Q(**{f"{alias}__iexact": candidate})
    return query


def _apply_row_field_filters(
    queryset,
    headers: list[str],
    column_schema: dict | None,
    filters: dict[str, str],
    filter_operators: dict[str, str],
):
    column_map = {column["name"]: column for column in column_definitions(headers, column_schema)}
    for index, header in enumerate(headers):
        value = filters.get(header, "")
        if not value:
            continue

        alias = f"rowset_filter_{index}"
        queryset = queryset.annotate(**{alias: KeyTextTransform(header, "data")})
        column = column_map[header]
        if column["type"] == DatasetColumnType.BOOLEAN:
            boolean_query = _boolean_filter_query(alias, value)
            if boolean_query is None:
                return queryset.none()
            queryset = queryset.filter(boolean_query)
        elif column["type"] == DatasetColumnType.CHOICE:
            queryset = queryset.filter(**{f"{alias}__iexact": value})
        elif column["type"] in ROW_NUMERIC_SORT_TYPES and filter_operators.get(header) in {
            ROW_FILTER_ABOVE,
            ROW_FILTER_BELOW,
        }:
            filter_value = _normalize_numeric_filter_value(value)
            if filter_value is None:
                return queryset.none()
            numeric_text_alias = f"{alias}_numeric_text"
            number_alias = f"{alias}_number"
            queryset = queryset.annotate(
                **{
                    numeric_text_alias: _normalized_numeric_text_expression(alias),
                    number_alias: Case(
                        When(
                            **{
                                f"{numeric_text_alias}__regex": ROW_NUMERIC_SORT_PATTERN,
                                "then": Cast(numeric_text_alias, FloatField()),
                            }
                        ),
                        default=Value(None),
                        output_field=FloatField(),
                    ),
                }
            )
            lookup = "gt" if filter_operators[header] == ROW_FILTER_ABOVE else "lt"
            queryset = queryset.filter(**{f"{number_alias}__{lookup}": filter_value})
        elif column["type"] in ROW_DATETIME_SORT_TYPES and filter_operators.get(header) in {
            ROW_FILTER_ABOVE,
            ROW_FILTER_BELOW,
        }:
            filter_value = _normalize_datetime_filter_value(value)
            if filter_value is None:
                return queryset.none()
            datetime_alias = f"{alias}_datetime"
            queryset = queryset.annotate(**{datetime_alias: _datetime_expression(alias)})
            lookup = "gt" if filter_operators[header] == ROW_FILTER_ABOVE else "lt"
            queryset = queryset.filter(**{f"{datetime_alias}__{lookup}": filter_value})
        else:
            queryset = queryset.filter(**{f"{alias}__icontains": value})
    return queryset


def apply_dataset_row_query(
    queryset,
    dataset,
    *,
    query: str | None = None,
    filters: dict | None = None,
    filter_operators: dict | None = None,
    sort: str | None = None,
    direction: str | None = None,
    strict: bool = False,
):
    search_query = str(query or "").strip()
    normalized_filters = normalize_dataset_row_filters(
        dataset.headers,
        filters,
        strict=strict,
    )
    normalized_filter_operators = normalize_dataset_row_filter_operators(
        dataset.headers,
        dataset.column_schema,
        normalized_filters,
        filter_operators,
        strict=strict,
    )
    selected_sort = normalize_dataset_row_sort(dataset.headers, sort, strict=strict)
    sort_direction = normalize_dataset_row_sort_direction(direction, strict=strict)

    if search_query:
        queryset = _or_header_value_search(queryset, dataset.headers, search_query)
    queryset = _apply_row_field_filters(
        queryset,
        dataset.headers,
        dataset.column_schema,
        normalized_filters,
        normalized_filter_operators,
    )
    queryset = apply_dataset_row_sort(queryset, dataset, selected_sort, sort_direction)

    return queryset, {
        "query": search_query,
        "filters": normalized_filters,
        "filter_operators": normalized_filter_operators,
        "sort": selected_sort,
        "direction": sort_direction,
        "has_filters": bool(
            search_query
            or normalized_filters
            or selected_sort != ROW_DEFAULT_SORT
            or sort_direction == ROW_SORT_DESC
        ),
    }


def _dataset_rows_query_contexts(
    datasets,
    *,
    filters: dict | None,
    filter_operators: dict | None,
    strict: bool,
    skip_invalid_filter_operators: bool,
) -> list[_DatasetRowsQueryContext]:
    contexts = []
    for dataset in datasets:
        normalized_filters = normalize_dataset_row_filters(
            dataset.headers,
            filters,
            strict=strict,
        )
        try:
            normalized_filter_operators = normalize_dataset_row_filter_operators(
                dataset.headers,
                dataset.column_schema,
                normalized_filters,
                filter_operators,
                strict=strict,
            )
        except DatasetRowQueryError:
            if skip_invalid_filter_operators:
                continue
            raise
        contexts.append(
            _DatasetRowsQueryContext(
                dataset_id=dataset.id,
                headers=dataset.headers,
                column_map={
                    column["name"]: column
                    for column in column_definitions(dataset.headers, dataset.column_schema)
                },
                filters=normalized_filters,
                filter_operators=normalized_filter_operators,
            )
        )
    return contexts


def _apply_dataset_rows_search(queryset, contexts: list[_DatasetRowsQueryContext], query: str):
    search_query = str(query or "").strip()
    if not search_query:
        return queryset

    annotations = {}
    search_filter = Q()
    alias_by_header: dict[str, str] = {}
    for context in contexts:
        for header in context.headers[:ROW_SEARCH_COLUMN_LIMIT]:
            alias = alias_by_header.get(header)
            if alias is None:
                alias = f"rowset_multi_search_{len(alias_by_header)}"
                alias_by_header[header] = alias
                annotations[alias] = KeyTextTransform(header, "data")
            search_filter |= Q(dataset_id=context.dataset_id) & Q(
                **{f"{alias}__icontains": search_query}
            )

    if not search_filter:
        return queryset.none()
    return queryset.annotate(**annotations).filter(search_filter)


def _dataset_rows_filter_condition(
    context: _DatasetRowsQueryContext,
    *,
    header: str,
    alias: str,
    number_alias: str,
    datetime_alias: str,
) -> Q | None:
    value = context.filters.get(header, "")
    if not value:
        return None

    column = context.column_map[header]
    column_type = column["type"]
    operator = context.filter_operators.get(header)
    dataset_scope = Q(dataset_id=context.dataset_id)
    if column_type == DatasetColumnType.BOOLEAN:
        boolean_query = _boolean_filter_query(alias, value)
        if boolean_query is None:
            return None
        return dataset_scope & boolean_query
    if column_type == DatasetColumnType.CHOICE:
        return dataset_scope & Q(**{f"{alias}__iexact": value})
    if column_type in ROW_NUMERIC_SORT_TYPES and operator in {ROW_FILTER_ABOVE, ROW_FILTER_BELOW}:
        filter_value = _normalize_numeric_filter_value(value)
        if filter_value is None:
            return None
        lookup = "gt" if operator == ROW_FILTER_ABOVE else "lt"
        return dataset_scope & Q(**{f"{number_alias}__{lookup}": filter_value})
    if column_type in ROW_DATETIME_SORT_TYPES and operator in {ROW_FILTER_ABOVE, ROW_FILTER_BELOW}:
        filter_value = _normalize_datetime_filter_value(value)
        if filter_value is None:
            return None
        lookup = "gt" if operator == ROW_FILTER_ABOVE else "lt"
        return dataset_scope & Q(**{f"{datetime_alias}__{lookup}": filter_value})
    return dataset_scope & Q(**{f"{alias}__icontains": value})


def _apply_dataset_rows_field_filters(queryset, contexts: list[_DatasetRowsQueryContext]):
    filter_headers: list[str] = []
    for context in contexts:
        for header in context.filters:
            if header not in filter_headers:
                filter_headers.append(header)

    for index, header in enumerate(filter_headers):
        alias = f"rowset_multi_filter_{index}"
        number_alias = f"{alias}_number"
        datetime_alias = f"{alias}_datetime"
        queryset = queryset.annotate(**{alias: KeyTextTransform(header, "data")})

        uses_numeric_filter = any(
            context.column_map[header]["type"] in ROW_NUMERIC_SORT_TYPES
            and context.filter_operators.get(header) in {ROW_FILTER_ABOVE, ROW_FILTER_BELOW}
            for context in contexts
            if header in context.filters
        )
        uses_datetime_filter = any(
            context.column_map[header]["type"] in ROW_DATETIME_SORT_TYPES
            and context.filter_operators.get(header) in {ROW_FILTER_ABOVE, ROW_FILTER_BELOW}
            for context in contexts
            if header in context.filters
        )
        if uses_numeric_filter:
            numeric_text_alias = f"{alias}_numeric_text"
            queryset = queryset.annotate(
                **{
                    numeric_text_alias: _normalized_numeric_text_expression(alias),
                    number_alias: Case(
                        When(
                            **{
                                f"{numeric_text_alias}__regex": ROW_NUMERIC_SORT_PATTERN,
                                "then": Cast(numeric_text_alias, FloatField()),
                            }
                        ),
                        default=Value(None),
                        output_field=FloatField(),
                    ),
                }
            )
        if uses_datetime_filter:
            queryset = queryset.annotate(**{datetime_alias: _datetime_expression(alias)})

        filter_query = Q()
        for context in contexts:
            condition = _dataset_rows_filter_condition(
                context,
                header=header,
                alias=alias,
                number_alias=number_alias,
                datetime_alias=datetime_alias,
            )
            if condition is not None:
                filter_query |= condition
        if not filter_query:
            return queryset.none()
        queryset = queryset.filter(filter_query)
    return queryset


def apply_dataset_rows_query(
    queryset,
    datasets,
    *,
    query: str | None = None,
    filters: dict | None = None,
    filter_operators: dict | None = None,
    strict: bool = False,
    skip_invalid_filter_operators: bool = False,
):
    dataset_list = list(datasets)
    if not dataset_list:
        return queryset.none()

    contexts = _dataset_rows_query_contexts(
        dataset_list,
        filters=filters,
        filter_operators=filter_operators,
        strict=strict,
        skip_invalid_filter_operators=skip_invalid_filter_operators,
    )
    if not contexts:
        return queryset.none()
    queryset = queryset.filter(dataset_id__in=[context.dataset_id for context in contexts])
    queryset = _apply_dataset_rows_search(queryset, contexts, str(query or "").strip())
    queryset = _apply_dataset_rows_field_filters(queryset, contexts)
    return queryset.order_by("dataset_id", "row_number", "id")


def apply_dataset_row_sort(queryset, dataset, selected_sort: str, sort_direction: str):
    sort_header = _dataset_row_sort_header(dataset.headers, selected_sort)
    if sort_header is None:
        ordering = "-row_number" if sort_direction == ROW_SORT_DESC else "row_number"
        return queryset.order_by(ordering)

    sort_column = next(
        column
        for column in column_definitions(dataset.headers, dataset.column_schema)
        if column["name"] == sort_header
    )
    queryset = queryset.annotate(rowset_sort_text=KeyTextTransform(sort_header, "data"))
    if sort_column["type"] in ROW_NUMERIC_SORT_TYPES:
        queryset = queryset.annotate(
            rowset_sort_numeric_text=_normalized_numeric_text_expression("rowset_sort_text"),
            rowset_sort_number=Case(
                When(
                    rowset_sort_numeric_text__regex=ROW_NUMERIC_SORT_PATTERN,
                    then=Cast("rowset_sort_numeric_text", FloatField()),
                ),
                default=Value(None),
                output_field=FloatField(),
            ),
        )
        sort_expression = F("rowset_sort_number")
    elif sort_column["type"] in ROW_DATETIME_SORT_TYPES:
        queryset = queryset.annotate(rowset_sort_datetime=_datetime_expression("rowset_sort_text"))
        sort_expression = F("rowset_sort_datetime")
    else:
        sort_expression = Lower("rowset_sort_text")
    if sort_direction == ROW_SORT_DESC:
        return queryset.order_by(sort_expression.desc(nulls_last=True), "row_number")
    return queryset.order_by(sort_expression.asc(nulls_last=True), "row_number")


def generated_index_column_schema() -> dict[str, str]:
    return {COLUMN_SCHEMA_TYPE_KEY: DatasetColumnType.INTEGER}


def _validate_headers(headers: list[str] | None, file_kind: str = "CSV") -> list[str]:
    if not headers:
        raise DatasetValidationError(f"Could not find any {file_kind.lower()} headers.")

    cleaned = [(header or "").strip() for header in headers]
    if any(not header for header in cleaned):
        raise DatasetValidationError(f"Every {file_kind.lower()} column needs a non-empty header.")

    duplicates = sorted({header for header in cleaned if cleaned.count(header) > 1})
    if duplicates:
        joined = ", ".join(duplicates)
        raise DatasetValidationError(
            f"{file_kind} headers must be unique. Duplicate headers: {joined}."
        )

    return cleaned


def validate_headers(headers: list[str] | None, file_kind: str = "CSV") -> list[str]:
    return _validate_headers(headers, file_kind=file_kind)


def generated_index_column_name(headers: list[str]) -> str:
    if GENERATED_INDEX_BASENAME not in headers:
        return GENERATED_INDEX_BASENAME

    suffix = 2
    while f"{GENERATED_INDEX_BASENAME}_{suffix}" in headers:
        suffix += 1
    return f"{GENERATED_INDEX_BASENAME}_{suffix}"


def rows_to_csv_text(headers: list[str], rows) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=headers, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(_export_row(headers, row))
    return buffer.getvalue()


def rows_to_parquet_bytes(headers: list[str], rows) -> bytes:
    dataframe = pl.DataFrame(
        [_export_row(headers, row) for row in rows],
        schema={header: pl.String for header in headers},
    )
    buffer = io.BytesIO()
    dataframe.write_parquet(buffer)
    return buffer.getvalue()


def rows_to_jsonl_text(headers: list[str], rows) -> str:
    return "".join(f"{json.dumps(_export_row(headers, row), ensure_ascii=False)}\n" for row in rows)


def rows_to_xlsx_bytes(headers: list[str], rows) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as workbook:
        workbook.writestr("[Content_Types].xml", _xlsx_content_types_xml())
        workbook.writestr("_rels/.rels", _xlsx_package_relationships_xml())
        workbook.writestr("xl/workbook.xml", _xlsx_workbook_xml())
        workbook.writestr("xl/_rels/workbook.xml.rels", _xlsx_workbook_relationships_xml())
        workbook.writestr("xl/worksheets/sheet1.xml", _xlsx_sheet_xml(headers, rows))
    return buffer.getvalue()


def rows_to_sqlite_bytes(headers: list[str], rows) -> bytes:
    connection = sqlite3.connect(":memory:")
    try:
        if not headers:
            connection.execute('CREATE TABLE rows ("_rowset_empty_export" TEXT)')
            connection.commit()
            return connection.serialize()

        quoted_columns = ", ".join(f"{_quote_sqlite_identifier(header)} TEXT" for header in headers)
        connection.execute(f"CREATE TABLE rows ({quoted_columns})")
        column_names = ", ".join(_quote_sqlite_identifier(header) for header in headers)
        placeholders = ", ".join("?" for _ in headers)
        connection.executemany(
            f"INSERT INTO rows ({column_names}) VALUES ({placeholders})",
            (_export_row_tuple(headers, row) for row in rows),
        )
        connection.commit()
        return connection.serialize()
    finally:
        connection.close()


def iter_export_row_data(dataset):
    return (
        dataset.rows.order_by("row_number").values_list("data", flat=True).iterator(chunk_size=1000)
    )


def _row_data(row) -> dict:
    if isinstance(row, dict):
        return row
    return row.data


def _export_row(headers: list[str], row) -> dict[str, str]:
    row_data = _row_data(row)
    return {header: _export_value(row_data.get(header, "")) for header in headers}


def _export_row_tuple(headers: list[str], row) -> tuple[str, ...]:
    row_data = _row_data(row)
    return tuple(_export_value(row_data.get(header, "")) for header in headers)


def _export_value(value) -> str:
    if value is None:
        return ""
    return str(value)


def _quote_sqlite_identifier(identifier: str) -> str:
    return f'"{identifier.replace(chr(34), chr(34) + chr(34))}"'


def _xlsx_content_types_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
        '  <Default Extension="rels" '
        'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>\n'
        '  <Default Extension="xml" ContentType="application/xml"/>\n'
        '  <Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.'
        'sheet.main+xml"/>\n'
        '  <Override PartName="/xl/worksheets/sheet1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.'
        'worksheet+xml"/>\n'
        "</Types>\n"
    )


def _xlsx_package_relationships_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
        'relationships">\n'
        '  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
        'officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/>\n'
        "</Relationships>\n"
    )


def _xlsx_workbook_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/'
        'relationships">\n'
        "  <sheets>\n"
        '    <sheet name="Rows" sheetId="1" r:id="rId1"/>\n'
        "  </sheets>\n"
        "</workbook>\n"
    )


def _xlsx_workbook_relationships_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
        'relationships">\n'
        '  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
        'officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/>\n'
        "</Relationships>\n"
    )


def _xlsx_sheet_xml(headers: list[str], rows) -> str:
    row_xml = [_xlsx_row_xml(1, headers)]
    for index, row in enumerate(rows, start=2):
        row_xml.append(_xlsx_row_xml(index, _export_row(headers, row).values()))
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    {"".join(row_xml)}
  </sheetData>
</worksheet>
"""


def _xlsx_row_xml(row_number: int, values) -> str:
    cells = [
        _xlsx_cell_xml(row_number=row_number, column_number=column_number, value=value)
        for column_number, value in enumerate(values, start=1)
    ]
    return f'<row r="{row_number}">{"".join(cells)}</row>'


def _xlsx_cell_xml(*, row_number: int, column_number: int, value) -> str:
    cell_ref = f"{_xlsx_column_name(column_number)}{row_number}"
    text = _strip_invalid_xml_chars(_export_value(value))
    preserve = ' xml:space="preserve"' if _xlsx_needs_preserved_space(text) else ""
    return f'<c r="{cell_ref}" t="inlineStr"><is><t{preserve}>{escape(text)}</t></is></c>'


def _xlsx_column_name(column_number: int) -> str:
    name = ""
    while column_number:
        column_number, remainder = divmod(column_number - 1, 26)
        name = f"{chr(65 + remainder)}{name}"
    return name


def _xlsx_needs_preserved_space(value: str) -> bool:
    return bool(value) and (value != value.strip() or "\n" in value or "\t" in value)


def _strip_invalid_xml_chars(value: str) -> str:
    return "".join(char for char in value if char in {"\t", "\n", "\r"} or ord(char) >= 0x20)


def normalize_public_page_size(value) -> int:
    try:
        page_size = int(value)
    except TypeError:
        page_size = DEFAULT_PUBLIC_PAGE_SIZE
    except ValueError:
        page_size = DEFAULT_PUBLIC_PAGE_SIZE

    if page_size < 1:
        return DEFAULT_PUBLIC_PAGE_SIZE
    return min(page_size, MAX_PUBLIC_PAGE_SIZE)
