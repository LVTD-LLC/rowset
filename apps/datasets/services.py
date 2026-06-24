import csv
import io
import json
import re
import sqlite3
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse
from xml.sax.saxutils import escape

import polars as pl
from django.db.models import Case, F, FloatField, Q, TextField, Value, When
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Cast, Lower, Replace, Trim

from apps.datasets.choices import DatasetColumnType


class CSVParseError(ValueError):
    pass


class DatasetRowQueryError(ValueError):
    pass


GENERATED_INDEX_CHOICE = "__rowset_generated__"
GENERATED_INDEX_BASENAME = "rowset_id"
DEFAULT_PUBLIC_PAGE_SIZE = 10
MAX_PUBLIC_PAGE_SIZE = 100
# Backward compatibility for datasets that already stored normalized sheet text
# before Rowset removed Google Sheets import/sync as an active product path.
LEGACY_GOOGLE_SHEETS_FILE_TYPE = "google_sheets"
COLUMN_TYPE_SAMPLE_LIMIT = 200
COLUMN_SCHEMA_TYPE_KEY = "type"
ROW_DEFAULT_SORT = "row_number"
ROW_SORT_DESC = "desc"
ROW_SEARCH_COLUMN_LIMIT = 20
ROW_BOOLEAN_TRUE_VALUES = ("true", "1", "yes", "y")
ROW_BOOLEAN_FALSE_VALUES = ("false", "0", "no", "n")
ROW_NUMERIC_SORT_TYPES = {
    DatasetColumnType.CURRENCY,
    DatasetColumnType.INTEGER,
    DatasetColumnType.NUMBER,
}
ROW_NUMERIC_SORT_PATTERN = r"^-?\d+(\.\d+)?$"

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
INTEGER_RE = re.compile(r"^[+-]?\d+$")
NUMBER_RE = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)$")
CURRENCY_SYMBOLS = "$€£¥₹"
COLUMN_TYPE_ALIASES = {
    "bool": DatasetColumnType.BOOLEAN,
    "decimal": DatasetColumnType.NUMBER,
    "float": DatasetColumnType.NUMBER,
    "money": DatasetColumnType.CURRENCY,
    "str": DatasetColumnType.TEXT,
    "string": DatasetColumnType.TEXT,
    "timestamp": DatasetColumnType.DATETIME,
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


@dataclass(frozen=True)
class TabularPreview:
    headers: list[str]
    preview_rows: list[dict[str, str]]
    row_count: int
    source_text: str
    file_type: str
    column_schema: dict[str, dict[str, str]] = field(default_factory=dict)

    @property
    def text(self) -> str:
        return self.source_text


@dataclass(frozen=True)
class IndexedRow:
    row_number: int
    index_value: str
    data: dict[str, str]


def ordered_row_values(headers: list[str], row_data: dict[str, object]) -> list[object]:
    return [row_data.get(header, "") for header in headers]


class TabularParser(Protocol):
    file_type: str

    def source_text_from_file(self, uploaded_file) -> str: ...

    def preview_file(self, uploaded_file, sample_size: int = 5) -> TabularPreview: ...

    def iter_text_rows(self, text: str): ...


class CSVParser:
    file_type = "csv"

    def source_text_from_file(self, uploaded_file) -> str:
        uploaded_file.seek(0)
        raw = uploaded_file.read()
        uploaded_file.seek(0)
        return _decode_bytes(raw)

    def preview_file(self, uploaded_file, sample_size: int = 5) -> TabularPreview:
        text = self.source_text_from_file(uploaded_file)
        return self.preview_text(text, sample_size=sample_size)

    def preview_text(self, text: str, sample_size: int = 5) -> TabularPreview:
        reader = _reader_for_text(text)
        headers = _validate_headers(reader.fieldnames)

        preview_rows = []
        column_samples: dict[str, list[str]] = {header: [] for header in headers}
        row_count = 0
        for row in reader:
            row_count += 1
            normalized = {header: (row.get(header) or "") for header in headers}
            _collect_column_samples(column_samples, normalized)
            if len(preview_rows) < sample_size:
                preview_rows.append(normalized)

        return TabularPreview(
            headers=headers,
            preview_rows=preview_rows,
            row_count=row_count,
            source_text=text,
            file_type=self.file_type,
            column_schema=_infer_column_schema_from_samples(headers, column_samples),
        )

    def iter_text_rows(self, text: str):
        reader = _reader_for_text(text)
        headers = _validate_headers(reader.fieldnames)

        for index, row in enumerate(reader, start=1):
            yield index, {header: (row.get(header) or "") for header in headers}


class ParquetParser:
    file_type = "parquet"

    def source_text_from_file(self, uploaded_file) -> str:
        dataframe = _parquet_dataframe(uploaded_file)
        original_headers = dataframe.columns
        headers = _validate_headers(original_headers, file_kind="Parquet")
        dataframe = dataframe.rename(dict(zip(original_headers, headers, strict=True)))
        normalized = dataframe.select([pl.col(header).cast(pl.String) for header in headers])
        normalized = normalized.fill_null("")
        return normalized.write_csv()

    def preview_file(self, uploaded_file, sample_size: int = 5) -> TabularPreview:
        source_text = self.source_text_from_file(uploaded_file)
        preview = CSVParser().preview_text(source_text, sample_size=sample_size)
        return TabularPreview(
            headers=preview.headers,
            preview_rows=preview.preview_rows,
            row_count=preview.row_count,
            source_text=source_text,
            file_type=self.file_type,
            column_schema=preview.column_schema,
        )

    def iter_text_rows(self, text: str):
        yield from CSVParser().iter_text_rows(text)


PARSERS_BY_EXTENSION = {".csv": CSVParser(), ".parquet": ParquetParser()}
PARSERS_BY_TYPE = {parser.file_type: parser for parser in PARSERS_BY_EXTENSION.values()}
PARSERS_BY_TYPE[LEGACY_GOOGLE_SHEETS_FILE_TYPE] = CSVParser()


# Backward-compatible names used by existing views/tests.
CSVPreview = TabularPreview


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
) -> dict[str, dict[str, str]]:
    return {
        header: {COLUMN_SCHEMA_TYPE_KEY: infer_column_type(header, column_samples.get(header, []))}
        for header in headers
    }


