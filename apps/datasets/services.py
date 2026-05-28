import csv
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

import polars as pl

from apps.datasets.constants import MAX_CSV_UPLOAD_BYTES


class CSVParseError(ValueError):
    pass


GENERATED_INDEX_CHOICE = "__filebridge_generated__"
GENERATED_INDEX_BASENAME = "filebridge_id"
DEFAULT_PUBLIC_PAGE_SIZE = 10
MAX_PUBLIC_PAGE_SIZE = 100
GOOGLE_SHEETS_FILE_TYPE = "google_sheets"
GOOGLE_SHEETS_EXPORT_TIMEOUT_SECONDS = 15


@dataclass(frozen=True)
class TabularPreview:
    headers: list[str]
    preview_rows: list[dict[str, str]]
    row_count: int
    source_text: str
    file_type: str

    @property
    def text(self) -> str:
        return self.source_text


@dataclass(frozen=True)
class IndexedRow:
    row_number: int
    index_value: str
    data: dict[str, str]


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
        row_count = 0
        for row in reader:
            row_count += 1
            normalized = {header: (row.get(header) or "") for header in headers}
            if len(preview_rows) < sample_size:
                preview_rows.append(normalized)

        return TabularPreview(
            headers=headers,
            preview_rows=preview_rows,
            row_count=row_count,
            source_text=text,
            file_type=self.file_type,
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
        )

    def iter_text_rows(self, text: str):
        yield from CSVParser().iter_text_rows(text)


PARSERS_BY_EXTENSION = {".csv": CSVParser(), ".parquet": ParquetParser()}
PARSERS_BY_TYPE = {parser.file_type: parser for parser in PARSERS_BY_EXTENSION.values()}
PARSERS_BY_TYPE[GOOGLE_SHEETS_FILE_TYPE] = CSVParser()


# Backward-compatible names used by existing views/tests.
CSVPreview = TabularPreview


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
        raise CSVParseError("FileBridge accepts CSV and Parquet files.")
    return parser


def parser_for_file_type(file_type: str) -> TabularParser:
    try:
        return PARSERS_BY_TYPE[file_type]
    except KeyError as exc:
        raise CSVParseError(f"Unsupported file type: {file_type}.") from exc


def preview_uploaded_table(uploaded_file, filename: str, sample_size: int = 5) -> TabularPreview:
    return parser_for_filename(filename).preview_file(uploaded_file, sample_size=sample_size)


def preview_google_sheet_url(url: str, sample_size: int = 5) -> TabularPreview:
    export_url, _sheet_id = google_sheets_export_url(url)
    text = fetch_google_sheet_csv(export_url)
    preview = CSVParser().preview_text(text, sample_size=sample_size)
    return TabularPreview(
        headers=preview.headers,
        preview_rows=preview.preview_rows,
        row_count=preview.row_count,
        source_text=preview.source_text,
        file_type=GOOGLE_SHEETS_FILE_TYPE,
    )


def google_sheets_export_url(url: str) -> tuple[str, str]:
    sheet_id, gid = google_sheets_ids(url)
    return (
        f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}",
        sheet_id,
    )


def google_sheets_ids(url: str) -> tuple[str, str]:
    parsed = urlparse((url or "").strip())
    if parsed.scheme != "https" or parsed.netloc != "docs.google.com":
        raise CSVParseError("Enter a public Google Sheets link from docs.google.com.")

    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 3 or parts[0] != "spreadsheets" or parts[1] != "d":
        raise CSVParseError("Enter a public Google Sheets spreadsheet link.")

    sheet_id = parts[2]
    params = parse_qs(parsed.query)
    fragment_params = parse_qs(parsed.fragment)
    gid = (params.get("gid") or fragment_params.get("gid") or ["0"])[0]
    if not gid.isdigit():
        raise CSVParseError("Google Sheets gid must be numeric.")

    return sheet_id, gid


def fetch_google_sheet_csv(export_url: str) -> str:
    _validate_google_sheets_fetch_url(export_url)
    request = Request(export_url, headers={"User-Agent": "FileBridge/1.0"})
    opener = build_opener(_GoogleSheetsRedirectHandler)
    try:
        with opener.open(request, timeout=GOOGLE_SHEETS_EXPORT_TIMEOUT_SECONDS) as response:
            content_type = response.headers.get("Content-Type", "")
            raw = response.read(MAX_CSV_UPLOAD_BYTES + 1)
    except HTTPError as exc:
        if exc.code in {401, 403, 404}:
            raise CSVParseError(
                "Could not read that Google Sheet. Make sure it is shared publicly or published."
            ) from exc
        raise CSVParseError("Could not download that Google Sheet right now.") from exc
    except (TimeoutError, URLError) as exc:
        raise CSVParseError("Could not download that Google Sheet right now.") from exc

    if len(raw) > MAX_CSV_UPLOAD_BYTES:
        raise CSVParseError("Google Sheets exports must be 10 MB or smaller for now.")

    text = _decode_bytes(raw)
    if "text/html" in content_type.lower() or "<html" in text[:200].lower():
        raise CSVParseError(
            "Google returned a web page instead of CSV. Make sure the sheet is publicly accessible."
        )
    return text


class _GoogleSheetsRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _validate_google_sheets_fetch_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _validate_google_sheets_fetch_url(url: str):
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    is_google_sheets_export = hostname == "docs.google.com"
    is_google_csv_redirect = hostname.endswith("-sheets.googleusercontent.com")
    if parsed.scheme != "https" or not (is_google_sheets_export or is_google_csv_redirect):
        raise CSVParseError("Could not download that Google Sheet right now.")


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
        writer.writerow({header: row.data.get(header, "") for header in headers})
    return buffer.getvalue()


def rows_to_parquet_bytes(headers: list[str], rows) -> bytes:
    dataframe = pl.DataFrame(
        [{header: row.data.get(header, "") for header in headers} for row in rows],
        schema={header: pl.String for header in headers},
    )
    buffer = io.BytesIO()
    dataframe.write_parquet(buffer)
    return buffer.getvalue()


def prepare_index_config(headers: list[str], selected_index: str) -> tuple[str, bool, list[str]]:
    if selected_index == GENERATED_INDEX_CHOICE:
        index_column = generated_index_column_name(headers)
        return index_column, True, [index_column, *headers]

    if selected_index not in headers:
        raise CSVParseError("Choose a valid index column or let FileBridge generate one.")

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
