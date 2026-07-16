import csv
import io

import pytest
from django.contrib.auth.hashers import make_password
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.datasets.choices import DatasetColumnType, DatasetMutationType
from apps.datasets.public_previews import (
    PublicPreviewSettingsError,
    build_public_dataset_agent_prompt,
    update_public_preview_settings,
)
from apps.datasets.tests.factories import (
    configure_filterable_dataset,
    create_dataset,
    create_ready_dataset,
)

pytestmark = pytest.mark.django_db

PUBLIC_EXPORT_CONTENT_TYPES = {
    "csv": "text/csv; charset=utf-8",
    "jsonl": "application/x-ndjson; charset=utf-8",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "sqlite": "application/vnd.sqlite3",
    "parquet": "application/vnd.apache.parquet",
}


@override_settings(SITE_URL="https://rowset.example")
def test_public_dataset_agent_prompt_contains_only_public_endpoint_instructions(profile):
    dataset = create_ready_dataset(profile)
    dataset.public_enabled = True
    dataset.save(update_fields=["public_enabled"])

    prompt = build_public_dataset_agent_prompt(dataset)

    assert f"https://rowset.example/api/public/datasets/{dataset.public_key}" in prompt
    assert f"https://rowset.example/api/public/datasets/{dataset.public_key}/rows" in prompt
    assert "limit=500" in prompt
    assert "offset" in prompt
    assert "has_more" in prompt
    assert "No API key or public password is required" in prompt
    assert "SKILL.md" not in prompt
    assert "openapi.json" not in prompt
    assert "/api/capabilities" not in prompt
    assert "/docs/" not in prompt
    assert str(dataset.key) not in prompt


@override_settings(SITE_URL="https://rowset.example")
def test_public_dataset_agent_prompt_requires_protected_password_separately(profile):
    dataset = create_ready_dataset(profile)
    dataset.public_enabled = True
    dataset.public_password_hash = make_password("share-secret")
    dataset.save(update_fields=["public_enabled", "public_password_hash"])

    prompt = build_public_dataset_agent_prompt(dataset)

    assert "Ask the user for the public password separately" in prompt
    assert "X-Rowset-Public-Password" in prompt
    assert "on every request" in prompt
    assert "share-secret" not in prompt
    assert dataset.name not in prompt


@override_settings(SITE_URL="https://rowset.example")
def test_unlocked_public_dataset_page_copies_ai_agent_prompt(client, profile):
    dataset = create_ready_dataset(profile)
    dataset.public_enabled = True
    dataset.save(update_fields=["public_enabled"])

    response = client.get(dataset.get_public_url())
    content = response.content.decode()

    assert response.status_code == 200
    assert "Copy prompt for AI agent" in content
    assert 'x-data="copyPanel"' in content
    assert 'x-ref="source"' in content
    assert f"https://rowset.example/api/public/datasets/{dataset.public_key}/rows" in content


@override_settings(SITE_URL="https://rowset.example")
def test_locked_public_dataset_page_copies_safe_ai_agent_prompt(client, profile):
    dataset = create_ready_dataset(profile)
    dataset.public_enabled = True
    dataset.public_password_hash = make_password("share-secret")
    dataset.save(update_fields=["public_enabled", "public_password_hash"])

    response = client.get(dataset.get_public_url())
    content = response.content.decode()

    assert response.status_code == 200
    assert "Password required" in content
    assert "Copy prompt for AI agent" in content
    assert "X-Rowset-Public-Password" in content
    assert dataset.name not in content
    assert str(dataset.key) not in content
    assert "share-secret" not in content
    assert "ada@example.com" not in content


def test_dataset_public_sharing_is_off_by_default(client, profile):
    dataset = create_ready_dataset(profile)

    response = client.get(dataset.get_public_url())

    assert response.status_code == 404


