import pytest
from django.urls import reverse

from apps.datasets import views
from apps.datasets.choices import DatasetColumnType
from apps.datasets.services import column_definitions, normalize_column_schema
from apps.datasets.tests.factories import create_dataset


def _create_tags_dataset(profile, **overrides):
    return create_dataset(
        profile,
        headers=["item", "topics"],
        index_column="item",
        column_schema={
            "item": {"type": DatasetColumnType.TEXT},
            "topics": {"type": DatasetColumnType.TAGS},
        },
        **overrides,
    )


def test_tags_column_type_normalizes_as_first_class_schema_metadata():
    schema = normalize_column_schema(["topics"], {"topics": "tags"})

    assert schema == {"topics": {"type": "tags"}}
    assert column_definitions(["topics"], schema) == [
        {
            "name": "topics",
            "type": "tags",
            "type_label": "Tags",
            "description": "",
        }
    ]


def test_tag_items_trim_segments_ignore_blanks_and_preserve_duplicates():
    items = views._tag_items(" Django, HTMX, , django ,  ", colorized=False)

    assert items == [
        {"value": "Django", "accent_class": ""},
        {"value": "HTMX", "accent_class": ""},
        {"value": "django", "accent_class": ""},
    ]


def test_tag_items_use_deterministic_accents_only_when_colorized():
    first = views._tag_items("Django, HTMX", colorized=True)
    second = views._tag_items(" django ,HTMX", colorized=True)

    assert all(item["accent_class"].startswith("fb-choice-pill-") for item in first)
    assert first[0]["accent_class"] == second[0]["accent_class"]
    assert first[1]["accent_class"] == second[1]["accent_class"]


@pytest.mark.django_db
def test_authenticated_dataset_and_row_detail_render_tags_using_profile_color_setting(
    auth_client,
    profile,
):
    original_value = " Django, HTMX, , django ,  "
    dataset = _create_tags_dataset(
        profile,
        rows=[{"item": "DOC-1", "topics": original_value}],
    )
    row = dataset.rows.get()

    neutral_response = auth_client.get(dataset.get_absolute_url())
    neutral_cell = neutral_response.context["rows_with_values"][0]["cells"][1]

    assert neutral_cell["is_tags"] is True
    assert [tag["value"] for tag in neutral_cell["tags"]] == ["Django", "HTMX", "django"]
    assert all(tag["accent_class"] == "" for tag in neutral_cell["tags"])
    assert neutral_response.content.decode().count("fb-choice-pill") == 3

    row_response = auth_client.get(reverse("dataset_row_detail", args=[dataset.key, row.id]))
    topics_cell = row_response.context["row_cells"][1]

    assert topics_cell["form_value"] == original_value
    assert [tag["value"] for tag in topics_cell["tags"]] == ["Django", "HTMX", "django"]
    assert all(tag["accent_class"] == "" for tag in topics_cell["tags"])

    profile.choice_colorization_enabled = True
    profile.save(update_fields=["choice_colorization_enabled"])
    colorized_response = auth_client.get(dataset.get_absolute_url())
    colorized_row_response = auth_client.get(
        reverse("dataset_row_detail", args=[dataset.key, row.id])
    )
    colorized_tags = colorized_response.context["rows_with_values"][0]["cells"][1]["tags"]
    colorized_row_tags = colorized_row_response.context["row_cells"][1]["tags"]

    assert all(tag["accent_class"].startswith("fb-choice-pill-") for tag in colorized_tags)
    assert all(tag["accent_class"].startswith("fb-choice-pill-") for tag in colorized_row_tags)
    assert colorized_tags[0]["accent_class"] == colorized_tags[2]["accent_class"]


@pytest.mark.django_db
def test_authenticated_preview_rows_render_tags_using_profile_color_setting(
    auth_client,
    profile,
):
    dataset = _create_tags_dataset(
        profile,
        preview_rows=[{"item": "DOC-1", "topics": "Django, HTMX"}],
    )

    neutral_response = auth_client.get(dataset.get_absolute_url())
    neutral_tags = neutral_response.context["rows_with_values"][0]["cells"][1]["tags"]

    assert [tag["value"] for tag in neutral_tags] == ["Django", "HTMX"]
    assert all(tag["accent_class"] == "" for tag in neutral_tags)

    profile.choice_colorization_enabled = True
    profile.save(update_fields=["choice_colorization_enabled"])
    colorized_response = auth_client.get(dataset.get_absolute_url())
    colorized_tags = colorized_response.context["rows_with_values"][0]["cells"][1]["tags"]

    assert all(tag["accent_class"].startswith("fb-choice-pill-") for tag in colorized_tags)


@pytest.mark.django_db
def test_separator_only_tags_render_as_blank_without_pills(auth_client, profile):
    dataset = _create_tags_dataset(
        profile,
        rows=[{"item": "DOC-1", "topics": " , , "}],
    )

    response = auth_client.get(dataset.get_absolute_url())
    topics_cell = response.context["rows_with_values"][0]["cells"][1]
    content = response.content.decode()

    assert topics_cell["tags"] == []
    assert topics_cell.get("is_tags") is None
    assert topics_cell["value"] == ""
    assert "fb-choice-pill" not in content
    assert ">Blank<" in content


@pytest.mark.django_db
def test_rest_api_preserves_tags_schema_and_original_comma_separated_value(client, profile):
    original_value = " Django, HTMX, , django ,  "
    create_response = client.post(
        f"/api/datasets?api_key={profile.key}",
        data={
            "name": "Tagged docs",
            "headers": ["item", "topics"],
            "index_column": "item",
            "column_types": {"item": "text", "topics": "tags"},
            "rows": [{"item": "DOC-1", "topics": original_value}],
        },
        content_type="application/json",
    )

    assert create_response.status_code == 201
    dataset_payload = create_response.json()["dataset"]
    assert dataset_payload["column_schema"]["topics"] == {"type": "tags"}

    rows_response = client.get(
        f"/api/datasets/{dataset_payload['key']}/rows?api_key={profile.key}"
    )

    assert rows_response.status_code == 200
    assert rows_response.json()["rows"][0]["data"]["topics"] == original_value


@pytest.mark.django_db
def test_public_dataset_and_row_detail_render_tags_as_neutral_pills(client, profile):
    dataset = _create_tags_dataset(
        profile,
        rows=[{"item": "DOC-1", "topics": " Django, HTMX, ,  "}],
        public_enabled=True,
    )
    row = dataset.rows.get()
    profile.choice_colorization_enabled = True
    profile.save(update_fields=["choice_colorization_enabled"])

    table_response = client.get(dataset.get_public_url())
    detail_response = client.get(
        reverse("public_dataset_row_detail", args=[dataset.public_key, row.id])
    )

    table_tags = table_response.context["public_rows_with_values"][0]["cells"][1]["tags"]
    detail_tags = detail_response.context["row_cells"][1]["tags"]
    assert all(tag["accent_class"] == "" for tag in [*table_tags, *detail_tags])

    for response in (table_response, detail_response):
        content = response.content.decode()
        assert response.status_code == 200
        assert content.count("fb-choice-pill") == 2
        assert ">Django<" in content
        assert ">HTMX<" in content