def infer_column_schema(
    headers: list[str],
    rows: list[dict[str, str]],
) -> dict[str, dict[str, str]]:
    column_samples: dict[str, list[str]] = {header: [] for header in headers}
    for row in rows:
        _collect_column_samples(column_samples, row)
    return _infer_column_schema_from_samples(headers, column_samples)


def normalize_column_type(column_type: str | None) -> str:
    normalized = str(column_type or "").strip().lower()
    normalized = COLUMN_TYPE_ALIASES.get(normalized, normalized)
    if normalized not in DatasetColumnType.values:
        allowed = ", ".join(DatasetColumnType.values)
        raise CSVParseError(f"Unsupported column type '{column_type}'. Use one of: {allowed}.")
    return normalized


def _column_type_from_schema_entry(entry) -> str | None:
    if isinstance(entry, dict):
        return entry.get(COLUMN_SCHEMA_TYPE_KEY)
    return entry


def normalize_column_schema(
    headers: list[str],
    column_schema: dict | None = None,
    *,
    fallback_schema: dict | None = None,
    reject_unknown: bool = False,
) -> dict[str, dict[str, str]]:
    raw_schema = column_schema or {}
    fallback = fallback_schema or {}
    if reject_unknown:
        unknown_headers = sorted(set(raw_schema) - set(headers))
        if unknown_headers:
            joined = ", ".join(unknown_headers)
            raise CSVParseError(f"Column types include unknown headers: {joined}.")

    normalized_schema = {}
    for header in headers:
        raw_type = None
        if header in raw_schema:
            raw_type = _column_type_from_schema_entry(raw_schema[header])
        elif header in fallback:
            raw_type = _column_type_from_schema_entry(fallback[header])
        if raw_type is None:
            raw_type = DatasetColumnType.TEXT
        normalized_schema[header] = {COLUMN_SCHEMA_TYPE_KEY: normalize_column_type(raw_type)}
    return normalized_schema


def column_definitions(
    headers: list[str],
    column_schema: dict | None,
) -> list[dict[str, str]]:
    normalized_schema = normalize_column_schema(headers, column_schema)
    labels = dict(DatasetColumnType.choices)
    return [
        {
            "name": header,
            "type": normalized_schema[header][COLUMN_SCHEMA_TYPE_KEY],
            "type_label": labels.get(normalized_schema[header][COLUMN_SCHEMA_TYPE_KEY], "Text"),
        }
        for header in headers
    ]


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
        else:
            queryset = queryset.filter(**{f"{alias}__icontains": value})
    return queryset