@pytest.mark.parametrize(("export_format", "content_type"), PUBLIC_EXPORT_CONTENT_TYPES.items())
def test_public_dataset_exports_supported_formats(client, profile, export_format, content_type):
    dataset = create_ready_dataset(profile)
    dataset.public_enabled = True
    dataset.save(update_fields=["public_enabled"])

    response = client.get(f"{dataset.get_public_url()}export/{export_format}/")

    assert response.status_code == 200
    assert response["Content-Type"] == content_type
    assert response["Content-Disposition"].endswith(f'.{export_format}"')
    assert response["X-Robots-Tag"] == "noindex, nofollow, noarchive"


def test_public_dataset_export_contains_all_rows_despite_preview_query(client, profile):
    dataset = create_ready_dataset(profile)
    dataset.public_enabled = True
    dataset.public_page_size = 1
    dataset.save(update_fields=["public_enabled", "public_page_size"])

    response = client.get(
        f"{dataset.get_public_url()}export/csv/",
        {"row_q": "Ada", "page": "1"},
    )

    assert response.status_code == 200
    exported = list(csv.DictReader(io.StringIO(response.content.decode())))
    assert exported == [
        {"name": "Ada", "email": "ada@example.com"},
        {"name": "Grace", "email": "grace@example.com"},
    ]


@pytest.mark.parametrize("dataset_state", ["disabled", "archived"])
def test_public_dataset_export_requires_active_public_preview(client, profile, dataset_state):
    dataset = create_ready_dataset(profile)
    if dataset_state == "archived":
        dataset.public_enabled = True
        dataset.archived_at = timezone.now()
        dataset.save(update_fields=["public_enabled", "archived_at"])

    response = client.get(f"{dataset.get_public_url()}export/csv/")

    assert response.status_code == 404


def test_public_dataset_export_rejects_unsupported_format(client, profile):
    dataset = create_ready_dataset(profile)
    dataset.public_enabled = True
    dataset.save(update_fields=["public_enabled"])

    response = client.get(f"{dataset.get_public_url()}export/xml/")

    assert response.status_code == 404


def test_public_dataset_export_requires_password_unlock(auth_client, client, profile):
    dataset = create_ready_dataset(profile)
    auth_client.post(
        reverse("dataset_update_public_settings", args=[dataset.key]),
        {
            "public_enabled": "on",
            "public_page_size": "10",
            "public_password": "secret-table",
        },
    )
    dataset.refresh_from_db()
    export_url = f"{dataset.get_public_url()}export/csv/"

    locked_response = client.get(export_url)
    assert locked_response.status_code == 404

    unlock_response = client.post(dataset.get_public_url(), {"password": "secret-table"})
    assert unlock_response.status_code == 302

    unlocked_response = client.get(export_url)
    assert unlocked_response.status_code == 200
    assert unlocked_response["Content-Type"] == "text/csv; charset=utf-8"


def test_public_dataset_preview_links_all_export_formats(client, profile):
    dataset = create_ready_dataset(profile)
    dataset.public_enabled = True
    dataset.save(update_fields=["public_enabled"])

    response = client.get(dataset.get_public_url())
    content = response.content.decode()

    assert response.status_code == 200
    assert 'aria-label="Export dataset"' in content
    for export_format in PUBLIC_EXPORT_CONTENT_TYPES:
        export_url = reverse(
            "public_dataset_export",
            args=[dataset.public_key, export_format],
        )
        assert f'href="{export_url}"' in content
    assert str(dataset.key) not in content


def test_locked_public_dataset_preview_hides_export_menu(auth_client, client, profile):
    dataset = create_ready_dataset(profile)
    auth_client.post(
        reverse("dataset_update_public_settings", args=[dataset.key]),
        {
            "public_enabled": "on",
            "public_page_size": "10",
            "public_password": "secret-table",
        },
    )
    dataset.refresh_from_db()

    response = client.get(dataset.get_public_url())

    assert response.status_code == 200
    assert 'aria-label="Export dataset"' not in response.content.decode()


