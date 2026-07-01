import pytest
from django.urls import reverse

from apps.datasets.choices import DatasetColumnType, DatasetMutationType
from apps.datasets.tests.factories import (
    configure_filterable_dataset,
    create_dataset,
    create_ready_dataset,
)

pytestmark = pytest.mark.django_db


def test_dataset_public_sharing_is_off_by_default(client, profile):
    dataset = create_ready_dataset(profile)

    response = client.get(dataset.get_public_url())

    assert response.status_code == 404


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
    assert "Internal scoring context for trusted agents only." not in content

    row = dataset.rows.first()
    row_detail_response = client.get(
        reverse("public_dataset_row_detail", args=[dataset.public_key, row.id])
    )

    assert row_detail_response.status_code == 200
    row_detail_content = row_detail_response.content.decode()
    assert "name" in row_detail_content
    assert "Internal scoring context for trusted agents only." not in row_detail_content


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


def test_public_dataset_linkifies_external_url_cells_with_safe_rel(client, profile):
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
    assert 'href="https://example.com/ada"' in content
    assert 'target="_blank" rel="nofollow ugc noopener noreferrer"' in content
    assert "javascript:alert(1)" in content
    assert 'href="javascript:alert(1)"' not in content


def test_public_dataset_keeps_row_detail_link_for_single_url_column(client, profile):
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
    assert 'href="https://example.com/ada"' in content
    assert f'href="{row_url}"' in content
    assert 'aria-label="View row 1 details"' in content
    assert 'aria-label="Open external link for row 1"' in content
    assert ">Open</a>" in content


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
    assert f'href="{public_target_url}"' in content
    assert 'aria-label="View row 1 details"' in content
    assert content.count('aria-label="View row 1 details"') == 1
    assert 'class="sr-only">View row 1 details' not in content


def test_public_dataset_renders_rowset_links_without_private_target_metadata(client, profile):
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
    assert f'href="{public_target_url}"' in content
    assert f'href="{private_target_path}"' in content
    assert "Rowset dataset" in content
    assert "Shared dataset" in content
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


def test_public_dataset_row_detail_linkifies_external_url_cells(client, profile):
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
    assert 'href="https://example.com/ada?ref=rowset&amp;ok=1"' in content
    assert 'target="_blank" rel="nofollow ugc noopener noreferrer"' in content
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
        source_text="customer_id,name,plan\nC-1001,Ada Lovelace,Scale\n",
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
    assert "Ada" not in locked_content

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
