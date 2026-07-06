from typing import Any

from django.urls import reverse

from apps.api.services import DatasetServiceError
from apps.dataset_plugins.models import DatasetPluginActivation
from apps.datasets.models import DatasetAsset

FLASHCARD_PLUGIN_MAX_CARDS = 500


def _field_value(row_data: dict[str, Any], column: str) -> str:
    value = row_data.get(column, "")
    return "" if value is None else str(value)


def _asset_lookup(activation: DatasetPluginActivation) -> dict[tuple[int, str], DatasetAsset]:
    dataset = activation.dataset
    columns = activation.config.get("columns", {})
    image_columns = [
        column
        for role, column in columns.items()
        if role.endswith("_image") and isinstance(column, str) and column
    ]
    if not image_columns:
        return {}
    assets = DatasetAsset.objects.filter(
        dataset=dataset,
        row_id__in=dataset.rows.values("id"),
        column_name__in=image_columns,
    )
    return {(asset.row_id, asset.column_name): asset for asset in assets}


def _image_field(
    activation: DatasetPluginActivation,
    row,
    role: str,
    column: str,
    assets: dict[tuple[int, str], DatasetAsset],
) -> dict[str, Any] | None:
    asset = assets.get((row.id, column))
    if asset is None:
        return None
    thumbnail_path = reverse(
        "dataset_asset_content",
        kwargs={"dataset_key": activation.dataset.key, "asset_key": asset.key},
    )
    full_path = reverse(
        "dataset_asset_content",
        kwargs={"dataset_key": activation.dataset.key, "asset_key": asset.key},
    )
    return {
        "role": role,
        "label": column,
        "url": f"{thumbnail_path}?variant=thumbnail",
        "full_url": full_path,
        "alt": asset.original_filename or column,
    }


def _text_field(row_data: dict[str, Any], role: str, column: str) -> dict[str, Any] | None:
    value = _field_value(row_data, column)
    if not value:
        return None
    return {
        "role": role,
        "label": column,
        "value": value,
    }


def flashcard_plugin_context(activation: DatasetPluginActivation) -> dict[str, Any]:
    dataset = activation.dataset
    columns = activation.config.get("columns", {})
    assets = _asset_lookup(activation)
    cards = []
    rows = dataset.rows.order_by("row_number", "id")[:FLASHCARD_PLUGIN_MAX_CARDS]
    for row in rows:
        front_fields = []
        back_fields = []
        front_images = []
        back_images = []

        for role in ("front_title", "front_question", "tags"):
            column = columns.get(role, "")
            field = _text_field(row.data, role, column) if column else None
            if field:
                front_fields.append(field)
        for role in ("back_title", "back_answer"):
            column = columns.get(role, "")
            field = _text_field(row.data, role, column) if column else None
            if field:
                back_fields.append(field)
        for role, target in (("front_image", front_images), ("back_image", back_images)):
            column = columns.get(role, "")
            image = _image_field(activation, row, role, column, assets) if column else None
            if image:
                target.append(image)

        cards.append(
            {
                "row": row,
                "front_fields": front_fields,
                "back_fields": back_fields,
                "front_images": front_images,
                "back_images": back_images,
                "row_url": row.get_absolute_url(),
            }
        )

    return {
        "dataset": dataset,
        "activation": activation,
        "plugin": {
            "slug": "flashcards",
            "name": "Flashcards",
        },
        "flashcards": cards,
        "flashcard_limit": FLASHCARD_PLUGIN_MAX_CARDS,
        "flashcards_truncated": dataset.row_count > len(cards),
    }


def dataset_plugin_view_context(activation: DatasetPluginActivation) -> dict[str, Any]:
    if activation.plugin_slug == "flashcards":
        return flashcard_plugin_context(activation)
    raise DatasetServiceError(404, "Dataset plugin view not found.")
