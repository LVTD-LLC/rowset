import json
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from django.conf import settings
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import service_account

from apps.datasets.models import Dataset
from apps.datasets.services import GOOGLE_SHEETS_FILE_TYPE, CSVParseError, google_sheets_ids

SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
SHEETS_API_BASE = "https://sheets.googleapis.com/v4/spreadsheets"
GOOGLE_SHEETS_TIMEOUT_SECONDS = 15


class GoogleSheetsSyncError(ValueError):
    pass


def sync_dataset_to_google_sheet(dataset: Dataset) -> str:
    """Replace the source Google Sheet tab with the current FileBridge dataset rows.

    CSV import only needs a public sheet URL. Write-back needs a service account JSON in
    GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON, and the spreadsheet must be shared with that service
    account as an editor. When credentials are not configured, this is intentionally a no-op so
    Google Sheets imports keep working as read-only datasets.
    """

    if dataset.file_type != GOOGLE_SHEETS_FILE_TYPE or not dataset.source_url:
        return "skipped"

    service_account_json = settings.GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON
    if not service_account_json:
        return "skipped"

    try:
        spreadsheet_id, gid = google_sheets_ids(dataset.source_url)
    except CSVParseError as exc:
        raise GoogleSheetsSyncError(str(exc)) from exc
    credentials = _credentials_from_json(service_account_json)
    sheet = _sheet_properties_for_gid(spreadsheet_id, gid, credentials.token)
    title = sheet["title"]
    grid_properties = sheet.get("gridProperties", {})
    values = _dataset_values(
        dataset,
        min_rows=grid_properties.get("rowCount", 0),
        min_columns=grid_properties.get("columnCount", 0),
    )
    range_name = _quote_sheet_title(title)

    _request_json(
        f"{SHEETS_API_BASE}/{spreadsheet_id}/values/{quote(range_name + '!A1', safe='')}"
        "?valueInputOption=RAW",
        token=credentials.token,
        method="PUT",
        payload={"values": values},
    )
    return "synced"


def _credentials_from_json(service_account_json: str):
    try:
        info = json.loads(service_account_json)
        credentials = service_account.Credentials.from_service_account_info(
            info,
            scopes=[SHEETS_SCOPE],
        )
        credentials.refresh(GoogleAuthRequest())
    except Exception as exc:
        raise GoogleSheetsSyncError("Could not authenticate with Google Sheets.") from exc
    return credentials


def _sheet_properties_for_gid(spreadsheet_id: str, gid: str, token: str) -> dict:
    metadata = _request_json(
        f"{SHEETS_API_BASE}/{spreadsheet_id}?fields="
        "sheets.properties(sheetId,title,gridProperties(rowCount,columnCount))",
        token=token,
        method="GET",
    )
    for sheet in metadata.get("sheets", []):
        properties = sheet.get("properties", {})
        if str(properties.get("sheetId")) == gid and properties.get("title"):
            return properties
    raise GoogleSheetsSyncError("Could not find the selected Google Sheet tab.")


def _dataset_values(
    dataset: Dataset,
    *,
    min_rows: int = 0,
    min_columns: int = 0,
) -> list[list[str]]:
    width = max(len(dataset.headers), min_columns)
    values = [_pad_row(dataset.headers, width)]
    for row in dataset.rows.order_by("row_number"):
        row_values = [str(row.data.get(header, "")) for header in dataset.headers]
        values.append(_pad_row(row_values, width))
    while len(values) < min_rows:
        values.append(["" for _ in range(width)])
    return values


def _pad_row(row: list[str], width: int) -> list[str]:
    return row + [""] * (width - len(row))


def _quote_sheet_title(title: str) -> str:
    return "'" + title.replace("'", "''") + "'"


def _request_json(url: str, *, token: str, method: str, payload: dict | None = None) -> dict:
    data = None
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"

    request = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=GOOGLE_SHEETS_TIMEOUT_SECONDS) as response:
            raw = response.read()
    except HTTPError as exc:
        message = _google_error_message(exc)
        raise GoogleSheetsSyncError(message) from exc
    except (TimeoutError, URLError) as exc:
        raise GoogleSheetsSyncError("Could not reach Google Sheets.") from exc

    if not raw:
        return {}
    return json.loads(raw.decode())


def _google_error_message(exc: HTTPError) -> str:
    if exc.code in {401, 403}:
        return "Google Sheets write access was denied. Share the sheet with the service account."
    if exc.code == 404:
        return "Google Sheets spreadsheet or tab was not found."
    return "Google Sheets write-back failed."