def test_dataset_owner_can_enable_public_sharing(auth_client, profile):
    dataset = create_ready_dataset(profile)

    response = auth_client.post(
        reverse("dataset_update_public_settings", args=[dataset.key]),
        {
            "public_enabled": "on",
            "public_page_size": "1",
        },
    )

    assert response.status_code == 302
    dataset.refresh_from_db()
    assert dataset.public_enabled is True
    assert dataset.public_page_size == 1
    mutation = dataset.mutations.get(mutation_type=DatasetMutationType.PUBLIC_PREVIEW_UPDATED)
    assert mutation.actor_label == "Account"
    assert mutation.metadata["previous_public_enabled"] is False
    assert mutation.metadata["public_enabled"] is True

    duplicate_response = auth_client.post(
        reverse("dataset_update_public_settings", args=[dataset.key]),
        {
            "public_enabled": "on",
            "public_page_size": "1",
        },
    )

    assert duplicate_response.status_code == 302
    assert (
        dataset.mutations.filter(mutation_type=DatasetMutationType.PUBLIC_PREVIEW_UPDATED).count()
        == 1
    )


def test_public_preview_settings_helper_records_mutation_metadata(profile):
    dataset = create_ready_dataset(profile)

    result = update_public_preview_settings(
        dataset,
        public_enabled=True,
        public_page_size=1,
        public_password=" secret-table ",
    )

    dataset.refresh_from_db()
    assert result.settings_changed is True
    assert dataset.public_enabled is True
    assert dataset.public_page_size == 1
    assert dataset.is_public_password_protected is True
    mutation = dataset.mutations.get(mutation_type=DatasetMutationType.PUBLIC_PREVIEW_UPDATED)
    assert mutation.metadata == {
        "previous_public_enabled": False,
        "public_enabled": True,
        "previous_public_page_size": 10,
        "public_page_size": 1,
        "previous_password_protected": False,
        "password_protected": True,
        "password_changed": True,
    }


def test_public_preview_settings_helper_rolls_back_save_when_mutation_recording_fails(
    monkeypatch,
    profile,
):
    dataset = create_ready_dataset(profile)

    def fail_to_record_mutation(*args, **kwargs):
        raise RuntimeError("mutation history unavailable")

    monkeypatch.setattr(
        "apps.datasets.public_previews.record_dataset_mutation",
        fail_to_record_mutation,
    )

    with pytest.raises(RuntimeError, match="mutation history unavailable"):
        update_public_preview_settings(
            dataset,
            public_enabled=True,
            public_page_size=1,
        )

    dataset.refresh_from_db()
    assert dataset.public_enabled is False
    assert dataset.public_page_size == 10
    assert dataset.mutations.count() == 0


def test_public_preview_settings_helper_validates_blank_password_before_mutating(profile):
    dataset = create_ready_dataset(profile)

    with pytest.raises(PublicPreviewSettingsError, match="password cannot be blank"):
        update_public_preview_settings(
            dataset,
            public_enabled=True,
            public_page_size=50,
            public_password="  ",
        )

    assert dataset.public_enabled is False
    assert dataset.public_page_size == 10
    assert dataset.public_password_hash == ""
    assert dataset.mutations.count() == 0


@override_settings(SITE_URL="https://rowset.lvtd.dev")
def test_public_dataset_view_paginates_rows(client, profile):
    dataset = create_ready_dataset(profile)
    dataset.public_enabled = True
    dataset.public_page_size = 1
    dataset.save(update_fields=["public_enabled", "public_page_size"])

    response = client.get(dataset.get_public_url())

    content = response.content.decode()

    assert response.status_code == 200
    assert response.headers["X-Robots-Tag"] == "noindex, nofollow, noarchive"
    assert '<meta name="robots" content="noindex, nofollow, noarchive" />' in content
    assert "Ada" in content
    assert "Grace" not in content
    assert "Page 1 of 2" in content

    page_two = client.get(f"{dataset.get_public_url()}?page=2")
    page_two_content = page_two.content.decode()
    assert "Grace" in page_two_content


