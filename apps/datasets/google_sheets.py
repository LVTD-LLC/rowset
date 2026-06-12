import json
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from allauth.socialaccount.models import SocialToken
from django.conf import settings
from django.utils import timezone
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials as GoogleOAuthCredentials

from apps.datasets.models import Dataset
from apps.datasets.services import (
    GOOGLE_SHEETS_FILE_TYPE,
    CSVParseError,
    CSVParser,
    TabularPreview,
    google_sheets_ids,
)

SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
SHEETS_API_BASE = "https://sheets.googleapis.com/v4/spreadsheets"
GOOGLE_SHEETS_TIMEOUT_SECONDS = 15
GOOGLE_SHEETS_CONNECT_SESSION_KEY = "filebridge_google_sheets_connect_requested"
GOOGLE_SHEETS_CONNECTED_EXTRA_DATA_KEY = "filebridge_google_sheets_connected"


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

    credentials = _credentials_for_dataset(dataset)
    if not credentials:
        return "skipped"

    try:
        spreadsheet_id, gid = google_sheets_ids(dataset.source_url)
    except CSVParseError as exc:
        raise GoogleSheetsSyncError(str(exc)) from exc
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


def preview_google_sheet_url_with_oauth(
    url: str,
    *,
    user,
    sample_size: int = 5,
) -> TabularPreview:
    try:
        spreadsheet_id, gid = google_sheets_ids(url)
    except CSVParseError as exc:
        raise GoogleSheetsSyncError(str(exc)) from exc

    credentials = _credentials_for_user(user)
    if not credentials:
        raise GoogleSheetsSyncError("Connect Google to import private Google Sheets.")

    sheet = _sheet_properties_for_gid(spreadsheet_id, gid, credentials.token)
    title = sheet["title"]
    range_name = _quote_sheet_title(title)
    data = _request_json(
        f"{SHEETS_API_BASE}/{spreadsheet_id}/values/{quote(range_name, safe='')}",
        token=credentials.token,
        method="GET",
    )
    text = _values_to_csv_text(data.get("values", []))
    preview = CSVParser().preview_text(text, sample_size=sample_size)
    return TabularPreview(
        headers=preview.headers,
        preview_rows=preview.preview_rows,
        row_count=preview.row_count,
        source_text=preview.source_text,
        file_type=GOOGLE_SHEETS_FILE_TYPE,
        column_schema=preview.column_schema,
    )


def user_has_google_sheets_connection(user) -> bool:
    return SocialToken.objects.filter(
        account__user=user,
        account__provider="google",
        account__extra_data__filebridge_google_sheets_connected=True,
    ).exists()


def _credentials_for_dataset(dataset: Dataset):
    credentials = _credentials_for_user(dataset.profile.user)
    if credentials:
        return credentials

    service_account_json = settings.GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON
    if service_account_json:
        return _credentials_from_json(service_account_json)
    return None


def _credentials_for_user(user):
    token = (
        SocialToken.objects.select_related("account")
        .filter(
            account__user=user,
            account__provider="google",
            account__extra_data__filebridge_google_sheets_connected=True,
        )
        .order_by("-id")
        .first()
    )
    if not token:
        return None

    credentials = GoogleOAuthCredentials(
        token=token.token,
        refresh_token=token.token_secret or None,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        scopes=[SHEETS_SCOPE],
        expiry=_google_credentials_expiry(token.expires_at),
    )
    try:
        if credentials.expired and not credentials.refresh_token:
            return None
        if credentials.expired and credentials.refresh_token:
            credentials.refresh(GoogleAuthRequest())
            token.token = credentials.token
            if credentials.expiry:
                token.expires_at = (
                    credentials.expiry
                    if timezone.is_aware(credentials.expiry)
                    else timezone.make_aware(credentials.expiry)
                )
            token.save(update_fields=["token", "expires_at"])
    except Exception as exc:
        raise GoogleSheetsSyncError("Could not authenticate with Google Sheets.") from exc
    return credentials


def _google_credentials_expiry(expires_at):
    if not expires_at:
        return None
    if timezone.is_aware(expires_at):
        return timezone.make_naive(expires_at, timezone.UTC)
    return expires_at


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


def _values_to_csv_text(values: list[list[str]]) -> str:
    import csv
    import io

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerows(values)
    return output.getvalue()


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
    try:
        return json.loads(raw.decode())
    except json.JSONDecodeError as exc:
        raise GoogleSheetsSyncError("Google Sheets write-back failed.") from exc


def _google_error_message(exc: HTTPError) -> str:
    if exc.code in {401, 403}:
        return (
            "Google Sheets access was denied. Connect Google again or share the sheet with "
            "the configured service account."
        )
    if exc.code == 404:
        return "Google Sheets spreadsheet or tab was not found."
    return "Google Sheets write-back failed."
