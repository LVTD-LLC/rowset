from types import SimpleNamespace

import pytest

from apps.datasets.choices import DatasetStatus
from apps.datasets.google_sheets import GoogleSheetsSyncError, sync_dataset_to_google_sheet
from apps.datasets.models import Dataset, DatasetRow
from apps.datasets.services import GOOGLE_SHEETS_FILE_TYPE, google_sheets_ids

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user(
        username="sheetsuser",
        email="sheetsuser@example.com",
        password="password123",
    )


@pytest.fixture
def profile(user):
    return user.profile


def create_google_sheet_dataset(profile):
    dataset = Dataset.objects.create(
        profile=profile,
        name="People",
        original_filename="people.csv",
        file_type=GOOGLE_SHEETS_FILE_TYPE,
        source_url="https://docs.google.com/spreadsheets/d/sheet123/edit#gid=456",
        source_text="email,name\nada@example.com,Ada\n",
        status=DatasetStatus.READY,
        headers=["email", "name"],
        index_column="email",
        row_count=1,
    )
    DatasetRow.objects.create(
        dataset=dataset,
        row_number=1,
        index_value="ada@example.com",
        data={"email": "ada@example.com", "name": "Ada"},
    )
    return dataset


def test_google_sheets_ids_extracts_spreadsheet_and_gid():
    sheet_id, gid = google_sheets_ids(
        "https://docs.google.com/spreadsheets/d/abc123/edit#gid=456"
    )

    assert sheet_id == "abc123"
    assert gid == "456"


def test_sync_dataset_to_google_sheet_noops_without_credentials(settings, profile, monkeypatch):
    settings.GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON = ""
    dataset = create_google_sheet_dataset(profile)

    def fail_request(*args, **kwargs):
        raise AssertionError("Google Sheets API should not be called without credentials")

    monkeypatch.setattr("apps.datasets.google_sheets._request_json", fail_request)

    sync_dataset_to_google_sheet(dataset)


def test_sync_dataset_to_google_sheet_replaces_tab_values(settings, profile, monkeypatch):
    settings.GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON = '{"client_email":"svc@example.com"}'
    dataset = create_google_sheet_dataset(profile)
    calls = []

    monkeypatch.setattr(
        "apps.datasets.google_sheets._credentials_from_json",
        lambda _json: SimpleNamespace(token="token123"),
    )

    def fake_request(url, *, token, method, payload=None):
        calls.append({"url": url, "token": token, "method": method, "payload": payload})
        if method == "GET":
            return {
                "sheets": [
                    {
                        "properties": {
                            "sheetId": 456,
                            "title": "People Sheet",
                            "gridProperties": {"rowCount": 4, "columnCount": 3},
                        }
                    }
                ]
            }
        return {}

    monkeypatch.setattr("apps.datasets.google_sheets._request_json", fake_request)

    sync_dataset_to_google_sheet(dataset)

    assert calls[0]["method"] == "GET"
    assert calls[1]["method"] == "PUT"
    assert "People%20Sheet" in calls[1]["url"]
    assert calls[1]["payload"] == {
        "values": [
            ["email", "name", ""],
            ["ada@example.com", "Ada", ""],
            ["", "", ""],
            ["", "", ""],
        ]
    }
    assert len(calls) == 2


def test_sync_dataset_to_google_sheet_does_not_clear_before_successful_update(
    settings,
    profile,
    monkeypatch,
):
    settings.GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON = '{"client_email":"svc@example.com"}'
    dataset = create_google_sheet_dataset(profile)
    calls = []

    monkeypatch.setattr(
        "apps.datasets.google_sheets._credentials_from_json",
        lambda _json: SimpleNamespace(token="token123"),
    )

    def fake_request(url, *, token, method, payload=None):
        calls.append(method)
        if method == "GET":
            return {
                "sheets": [
                    {
                        "properties": {
                            "sheetId": 456,
                            "title": "People Sheet",
                            "gridProperties": {"rowCount": 10, "columnCount": 3},
                        }
                    }
                ]
            }
        if method == "PUT":
            raise GoogleSheetsSyncError("Google Sheets write-back failed.")
        return {}

    monkeypatch.setattr("apps.datasets.google_sheets._request_json", fake_request)

    with pytest.raises(GoogleSheetsSyncError):
        sync_dataset_to_google_sheet(dataset)

    assert calls == ["GET", "PUT"]