def test_public_dataset_markdown_returns_all_rows_and_escapes_table_cells(client, profile):
    dataset = create_dataset(
        profile,
        headers=["name", "notes | status"],
        rows=[
            {"name": "Ada", "notes | status": "First line\nSecond | line"},
            {"name": "Grace", "notes | status": "<ready>"},
        ],
        name="People <notes>",
    )
    dataset.public_enabled = True
    dataset.public_page_size = 1
    dataset.save(update_fields=["public_enabled", "public_page_size"])

    response = client.get(reverse("public_dataset_markdown", args=[dataset.public_key]))

    assert response.status_code == 200
    assert response.headers["Content-Type"] == "text/markdown; charset=utf-8"
    assert response.headers["X-Robots-Tag"] == "noindex, nofollow, noarchive"
    assert response.content.decode() == (
        "# People &lt;notes&gt;\n\n"
        "| name | notes \\| status |\n"
        "| --- | --- |\n"
        "| Ada | First line<br>Second \\| line |\n"
        "| Grace | &lt;ready&gt; |\n"
    )


def test_public_dataset_page_links_to_markdown_version(client, profile):
    dataset = create_ready_dataset(profile)
    dataset.public_enabled = True
    dataset.save(update_fields=["public_enabled"])

    response = client.get(dataset.get_public_url())

    content = response.content.decode()
    markdown_url = reverse("public_dataset_markdown", args=[dataset.public_key])
    assert "View as Markdown" in content
    assert f'href="http://testserver{markdown_url}"' in content
    assert "Copy as Markdown" not in content
    assert f'data-markdown-url="http://testserver{markdown_url}"' not in content
    assert (
        f'<link rel="alternate" type="text/markdown" href="http://testserver{markdown_url}" />'
        in content
    )


def test_public_dataset_markdown_requires_public_preview(client, profile):
    dataset = create_ready_dataset(profile)

    response = client.get(reverse("public_dataset_markdown", args=[dataset.public_key]))

    assert response.status_code == 404


def test_public_dataset_markdown_uses_public_preview_password_session(
    auth_client,
    client,
    profile,
):
    dataset = create_ready_dataset(profile)
    auth_client.post(
        reverse("dataset_update_public_settings", args=[dataset.key]),
        {
            "public_enabled": "on",
            "public_page_size": "10",
            "public_password": "secret-table",
        },
    )
    dataset.refresh_from_db()
    markdown_url = reverse("public_dataset_markdown", args=[dataset.public_key])

    locked_response = client.get(markdown_url)
    assert locked_response.status_code == 403
    assert "Ada" not in locked_response.content.decode()

    client.post(dataset.get_public_url(), {"password": "secret-table"})
    unlocked_response = client.get(markdown_url)
    assert unlocked_response.status_code == 200
    assert "Ada" in unlocked_response.content.decode()


def test_public_dataset_does_not_expose_column_descriptions(client, profile):
    dataset = create_ready_dataset(profile)
    dataset.public_enabled = True
    dataset.column_schema = {
        "name": {
            "type": "text",
            "description": "Internal scoring context for trusted agents only.",
        },
        "email": {"type": "email"},
    }
    dataset.save(update_fields=["public_enabled", "column_schema"])

    response = client.get(dataset.get_public_url())

    assert response.status_code == 200
    content = response.content.decode()
    assert "name" in content
    assert 'x-data="rowColumnMenu"' in content
    assert 'name="row_sort" value="col_0"' in content
    assert "Internal scoring context for trusted agents only." not in content

    row = dataset.rows.first()
    row_detail_response = client.get(
        reverse("public_dataset_row_detail", args=[dataset.public_key, row.id])
    )

    assert row_detail_response.status_code == 200
    row_detail_content = row_detail_response.content.decode()
    assert "name" in row_detail_content
    assert "Internal scoring context for trusted agents only." not in row_detail_content


def test_public_dataset_dashboard_does_not_render_dataset_metadata(client, profile):
    dataset = create_ready_dataset(profile)
    dataset.public_enabled = True
    dataset.description = "A public description for people viewing this dataset."
    dataset.instructions = "Private operating instructions for trusted agents."
    dataset.metadata = {"private_note": "Never expose this arbitrary metadata."}
    dataset.save(update_fields=["public_enabled", "description", "instructions", "metadata"])

    response = client.get(dataset.get_public_url())

    assert response.status_code == 200
    content = response.content.decode()
    assert "Dataset statistics" in content
    assert "A public description for people viewing this dataset." in content
    assert dataset.index_column in content
    assert "Dataset metadata" not in content
    assert "Public identifier" not in content
    assert "Private operating instructions for trusted agents." not in content
    assert "Never expose this arbitrary metadata." not in content


