import base64
import io
import sqlite3
import wave
import xml.etree.ElementTree as ET
import zipfile

from django.utils import timezone
from PIL import Image

from apps.datasets.choices import DatasetColumnType
from apps.datasets.models import Dataset, DatasetRow


def main_content_html(response) -> str:
    content = response.content.decode()
    return content.split('<main id="main-content"', maxsplit=1)[1].split("</main>", maxsplit=1)[0]


def image_base64() -> str:
    return base64.b64encode(image_bytes()).decode()


def image_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (3, 2), (12, 34, 56)).save(buffer, format="PNG")
    return buffer.getvalue()


def audio_base64() -> str:
    return base64.b64encode(audio_bytes()).decode()


def audio_bytes() -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b"\x00\x00" * 8)
    return buffer.getvalue()


def palette_image_bytes() -> bytes:
    buffer = io.BytesIO()
    image = Image.new("P", (3, 2), 0)
    image.putpalette([12, 34, 56, 240, 244, 248] + [0, 0, 0] * 254)
    image.putdata([0, 1, 0, 1, 0, 1])
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def xlsx_cell_texts(content: bytes) -> list[str]:
    root = ET.fromstring(xlsx_sheet_xml(content))
    namespace = {"xlsx": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    return [element.text or "" for element in root.findall(".//xlsx:t", namespace)]


def xlsx_sheet_xml(content: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(content)) as workbook:
        return workbook.read("xl/worksheets/sheet1.xml").decode()


def sqlite_rows(content: bytes) -> list[dict[str, str]]:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    try:
        connection.deserialize(content)
        return [dict(row) for row in connection.execute("SELECT * FROM rows")]
    finally:
        connection.close()


def sqlite_table_columns(content: bytes, table_name: str = "rows") -> list[str]:
    connection = sqlite3.connect(":memory:")
    try:
        connection.deserialize(content)
        return [row[1] for row in connection.execute(f"PRAGMA table_info({table_name})")]
    finally:
        connection.close()


def create_ready_dataset(profile):
    dataset = Dataset.objects.create(
        profile=profile,
        name="People",
        headers=["name", "email"],
        index_column="email",
        preview_rows=[{"name": "Ada", "email": "ada@example.com"}],
        row_count=2,
    )
    DatasetRow.objects.create(
        dataset=dataset,
        row_number=1,
        index_value="ada@example.com",
        data={"name": "Ada", "email": "ada@example.com"},
    )
    DatasetRow.objects.create(
        dataset=dataset,
        row_number=2,
        index_value="grace@example.com",
        data={"name": "Grace", "email": "grace@example.com"},
    )
    return dataset


def complete_agent_setup(profile):
    profile.setup_completed_at = timezone.now()
    profile.save(update_fields=["setup_completed_at"])


def create_choice_status_dataset(profile):
    dataset = Dataset.objects.create(
        profile=profile,
        name="Tasks",
        headers=["task_id", "status"],
        column_schema={
            "task_id": {"type": DatasetColumnType.TEXT},
            "status": {
                "type": DatasetColumnType.CHOICE,
                "choices": ["todo", "doing", "blocked", "done"],
            },
        },
        index_column="task_id",
        preview_rows=[{"task_id": "TASK-1", "status": "todo"}],
        row_count=3,
    )
    DatasetRow.objects.bulk_create(
        [
            DatasetRow(
                dataset=dataset,
                row_number=1,
                index_value="TASK-1",
                data={"task_id": "TASK-1", "status": "todo"},
            ),
            DatasetRow(
                dataset=dataset,
                row_number=2,
                index_value="TASK-2",
                data={"task_id": "TASK-2", "status": "done"},
            ),
            DatasetRow(
                dataset=dataset,
                row_number=3,
                index_value="TASK-3",
                data={"task_id": "TASK-3", "status": "paused"},
            ),
        ]
    )
    return dataset


def create_crm_datasets(profile):
    people = Dataset.objects.create(
        profile=profile,
        name="People",
        headers=["person_id", "name", "email"],
        index_column="person_id",
        row_count=1,
    )
    DatasetRow.objects.create(
        dataset=people,
        row_number=1,
        index_value="P-1",
        data={
            "person_id": "P-1",
            "name": "Ada Lovelace",
            "email": "ada@example.com",
        },
    )
    messages = Dataset.objects.create(
        profile=profile,
        name="CRM Messages",
        headers=["message_id", "person_id", "body"],
        index_column="message_id",
        row_count=1,
    )
    DatasetRow.objects.create(
        dataset=messages,
        row_number=1,
        index_value="M-1",
        data={
            "message_id": "M-1",
            "person_id": "P-1",
            "body": "Intro call completed.",
        },
    )
    return people, messages


def configure_filterable_dataset(dataset):
    dataset.headers = ["name", "email", "score", "active"]
    dataset.column_schema = {
        "name": {"type": DatasetColumnType.TEXT},
        "email": {"type": DatasetColumnType.EMAIL},
        "score": {"type": DatasetColumnType.NUMBER},
        "active": {"type": DatasetColumnType.BOOLEAN},
    }
    dataset.row_count = 3
    dataset.rows.all().delete()
    dataset.save(update_fields=["headers", "column_schema", "row_count"])
    DatasetRow.objects.bulk_create(
        [
            DatasetRow(
                dataset=dataset,
                row_number=1,
                index_value="ada@example.com",
                data={
                    "name": "Ada Lovelace",
                    "email": "ada@example.com",
                    "score": "10.0",
                    "active": "true",
                },
            ),
            DatasetRow(
                dataset=dataset,
                row_number=2,
                index_value="grace@example.com",
                data={
                    "name": "Grace Hopper",
                    "email": "grace@example.com",
                    "score": "8",
                    "active": "false",
                },
            ),
            DatasetRow(
                dataset=dataset,
                row_number=3,
                index_value="katherine@example.com",
                data={
                    "name": "Katherine Johnson",
                    "email": "katherine@example.com",
                    "score": "010",
                    "active": "true",
                },
            ),
        ]
    )
    return dataset


def configure_datetime_dataset(dataset):
    dataset.headers = ["event_id", "event_name", "event_at"]
    dataset.column_schema = {
        "event_id": {"type": DatasetColumnType.TEXT},
        "event_name": {"type": DatasetColumnType.TEXT},
        "event_at": {"type": DatasetColumnType.DATETIME},
    }
    dataset.index_column = "event_id"
    dataset.row_count = 3
    dataset.rows.all().delete()
    dataset.save(update_fields=["headers", "column_schema", "index_column", "row_count"])
    DatasetRow.objects.bulk_create(
        [
            DatasetRow(
                dataset=dataset,
                row_number=1,
                index_value="E-1",
                data={
                    "event_id": "E-1",
                    "event_name": "UTC later",
                    "event_at": "2026-05-14T09:00:00Z",
                },
            ),
            DatasetRow(
                dataset=dataset,
                row_number=2,
                index_value="E-2",
                data={
                    "event_id": "E-2",
                    "event_name": "Offset early",
                    "event_at": "2026-05-14T10:00:00+02:00",
                },
            ),
            DatasetRow(
                dataset=dataset,
                row_number=3,
                index_value="E-3",
                data={
                    "event_id": "E-3",
                    "event_name": "Next day",
                    "event_at": "2026-05-15T08:00:00Z",
                },
            ),
        ]
    )
    return dataset


TYPED_ROW_HEADERS = [
    "row_id",
    "status",
    "active",
    "due_on",
    "scheduled_at",
    "count",
    "score",
    "budget",
    "contact",
    "website",
    "related_dataset",
    "notes",
    "photo",
]


def typed_row_data(**overrides):
    data = {
        "row_id": "ROW-1",
        "status": "Backlog",
        "active": "true",
        "due_on": "2026-07-01",
        "scheduled_at": "2026-07-01T09:30",
        "count": "2",
        "score": "9.5",
        "budget": "120.00",
        "contact": "ada@example.com",
        "website": "https://example.com",
        "related_dataset": "",
        "notes": "Initial row",
        "photo": "",
    }
    data.update(overrides)
    return data


def typed_row_post_data(**overrides):
    data = typed_row_data(**overrides)
    data.pop("photo")
    return data


def create_typed_row_dataset(profile):
    row_data = typed_row_data()
    dataset = Dataset.objects.create(
        profile=profile,
        name="Typed rows",
        headers=TYPED_ROW_HEADERS,
        index_column="row_id",
        row_count=1,
        column_schema={
            "row_id": {"type": DatasetColumnType.TEXT},
            "status": {
                "type": DatasetColumnType.CHOICE,
                "choices": ["Backlog", "Doing", "Done"],
            },
            "active": {"type": DatasetColumnType.BOOLEAN},
            "due_on": {"type": DatasetColumnType.DATE},
            "scheduled_at": {"type": DatasetColumnType.DATETIME},
            "count": {"type": DatasetColumnType.INTEGER},
            "score": {"type": DatasetColumnType.NUMBER},
            "budget": {"type": DatasetColumnType.CURRENCY},
            "contact": {"type": DatasetColumnType.EMAIL},
            "website": {"type": DatasetColumnType.URL},
            "related_dataset": {"type": DatasetColumnType.REFERENCE},
            "notes": {"type": DatasetColumnType.TEXT},
            "photo": {"type": DatasetColumnType.IMAGE},
        },
    )
    DatasetRow.objects.create(
        dataset=dataset,
        row_number=1,
        index_value="ROW-1",
        data=row_data,
    )
    return dataset


def add_invalid_datetime_row(dataset):
    DatasetRow.objects.bulk_create(
        [
            DatasetRow(
                dataset=dataset,
                row_number=4,
                index_value="E-4",
                data={
                    "event_id": "E-4",
                    "event_name": "Invalid date",
                    "event_at": "2026-13-01",
                },
            ),
            DatasetRow(
                dataset=dataset,
                row_number=5,
                index_value="E-5",
                data={
                    "event_id": "E-5",
                    "event_name": "Invalid time",
                    "event_at": "2026-05-14T29:00:00Z",
                },
            ),
            DatasetRow(
                dataset=dataset,
                row_number=6,
                index_value="E-6",
                data={
                    "event_id": "E-6",
                    "event_name": "Invalid year",
                    "event_at": "0000-01-01",
                },
            ),
        ]
    )
    dataset.row_count = 6
    dataset.save(update_fields=["row_count"])
    return dataset


def add_supported_datetime_format_rows(dataset):
    DatasetRow.objects.bulk_create(
        [
            DatasetRow(
                dataset=dataset,
                row_number=4,
                index_value="E-4",
                data={
                    "event_id": "E-4",
                    "event_name": "YMD slash",
                    "event_at": "2026/05/13",
                },
            ),
            DatasetRow(
                dataset=dataset,
                row_number=5,
                index_value="E-5",
                data={
                    "event_id": "E-5",
                    "event_name": "MDY slash",
                    "event_at": "05/14/2026 08:45",
                },
            ),
            DatasetRow(
                dataset=dataset,
                row_number=6,
                index_value="E-6",
                data={
                    "event_id": "E-6",
                    "event_name": "Century leap",
                    "event_at": "2000-02-29",
                },
            ),
            DatasetRow(
                dataset=dataset,
                row_number=7,
                index_value="E-7",
                data={
                    "event_id": "E-7",
                    "event_name": "Century slash leap",
                    "event_at": "02/29/2000",
                },
            ),
            DatasetRow(
                dataset=dataset,
                row_number=8,
                index_value="E-8",
                data={
                    "event_id": "E-8",
                    "event_name": "YMD slash datetime",
                    "event_at": "2026/5/13 8:45",
                },
            ),
            DatasetRow(
                dataset=dataset,
                row_number=9,
                index_value="E-9",
                data={
                    "event_id": "E-9",
                    "event_name": "MDY slash date",
                    "event_at": "5/14/2026",
                },
            ),
            DatasetRow(
                dataset=dataset,
                row_number=10,
                index_value="E-10",
                data={
                    "event_id": "E-10",
                    "event_name": "MDY slash compact time",
                    "event_at": "5/14/2026 8:5",
                },
            ),
        ]
    )
    dataset.row_count = dataset.rows.count()
    dataset.save(update_fields=["row_count"])
    return dataset