def apply_dataset_row_query(
    queryset,
    dataset,
    *,
    query: str | None = None,
    filters: dict | None = None,
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
    selected_sort = normalize_dataset_row_sort(dataset.headers, sort, strict=strict)
    sort_direction = normalize_dataset_row_sort_direction(direction, strict=strict)

    if search_query:
        queryset = _or_header_value_search(queryset, dataset.headers, search_query)
    queryset = _apply_row_field_filters(
        queryset,
        dataset.headers,
        dataset.column_schema,
        normalized_filters,
    )
    queryset = apply_dataset_row_sort(queryset, dataset, selected_sort, sort_direction)

    return queryset, {
        "query": search_query,
        "filters": normalized_filters,
        "sort": selected_sort,
        "direction": sort_direction,
        "has_filters": bool(
            search_query
            or normalized_filters
            or selected_sort != ROW_DEFAULT_SORT
            or sort_direction == ROW_SORT_DESC
        ),
    }


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
        empty_text = Value("", output_field=TextField())
        queryset = queryset.annotate(
            rowset_sort_numeric_text=Replace(
                Replace(
                    Trim(Cast("rowset_sort_text", TextField())),
                    Value("$", output_field=TextField()),
                    empty_text,
                    output_field=TextField(),
                ),
                Value(",", output_field=TextField()),
                empty_text,
                output_field=TextField(),
            ),
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
    else:
        sort_expression = Lower("rowset_sort_text")
    if sort_direction == ROW_SORT_DESC:
        return queryset.order_by(sort_expression.desc(nulls_last=True), "row_number")
    return queryset.order_by(sort_expression.asc(nulls_last=True), "row_number")


def generated_index_column_schema() -> dict[str, str]:
    return {COLUMN_SCHEMA_TYPE_KEY: DatasetColumnType.INTEGER}


def _decode_bytes(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise CSVParseError("Could not decode the CSV file. Please upload UTF-8 or latin-1 text.")


def _parquet_dataframe(uploaded_file) -> pl.DataFrame:
    uploaded_file.seek(0)
    raw = uploaded_file.read()
    uploaded_file.seek(0)
    try:
        return pl.read_parquet(io.BytesIO(raw))
    except Exception as exc:
        raise CSVParseError("Could not read the Parquet file.") from exc


def _reader_for_text(text: str):
    if not text.strip():
        raise CSVParseError("The CSV file is empty.")

    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample)
    except csv.Error:
        dialect = csv.excel

    return csv.DictReader(io.StringIO(text), dialect=dialect)


def _validate_headers(headers: list[str] | None, file_kind: str = "CSV") -> list[str]:
    if not headers:
        raise CSVParseError(f"Could not find a header row in the {file_kind} file.")

    cleaned = [(header or "").strip() for header in headers]
    if any(not header for header in cleaned):
        raise CSVParseError(f"Every {file_kind} column needs a non-empty header.")

    duplicates = sorted({header for header in cleaned if cleaned.count(header) > 1})
    if duplicates:
        joined = ", ".join(duplicates)
        raise CSVParseError(f"{file_kind} headers must be unique. Duplicate headers: {joined}.")

    return cleaned


def validate_headers(headers: list[str] | None, file_kind: str = "CSV") -> list[str]:
    return _validate_headers(headers, file_kind=file_kind)


def parser_for_filename(filename: str) -> TabularParser:
    suffix = Path(filename).suffix.lower()
    parser = PARSERS_BY_EXTENSION.get(suffix)
    if not parser:
        raise CSVParseError("Rowset accepts CSV and Parquet files.")
    return parser


def parser_for_file_type(file_type: str) -> TabularParser:
    try:
        return PARSERS_BY_TYPE[file_type]
    except KeyError as exc:
        raise CSVParseError(f"Unsupported file type: {file_type}.") from exc


def preview_uploaded_table(uploaded_file, filename: str, sample_size: int = 5) -> TabularPreview:
    return parser_for_filename(filename).preview_file(uploaded_file, sample_size=sample_size)


def source_text_from_file(file_obj, file_type: str) -> str:
    return parser_for_file_type(file_type).source_text_from_file(file_obj)


def preview_csv_text(text: str, sample_size: int = 5) -> CSVPreview:
    return CSVParser().preview_text(text, sample_size=sample_size)


def preview_csv_file(uploaded_file, sample_size: int = 5) -> CSVPreview:
    return CSVParser().preview_file(uploaded_file, sample_size=sample_size)


def iter_csv_text_rows(text: str):
    yield from CSVParser().iter_text_rows(text)


def iter_csv_rows(file_obj):
    file_obj.seek(0)
    raw = file_obj.read()
    text = _decode_bytes(raw)
    yield from iter_csv_text_rows(text)


def generated_index_column_name(headers: list[str]) -> str:
    if GENERATED_INDEX_BASENAME not in headers:
        return GENERATED_INDEX_BASENAME

    suffix = 2
    while f"{GENERATED_INDEX_BASENAME}_{suffix}" in headers:
        suffix += 1
    return f"{GENERATED_INDEX_BASENAME}_{suffix}"


def iter_indexed_rows(
    *,
    file_type: str,
    source_text: str,
    headers: list[str],
    index_column: str,
    index_generated: bool,
):
    parser = parser_for_file_type(file_type)
    seen = set()

    for row_number, data in parser.iter_text_rows(source_text):
        if index_generated:
            index_value = str(row_number)
            data = {index_column: index_value, **data}
        else:
            index_value = str(data.get(index_column, "")).strip()
            if not index_value:
                raise CSVParseError(f"Index column '{index_column}' cannot contain blank values.")

        if index_value in seen:
            raise CSVParseError(
                f"Index column '{index_column}' must be unique. Duplicate value: {index_value}."
            )
        seen.add(index_value)
        yield IndexedRow(
            row_number=row_number,
            index_value=index_value,
            data={header: str(data.get(header, "")) for header in headers},
        )


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


def prepare_index_config(headers: list[str], selected_index: str) -> tuple[str, bool, list[str]]:
    if selected_index == GENERATED_INDEX_CHOICE:
        index_column = generated_index_column_name(headers)
        return index_column, True, [index_column, *headers]

    if selected_index not in headers:
        raise CSVParseError("Choose a valid index column or let Rowset generate one.")

    return selected_index, False, headers


def dataset_name_from_filename(filename: str) -> str:
    name = Path(filename).stem.replace("_", " ").replace("-", " ").strip()
    return name.title() or "Untitled dataset"


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