def test_public_dataset_view_filters_and_sorts_rows(client, profile):
    dataset = configure_filterable_dataset(create_ready_dataset(profile))
    dataset.public_enabled = True
    dataset.save(update_fields=["public_enabled"])

    search_response = client.get(dataset.get_public_url(), {"row_q": "grace"})
    search_content = search_response.content.decode()

    assert search_response.status_code == 200
    assert search_response.context["page_obj"].paginator.count == 1
    assert "Grace Hopper" in search_content
    assert "Ada Lovelace" not in search_content
    assert "Katherine Johnson" not in search_content

    sort_response = client.get(
        dataset.get_public_url(),
        {"row_sort": "col_0", "row_dir": "desc"},
    )
    sort_content = sort_response.content.decode()

    assert sort_response.status_code == 200
    assert sort_content.index("Katherine Johnson") < sort_content.index("Grace Hopper")
    assert sort_content.index("Grace Hopper") < sort_content.index("Ada Lovelace")


def test_public_dataset_pagination_preserves_row_filters(client, profile):
    dataset = configure_filterable_dataset(create_ready_dataset(profile))
    dataset.public_enabled = True
    dataset.public_page_size = 1
    dataset.save(update_fields=["public_enabled", "public_page_size"])

    response = client.get(dataset.get_public_url(), {"filter_2": "10"})
    content = response.content.decode()

    assert response.status_code == 200
    assert response.context["page_obj"].paginator.count == 2
    assert "Ada Lovelace" in content
    assert "Katherine Johnson" not in content
    assert 'href="?filter_2=10&amp;page=2"' in content

    page_two = client.get(dataset.get_public_url(), {"filter_2": "10", "page": "2"})
    page_two_content = page_two.content.decode()

    assert page_two.status_code == 200
    assert "Katherine Johnson" in page_two_content
    assert "Grace Hopper" not in page_two_content


def test_public_dataset_links_rows_and_truncates_cells(client, profile):
    dataset = create_ready_dataset(profile)
    dataset.public_enabled = True
    dataset.save(update_fields=["public_enabled"])
    row = dataset.rows.first()
    row.data["email"] = None
    row.save(update_fields=["data"])

    response = client.get(dataset.get_public_url())
    content = response.content.decode()

    assert response.status_code == 200
    assert reverse("public_dataset_row_detail", args=[dataset.public_key, row.id]) in content
    assert 'class="fb-focus block max-w-64 truncate' in content
    assert 'aria-label="View row 1 details"' in content
    assert content.count('aria-label="View row 1 details"') == 1
    assert 'aria-hidden="true" tabindex="-1"' in content
    assert 'title="None"' not in content
    assert 'title=""' in content


def test_public_dataset_renders_url_cells_as_text(client, profile):
    dataset = create_ready_dataset(profile)
    dataset.public_enabled = True
    dataset.headers = ["name", "website", "unsafe"]
    dataset.column_schema = {
        "name": {"type": DatasetColumnType.TEXT},
        "website": {"type": DatasetColumnType.URL},
        "unsafe": {"type": DatasetColumnType.TEXT},
    }
    dataset.save(update_fields=["public_enabled", "headers", "column_schema"])
    row = dataset.rows.first()
    row.data = {
        "name": "Ada",
        "website": "https://example.com/ada",
        "unsafe": "javascript:alert(1)",
    }
    row.save(update_fields=["data"])

    response = client.get(dataset.get_public_url())
    content = response.content.decode()

    assert response.status_code == 200
    assert "https://example.com/ada" in content
    assert 'href="https://example.com/ada"' not in content
    assert 'target="_blank" rel="nofollow ugc noopener noreferrer"' not in content
    assert "javascript:alert(1)" in content
    assert 'href="javascript:alert(1)"' not in content


