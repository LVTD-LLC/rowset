import csv
import io
from dataclasses import dataclass
from pathlib import Path


class CSVParseError(ValueError):
    pass


@dataclass(frozen=True)
class CSVPreview:
    headers: list[str]
    preview_rows: list[dict[str, str]]
    row_count: int
    text: str


def _decode_bytes(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise CSVParseError("Could not decode the CSV file. Please upload UTF-8 or latin-1 text.")


def _reader_for_text(text: str):
    if not text.strip():
        raise CSVParseError("The CSV file is empty.")

    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample)
    except csv.Error:
        dialect = csv.excel

    return csv.DictReader(io.StringIO(text), dialect=dialect)


def _validate_headers(headers: list[str] | None) -> list[str]:
    if not headers:
        raise CSVParseError("Could not find a header row in the CSV file.")

    cleaned = [(header or "").strip() for header in headers]
    if any(not header for header in cleaned):
        raise CSVParseError("Every CSV column needs a non-empty header.")

    duplicates = sorted({header for header in cleaned if cleaned.count(header) > 1})
    if duplicates:
        joined = ", ".join(duplicates)
        raise CSVParseError(f"CSV headers must be unique. Duplicate headers: {joined}.")

    return cleaned


def preview_csv_text(text: str, sample_size: int = 5) -> CSVPreview:
    reader = _reader_for_text(text)
    headers = _validate_headers(reader.fieldnames)

    preview_rows = []
    row_count = 0
    for row in reader:
        row_count += 1
        normalized = {header: (row.get(header) or "") for header in headers}
        if len(preview_rows) < sample_size:
            preview_rows.append(normalized)

    return CSVPreview(
        headers=headers,
        preview_rows=preview_rows,
        row_count=row_count,
        text=text,
    )


def preview_csv_file(uploaded_file, sample_size: int = 5) -> CSVPreview:
    uploaded_file.seek(0)
    raw = uploaded_file.read()
    uploaded_file.seek(0)

    text = _decode_bytes(raw)
    return preview_csv_text(text, sample_size=sample_size)


def iter_csv_text_rows(text: str):
    reader = _reader_for_text(text)
    headers = _validate_headers(reader.fieldnames)

    for index, row in enumerate(reader, start=1):
        yield index, {header: (row.get(header) or "") for header in headers}


def iter_csv_rows(file_obj):
    file_obj.seek(0)
    raw = file_obj.read()
    text = _decode_bytes(raw)
    yield from iter_csv_text_rows(text)


def dataset_name_from_filename(filename: str) -> str:
    name = Path(filename).stem.replace("_", " ").replace("-", " ").strip()
    return name.title() or "Untitled dataset"
