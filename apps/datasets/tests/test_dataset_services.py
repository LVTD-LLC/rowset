import pytest

from apps.api.services import list_profile_dataset_rows, patch_profile_dataset_row
from apps.datasets.choices import DatasetMutationType
from apps.datasets.services import apply_dataset_row_query
from apps.datasets.tests.dataset_test_helpers import (
    add_invalid_datetime_row,
    add_supported_datetime_format_rows,
    configure_datetime_dataset,
    configure_filterable_dataset,
    create_ready_dataset,
)

pytestmark = pytest.mark.django_db


def test_dataset_row_service_preserves_native_falsy_filter_values(profile):
    dataset = configure_filterable_dataset(create_ready_dataset(profile))

    payload = list_profile_dataset_rows(
        profile,
        str(dataset.key),
        filters={"active": False},
    )

    assert payload["count"] == 1
    assert payload["filters"] == {"active": "False"}
    assert [row["data"]["name"] for row in payload["rows"]] == ["Grace Hopper"]


def test_dataset_row_service_sorts_datetime_columns_chronologically(profile):
    dataset = configure_datetime_dataset(create_ready_dataset(profile))

    payload = list_profile_dataset_rows(
        profile,
        str(dataset.key),
        sort="event_at",
    )

    assert [row["data"]["event_name"] for row in payload["rows"]] == [
        "Offset early",
        "UTC later",
        "Next day",
    ]


def test_dataset_row_service_sorts_invalid_datetime_cells_last(profile):
    dataset = configure_datetime_dataset(create_ready_dataset(profile))
    add_invalid_datetime_row(dataset)

    payload = list_profile_dataset_rows(
        profile,
        str(dataset.key),
        sort="event_at",
    )

    assert [row["data"]["event_name"] for row in payload["rows"]] == [
        "Offset early",
        "UTC later",
        "Next day",
        "Invalid date",
        "Invalid time",
        "Invalid year",
    ]


def test_dataset_row_service_handles_supported_non_iso_datetime_formats(profile):
    dataset = configure_datetime_dataset(create_ready_dataset(profile))
    add_supported_datetime_format_rows(dataset)

    sorted_payload = list_profile_dataset_rows(
        profile,
        str(dataset.key),
        sort="event_at",
    )

    assert [row["data"]["event_name"] for row in sorted_payload["rows"]] == [
        "Century leap",
        "Century slash leap",
        "YMD slash",
        "YMD slash datetime",
        "MDY slash date",
        "Offset early",
        "MDY slash compact time",
        "MDY slash",
        "UTC later",
        "Next day",
    ]

    recent_filtered_queryset, row_query = apply_dataset_row_query(
        dataset.rows.all(),
        dataset,
        filters={"event_at": "2026-05-14T08:30"},
        filter_operators={"event_at": "above"},
        sort="event_at",
        strict=True,
    )

    assert row_query["filter_operators"] == {"event_at": "above"}
    assert [row.data["event_name"] for row in recent_filtered_queryset] == [
        "MDY slash",
        "UTC later",
        "Next day",
    ]

    ymd_slash_filtered_queryset, row_query = apply_dataset_row_query(
        dataset.rows.all(),
        dataset,
        filters={"event_at": "2026/5/13 8:45"},
        filter_operators={"event_at": "above"},
        sort="event_at",
        strict=True,
    )

    assert row_query["filter_operators"] == {"event_at": "above"}
    assert [row.data["event_name"] for row in ymd_slash_filtered_queryset] == [
        "MDY slash date",
        "Offset early",
        "MDY slash compact time",
        "MDY slash",
        "UTC later",
        "Next day",
    ]

    century_filtered_queryset, row_query = apply_dataset_row_query(
        dataset.rows.all(),
        dataset,
        filters={"event_at": "2001-01-01"},
        filter_operators={"event_at": "below"},
        sort="event_at",
        strict=True,
    )

    assert row_query["filter_operators"] == {"event_at": "below"}
    assert [row.data["event_name"] for row in century_filtered_queryset] == [
        "Century leap",
        "Century slash leap",
    ]


def test_row_update_service_null_patch_clears_cell(profile):
    dataset = create_ready_dataset(profile)
    row = dataset.rows.get(row_number=1)

    result = patch_profile_dataset_row(profile, str(dataset.key), row.id, {"name": None})

    assert result["row"]["data"]["name"] == ""
    row.refresh_from_db()
    assert row.data["name"] == ""

    mutation = dataset.mutations.get(mutation_type=DatasetMutationType.ROW_UPDATED)
    assert mutation.metadata == {
        "row_id": row.id,
        "row_number": 1,
        "changed_fields": ["name"],
        "field_changes": [
            {
                "field": "name",
                "before": "Ada",
                "after": "",
            }
        ],
        "value_changes_recorded": True,
        "index_changed": False,
    }