def test_public_dataset_keeps_row_detail_link_for_single_text_url_column(client, profile):
    dataset = create_ready_dataset(profile)
    dataset.public_enabled = True
    dataset.headers = ["website"]
    dataset.column_schema = {"website": {"type": DatasetColumnType.URL}}
    dataset.save(update_fields=["public_enabled", "headers", "column_schema"])
    row = dataset.rows.first()
    row.data = {"website": "https://example.com/ada"}
    row.save(update_fields=["data"])
    row_url = reverse("public_dataset_row_detail", args=[dataset.public_key, row.id])

    response = client.get(dataset.get_public_url())
    content = response.content.decode()

    assert response.status_code == 200
    assert "https://example.com/ada" in content
    assert 'href="https://example.com/ada"' not in content
    assert f'href="{row_url}"' in content
    assert 'aria-label="View row 1 details"' in content
    assert 'aria-label="Open external link for row 1"' not in content
    assert ">Open</a>" not in content


def test_public_dataset_keeps_row_detail_link_for_single_rowset_url_column(client, profile):
    dataset = create_ready_dataset(profile)
    target_dataset = create_ready_dataset(profile)
    dataset.public_enabled = True
    dataset.headers = ["task_dataset_url"]
    dataset.save(update_fields=["public_enabled", "headers"])
    row = dataset.rows.first()
    public_target_url = f"https://rowset.lvtd.dev/share/datasets/{target_dataset.public_key}/"
    row.data = {"task_dataset_url": public_target_url}
    row.save(update_fields=["data"])
    row_url = reverse("public_dataset_row_detail", args=[dataset.public_key, row.id])

    response = client.get(dataset.get_public_url())
    content = response.content.decode()

    assert response.status_code == 200
    assert f'href="{row_url}"' in content
    assert public_target_url in content
    assert f'href="{public_target_url}"' not in content
    assert 'aria-label="View row 1 details"' in content
    assert content.count('aria-label="View row 1 details"') == 1
    assert 'class="sr-only">View row 1 details' not in content


def test_public_dataset_renders_rowset_urls_as_text_without_private_target_metadata(
    client,
    profile,
):
    source_dataset = create_ready_dataset(profile)
    source_dataset.public_enabled = True
    source_dataset.headers = ["name", "task_dataset_url", "private_path"]
    source_dataset.save(update_fields=["public_enabled", "headers"])
    target_dataset = create_dataset(
        profile,
        name="Private Sprint Tasks",
        headers=["task_id"],
        index_column="task_id",
    )
    row = source_dataset.rows.first()
    public_target_url = f"https://rowset.lvtd.dev/share/datasets/{target_dataset.public_key}/"
    private_target_path = f"/datasets/{target_dataset.key}/"
    row.data = {
        "name": "Review Gate Sprint History",
        "task_dataset_url": public_target_url,
        "private_path": private_target_path,
    }
    row.save(update_fields=["data"])

    response = client.get(source_dataset.get_public_url())
    content = response.content.decode()

    assert response.status_code == 200
    assert public_target_url in content
    assert private_target_path in content
    assert f'href="{public_target_url}"' not in content
    assert f'href="{private_target_path}"' not in content
    assert "Shared dataset" not in content
    assert "Internal dataset" not in content
    assert "Private Sprint Tasks" not in content
    assert reverse("public_dataset_row_detail", args=[source_dataset.public_key, row.id]) in content


def test_public_dataset_row_detail_displays_full_row_data(client, profile):
    dataset = create_ready_dataset(profile)
    dataset.public_enabled = True
    dataset.headers = ["name", "email", "notes"]
    dataset.save(update_fields=["public_enabled", "headers"])
    row = dataset.rows.first()
    full_value = "Line one\n" + "Full untruncated value " * 12
    row.data = {
        "name": "Ada",
        "email": "ada@example.com",
        "notes": full_value,
        "extra_field": "Stored outside declared headers",
    }
    row.save(update_fields=["data"])

    response = client.get(reverse("public_dataset_row_detail", args=[dataset.public_key, row.id]))
    content = response.content.decode()

    assert response.status_code == 200
    assert response.headers["X-Robots-Tag"] == "noindex, nofollow, noarchive"
    assert '<meta name="robots" content="noindex, nofollow, noarchive" />' in content
    assert "Shared Rowset row" in content
    assert "Row 1" in content
    assert "notes" in content
    assert full_value in content
    assert "extra_field" in content
    assert "Stored outside declared headers" in content
    assert "Back to preview" in content
    assert "Created by" not in content


