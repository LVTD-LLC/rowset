import base64
import io

import pytest
from PIL import Image

from apps.api.services import (
    add_profile_dataset_column,
    attach_profile_dataset_image_asset,
    patch_profile_dataset_row,
    update_profile_dataset_metadata,
    update_profile_dataset_public_preview,
)
from apps.datasets.choices import DatasetColumnType, DatasetMutationType
from apps.datasets.models import DatasetMutation
from apps.datasets.tests.factories import create_dataset

pytestmark = pytest.mark.django_db


def _image_base64() -> str:
    buffer = io.BytesIO()
    Image.new("RGB", (3, 2), (12, 34, 56)).save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode()


def test_row_patch_records_value_diff_metadata(profile):
    dataset = create_dataset(
        profile,
        headers=["email", "name", "role"],
        index_column="email",
        rows=[
            {
                "email": "ada@example.com",
                "name": "Ada Lovelace",
                "role": "Engineer",
            }
        ],
    )
    row = dataset.rows.get()

    patch_profile_dataset_row(
        profile,
        str(dataset.key),
        row.id,
        {
            "name": "Ada Byron",
            "role": "Engineer",
        },
    )

    mutation = dataset.mutations.get(mutation_type=DatasetMutationType.ROW_UPDATED)
    assert mutation.actor_label == "Account"
    assert mutation.target_type == "row"
    assert mutation.target_identifier == str(row.id)
    assert mutation.metadata == {
        "row_id": row.id,
        "row_number": 1,
        "changed_fields": ["name"],
        "field_changes": [
            {
                "field": "name",
                "before": "Ada Lovelace",
                "after": "Ada Byron",
            }
        ],
        "value_changes_recorded": True,
        "index_changed": False,
    }


def test_schema_add_column_records_column_metadata_without_row_values(profile):
    dataset = create_dataset(
        profile,
        headers=["email", "name"],
        index_column="email",
        rows=[
            {
                "email": "ada@example.com",
                "name": "Ada Lovelace",
            }
        ],
    )

    add_profile_dataset_column(
        profile,
        str(dataset.key),
        name="status",
        default_value="todo",
        column_type=DatasetColumnType.TEXT,
    )

    mutation = dataset.mutations.get(mutation_type=DatasetMutationType.COLUMN_ADDED)
    assert mutation.actor_label == "Account"
    assert mutation.target_type == "column"
    assert mutation.target_identifier == "status"
    assert mutation.metadata == {
        "column": "status",
        "column_type": DatasetColumnType.TEXT,
        "default_value_provided": True,
    }
    serialized_metadata = str(mutation.metadata)
    assert "Ada Lovelace" not in serialized_metadata
    assert "ada@example.com" not in serialized_metadata


def test_public_preview_update_records_previous_and_current_settings(profile):
    dataset = create_dataset(
        profile,
        rows=[
            {
                "email": "ada@example.com",
                "name": "Ada Lovelace",
            }
        ],
    )
    dataset.public_page_size = 50
    dataset.save(update_fields=["public_page_size"])

    update_profile_dataset_public_preview(
        profile,
        str(dataset.key),
        public_enabled=True,
        public_page_size=25,
        public_password="review-only",
    )

    mutation = dataset.mutations.get(mutation_type=DatasetMutationType.PUBLIC_PREVIEW_UPDATED)
    assert mutation.actor_label == "Account"
    assert mutation.target_type == "public_preview"
    assert mutation.target_identifier == ""
    assert mutation.metadata == {
        "previous_public_enabled": False,
        "public_enabled": True,
        "previous_public_page_size": 50,
        "public_page_size": 25,
        "previous_password_protected": False,
        "password_protected": True,
        "password_changed": True,
    }


def test_image_attachment_records_asset_metadata_and_field_diff(profile):
    dataset = create_dataset(
        profile,
        headers=["email", "name", "photo"],
        index_column="email",
        column_schema={
            "email": {"type": DatasetColumnType.EMAIL},
            "name": {"type": DatasetColumnType.TEXT},
            "photo": {"type": DatasetColumnType.IMAGE},
        },
        rows=[
            {
                "email": "ada@example.com",
                "name": "Ada Lovelace",
                "photo": "",
            }
        ],
    )
    row = dataset.rows.get()

    result = attach_profile_dataset_image_asset(
        profile,
        str(dataset.key),
        column_name="photo",
        image_base64=_image_base64(),
        filename="portrait.png",
        content_type="image/png",
        row_id=row.id,
    )

    mutation = dataset.mutations.get(mutation_type=DatasetMutationType.ROW_UPDATED)
    assert mutation.actor_label == "Account"
    assert mutation.target_type == "row"
    assert mutation.target_identifier == str(row.id)
    assert mutation.metadata == {
        "row_id": row.id,
        "row_number": 1,
        "changed_fields": ["photo"],
        "field_changes": [
            {
                "field": "photo",
                "before": "",
                "after": result["asset"]["ref"],
            }
        ],
        "value_changes_recorded": True,
        "asset_key": result["asset"]["key"],
        "asset_ref_recorded": True,
        "filename": "portrait.png",
        "content_type": "image/png",
        "byte_size": result["asset"]["byte_size"],
        "width": 3,
        "height": 2,
    }


def test_noop_dataset_metadata_update_does_not_record_mutation(profile):
    dataset = create_dataset(profile)
    dataset.description = "Initial task board."
    dataset.instructions = "Keep task IDs stable."
    dataset.metadata = {"status_order": ["todo", "done"]}
    dataset.save(update_fields=["description", "instructions", "metadata"])

    update_profile_dataset_metadata(
        profile,
        str(dataset.key),
        description="Initial task board.",
        instructions="Keep task IDs stable.",
        metadata={"status_order": ["todo", "done"]},
    )

    assert not DatasetMutation.objects.filter(
        dataset=dataset,
        mutation_type=DatasetMutationType.DATASET_METADATA_UPDATED,
    ).exists()