def test_public_dataset_row_detail_links_previous_and_next_rows(client, profile):
    dataset = create_ready_dataset(profile)
    dataset.public_enabled = True
    dataset.save(update_fields=["public_enabled"])
    previous_row = dataset.rows.get(row_number=1)
    current_row = dataset.rows.get(row_number=2)
    next_row = dataset.rows.create(
        row_number=3,
        index_value="katherine@example.com",
        data={"name": "Katherine", "email": "katherine@example.com"},
    )

    response = client.get(
        reverse("public_dataset_row_detail", args=[dataset.public_key, current_row.id])
    )
    content = response.content.decode()

    assert response.status_code == 200
    assert response.context["has_dataset_row_navigation"] is True
    assert response.context["previous_dataset_row"] == previous_row
    assert response.context["next_dataset_row"] == next_row
    previous_url = reverse("public_dataset_row_detail", args=[dataset.public_key, previous_row.id])
    next_url = reverse("public_dataset_row_detail", args=[dataset.public_key, next_row.id])
    assert f'href="{previous_url}"' in content
    assert f'href="{next_url}"' in content
    assert ">Previous Row</a>" in content
    assert ">Next Row</a>" in content


def test_public_dataset_row_detail_disables_missing_row_navigation_edges(client, profile):
    dataset = create_ready_dataset(profile)
    dataset.public_enabled = True
    dataset.save(update_fields=["public_enabled"])
    first_row = dataset.rows.get(row_number=1)
    last_row = dataset.rows.get(row_number=2)
    first_row_url = reverse("public_dataset_row_detail", args=[dataset.public_key, first_row.id])
    last_row_url = reverse("public_dataset_row_detail", args=[dataset.public_key, last_row.id])

    first_response = client.get(first_row_url)
    first_content = first_response.content.decode()

    assert first_response.status_code == 200
    assert first_response.context["has_dataset_row_navigation"] is True
    assert first_response.context["previous_dataset_row"] is None
    assert first_response.context["previous_dataset_row_url"] == ""
    assert first_response.context["next_dataset_row"] == last_row
    assert first_response.context["next_dataset_row_url"] == last_row_url
    assert "Previous Row" in first_content
    assert "Next Row" in first_content
    assert f'href="{last_row_url}"' in first_content

    last_response = client.get(last_row_url)
    last_content = last_response.content.decode()

    assert last_response.status_code == 200
    assert last_response.context["previous_dataset_row"] == first_row
    assert last_response.context["previous_dataset_row_url"] == first_row_url
    assert last_response.context["next_dataset_row"] is None
    assert last_response.context["next_dataset_row_url"] == ""
    assert "Previous Row" in last_content
    assert "Next Row" in last_content
    assert f'href="{first_row_url}"' in last_content


def test_public_dataset_row_detail_renders_url_cells_as_text(client, profile):
    dataset = create_ready_dataset(profile)
    dataset.public_enabled = True
    dataset.headers = ["name", "website", "unsafe"]
    dataset.save(update_fields=["public_enabled", "headers"])
    row = dataset.rows.first()
    row.data = {
        "name": "Ada",
        "website": "https://example.com/ada?ref=rowset&ok=1",
        "unsafe": "https://example.com/<script>",
    }
    row.save(update_fields=["data"])

    response = client.get(reverse("public_dataset_row_detail", args=[dataset.public_key, row.id]))
    content = response.content.decode()

    assert response.status_code == 200
    assert "https://example.com/ada?ref=rowset&amp;ok=1" in content
    assert 'href="https://example.com/ada?ref=rowset&amp;ok=1"' not in content
    assert 'target="_blank" rel="nofollow ugc noopener noreferrer"' not in content
    assert "https://example.com/&lt;script&gt;" in content
    assert 'href="https://example.com/&lt;script&gt;"' not in content


def test_public_dataset_row_detail_requires_public_preview(client, profile):
    dataset = create_ready_dataset(profile)
    row = dataset.rows.first()

    response = client.get(reverse("public_dataset_row_detail", args=[dataset.public_key, row.id]))

    assert response.status_code == 404


def test_public_dataset_orders_cells_by_headers(client, profile):
    dataset = create_dataset(
        profile,
        name="Customers",
        headers=["customer_id", "name", "plan"],
        index_column="customer_id",
        public_enabled=True,
        rows=[
            {
                "name": "Ada Lovelace",
                "plan": "Scale",
                "customer_id": "C-1001",
            }
        ],
    )

    response = client.get(dataset.get_public_url())
    content = response.content.decode()

    assert response.status_code == 200
    customer_id_position = content.index('title="C-1001"')
    name_position = content.index('title="Ada Lovelace"')
    plan_position = content.index('title="Scale"')
    assert customer_id_position < name_position < plan_position


def test_public_dataset_row_detail_password_protection(auth_client, client, profile):
    dataset = create_ready_dataset(profile)
    row = dataset.rows.first()
    auth_client.post(
        reverse("dataset_update_public_settings", args=[dataset.key]),
        {
            "public_enabled": "on",
            "public_page_size": "10",
            "public_password": "secret-table",
        },
    )
    dataset.refresh_from_db()
    row_url = reverse("public_dataset_row_detail", args=[dataset.public_key, row.id])

    locked_response = client.get(row_url)
    locked_content = locked_response.content.decode()
    assert locked_response.status_code == 200
    assert "Password required" in locked_content
    assert "Public preview" in locked_content
    assert dataset.get_public_url() in locked_content
    assert dataset.name not in locked_content
    assert "ada@example.com" not in locked_content

    wrong_response = client.post(row_url, {"password": "wrong"})
    assert "That password did not work" in wrong_response.content.decode()

    unlock_response = client.post(row_url, {"password": "secret-table"})
    assert unlock_response.status_code == 302
    assert unlock_response.url == row_url

    unlocked_response = client.get(row_url)
    assert "Ada" in unlocked_response.content.decode()
    assert "Row data" in unlocked_response.content.decode()


def test_public_dataset_password_protection(auth_client, client, profile):
    dataset = create_ready_dataset(profile)
    auth_client.post(
        reverse("dataset_update_public_settings", args=[dataset.key]),
        {
            "public_enabled": "on",
            "public_page_size": "10",
            "public_password": "secret-table",
        },
    )
    dataset.refresh_from_db()

    locked_response = client.get(dataset.get_public_url())
    assert locked_response.status_code == 200
    assert "Password required" in locked_response.content.decode()
    assert "Ada" not in locked_response.content.decode()

    wrong_response = client.post(dataset.get_public_url(), {"password": "wrong"})
    assert "That password did not work" in wrong_response.content.decode()

    unlock_response = client.post(dataset.get_public_url(), {"password": "secret-table"})
    assert unlock_response.status_code == 302

    unlocked_response = client.get(dataset.get_public_url())
    assert "Ada" in unlocked_response.content.decode()


def test_public_dataset_password_change_revokes_existing_unlock(auth_client, client, profile):
    dataset = create_ready_dataset(profile)
    auth_client.post(
        reverse("dataset_update_public_settings", args=[dataset.key]),
        {
            "public_enabled": "on",
            "public_page_size": "10",
            "public_password": "old-secret",
        },
    )
    dataset.refresh_from_db()

    unlock_response = client.post(dataset.get_public_url(), {"password": "old-secret"})
    assert unlock_response.status_code == 302
    assert "Ada" in client.get(dataset.get_public_url()).content.decode()

    auth_client.post(
        reverse("dataset_update_public_settings", args=[dataset.key]),
        {
            "public_enabled": "on",
            "public_page_size": "10",
            "public_password": "new-secret",
        },
    )

    locked_again = client.get(dataset.get_public_url())
    content = locked_again.content.decode()
    assert "Password required" in content
    assert "Ada" not in content
