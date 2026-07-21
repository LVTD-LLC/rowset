import json
import re
from datetime import timedelta

import pytest
from django.contrib import messages as message_constants
from django.contrib.messages import get_messages
from django.urls import reverse
from django.utils import timezone

from apps.api.services import create_profile_dataset, create_profile_dataset_row
from apps.core.choices import ProfileStates
from apps.datasets.choices import DatasetColumnType, DatasetMutationType
from apps.datasets.history import record_dataset_mutation
from apps.datasets.models import Dataset, DatasetRow, Project
from apps.datasets.tests.dataset_test_helpers import (
    add_invalid_datetime_row,
    complete_agent_setup,
    configure_datetime_dataset,
    configure_filterable_dataset,
    create_ready_dataset,
    create_typed_row_dataset,
    main_content_html,
    typed_row_post_data,
)
from apps.datasets.views import DATASET_DETAIL_ROW_PAGE_SIZE

pytestmark = pytest.mark.django_db


def test_dataset_list_includes_active_datasets(auth_client, profile):
    create_ready_dataset(profile)
    Dataset.objects.create(
        profile=profile,
        name="Scratch",
        headers=["name"],
        preview_rows=[{"name": "Ada"}],
        row_count=1,
    )

    response = auth_client.get(reverse("home"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "People" in content
    assert "Scratch" in content


def test_dataset_list_supports_search_sort_and_omits_row_actions(auth_client, profile):
    complete_agent_setup(profile)
    project = Project.objects.create(profile=profile, name="Research")
    dataset = create_ready_dataset(profile)
    dataset.project = project
    dataset.public_enabled = True
    dataset.save(update_fields=["project", "public_enabled"])
    Dataset.objects.create(
        profile=profile,
        name="Invoices",
        headers=["invoice_id"],
        row_count=10,
    )

    response = auth_client.get(reverse("home"), {"q": "people", "sort": "rows"})

    content = response.content.decode()
    assert response.status_code == 200
    assert response.context["search_query"] == "people"
    assert response.context["selected_sort"] == "rows"
    assert response.context["dataset_stats"] == {
        "total_datasets": 2,
        "total_rows": 12,
        "public_preview_count": 1,
        "total_projects": 1,
    }
    assert "<title>Dashboard · Rowset</title>" in content
    assert "Search datasets" in content
    assert "People" in content
    assert "Research" in content
    assert [item.name for item in response.context["datasets"]] == ["People"]
    assert "Invoices" in content  # The global workspace tree remains unfiltered.
    assert reverse("archived_dataset_list") in content
    assert reverse("dataset_export", args=[dataset.key, "csv"]) not in content
    assert reverse("dataset_export", args=[dataset.key, "parquet"]) not in content
    assert reverse("dataset_delete", args=[dataset.key]) not in content
    assert "Dataset status" not in content


def test_home_defaults_to_global_recent_order(auth_client, profile):
    alphabetically_first_project = Project.objects.create(profile=profile, name="Alpha project")
    alphabetically_last_project = Project.objects.create(profile=profile, name="Zulu project")
    older_dataset = Dataset.objects.create(
        profile=profile,
        project=alphabetically_first_project,
        name="Alpha",
        headers=["id"],
        index_column="id",
    )
    newer_dataset = Dataset.objects.create(
        profile=profile,
        project=alphabetically_last_project,
        name="Beta",
        headers=["id"],
        index_column="id",
    )
    now = timezone.now()
    Dataset.objects.filter(pk=older_dataset.pk).update(
        created_at=now - timedelta(days=4),
        updated_at=now - timedelta(days=2),
    )
    Dataset.objects.filter(pk=newer_dataset.pk).update(
        created_at=now - timedelta(days=3),
        updated_at=now - timedelta(days=1),
    )

    response = auth_client.get(reverse("home"))

    assert response.status_code == 200
    assert response.context["selected_view_mode"] == "grouped"
    assert response.context["selected_sort"] == "recent"
    assert [dataset.name for dataset in response.context["datasets"]] == ["Beta", "Alpha"]


def test_home_displays_only_ten_recent_datasets(auth_client, profile):
    for index in range(12):
        Dataset.objects.create(
            profile=profile,
            name=f"Dataset {index:02}",
            headers=["id"],
            index_column="id",
        )

    response = auth_client.get(reverse("home"))
    page_two_response = auth_client.get(reverse("home"), {"page": 2})

    assert response.status_code == 200
    assert len(response.context["datasets"]) == 10
    expected_names = [f"Dataset {index:02}" for index in range(11, 1, -1)]
    assert [dataset.name for dataset in response.context["datasets"]] == expected_names
    assert [dataset.name for dataset in page_two_response.context["datasets"]] == expected_names


def test_home_links_to_all_datasets(auth_client, profile):
    complete_agent_setup(profile)
    Dataset.objects.create(
        profile=profile,
        name="People",
        headers=["id"],
        index_column="id",
    )

    response = auth_client.get(reverse("home"))

    assert response.status_code == 200
    assert reverse("dataset_list") in response.content.decode()
    assert "View all datasets" in response.content.decode()


def test_dataset_list_displays_all_active_datasets(auth_client, profile):
    for index in range(12):
        Dataset.objects.create(
            profile=profile,
            name=f"Dataset {index:02}",
            headers=["id"],
            index_column="id",
        )

    response = auth_client.get(reverse("dataset_list"))

    assert response.status_code == 200
    assert len(response.context["datasets"]) == 12


def test_dataset_list_supports_created_sort(auth_client, profile):
    older_created_dataset = Dataset.objects.create(
        profile=profile,
        name="Recently updated",
        headers=["id"],
        index_column="id",
    )
    newer_created_dataset = Dataset.objects.create(
        profile=profile,
        name="Recently created",
        headers=["id"],
        index_column="id",
    )
    now = timezone.now()
    Dataset.objects.filter(pk=older_created_dataset.pk).update(
        created_at=now - timedelta(days=6),
        updated_at=now,
    )
    Dataset.objects.filter(pk=newer_created_dataset.pk).update(
        created_at=now - timedelta(days=1),
        updated_at=now - timedelta(days=5),
    )

    response = auth_client.get(reverse("home"), {"sort": "created"})

    assert response.status_code == 200
    assert response.context["selected_sort"] == "created"
    assert response.context["dataset_table_date_heading"] == "Created"
    assert [dataset.name for dataset in response.context["datasets"]] == [
        "Recently created",
        "Recently updated",
    ]


def test_dataset_list_group_counts_use_filtered_totals_across_pages(auth_client, profile):
    project = Project.objects.create(profile=profile, name="Research")
    for index in range(101):
        Dataset.objects.create(
            profile=profile,
            project=project,
            name=f"Research dataset {index:03}",
            headers=["record_id"],
            index_column="record_id",
            row_count=1,
        )

    page_one = auth_client.get(reverse("dataset_list"), {"sort": "name", "view": "grouped"})
    page_two = auth_client.get(f"{reverse('dataset_list')}?sort=name&view=grouped&page=2")

    assert page_one.status_code == 200
    assert page_two.status_code == 200
    assert len(page_one.context["dataset_groups"][0]["datasets"]) == 100
    assert len(page_two.context["dataset_groups"][0]["datasets"]) == 1
    for response in (page_one, page_two):
        group = response.context["dataset_groups"][0]
        assert group["label"] == "Research"
        assert group["dataset_count"] == 101
        assert group["row_count"] == 101


def test_archived_dataset_list_shows_archived_datasets_only(
    auth_client,
    django_user_model,
    profile,
):
    project = Project.objects.create(profile=profile, name="Research")
    active_project = Project.objects.create(profile=profile, name="Active only")
    active_dataset = create_ready_dataset(profile)
    active_dataset.name = "Archived active people"
    active_dataset.project = active_project
    active_dataset.save(update_fields=["name", "project"])
    archived_dataset = Dataset.objects.create(
        profile=profile,
        project=project,
        name="Archived people",
        headers=["email"],
        index_column="email",
        row_count=4,
        archived_at=timezone.now(),
    )
    archived_draft = Dataset.objects.create(
        profile=profile,
        name="Archived draft",
        headers=["email"],
        index_column="email",
        archived_at=timezone.now(),
    )
    other_user = django_user_model.objects.create_user(
        username="other-archive-list",
        email="other-archive-list@example.com",
        password="password123",
    )
    Dataset.objects.create(
        profile=other_user.profile,
        name="Archived other account dataset",
        headers=["email"],
        index_column="email",
        archived_at=timezone.now(),
    )

    response = auth_client.get(
        reverse("archived_dataset_list"),
        {"q": "archived", "sort": "archived"},
    )

    content = response.content.decode()
    main_content = main_content_html(response)
    assert response.status_code == 200
    assert [dataset.key for dataset in response.context["datasets"]] == [
        archived_draft.key,
        archived_dataset.key,
    ]
    assert response.context["search_query"] == "archived"
    assert response.context["selected_sort"] == "archived"
    assert response.context["dataset_stats"] == {
        "total_datasets": 2,
        "total_rows": 4,
        "public_preview_count": 0,
        "total_projects": 1,
    }
    assert "<title>Archived datasets · Rowset</title>" in content
    assert "Archived datasets" in content
    assert "Archived rows" in content
    assert "Archived projects" in content
    assert "Search archived datasets" in content
    assert "Active datasets" in content
    assert "Archived people" in content
    assert "Research" in content
    assert "Active only" in content  # Active workspace items remain available in the sidebar.
    assert "Archived active people" not in main_content
    assert "Archived draft" in content
    assert "Archived other account dataset" not in content
    assert reverse("home") in content
    assert reverse("dataset_restore", args=[archived_dataset.key]) in content
    assert "Unarchive" in content
    assert reverse("dataset_export", args=[archived_dataset.key, "csv"]) not in content
    assert reverse("dataset_delete", args=[archived_dataset.key]) not in content


def test_archived_dataset_list_paginates_archived_datasets(auth_client, profile):
    for index in range(101):
        Dataset.objects.create(
            profile=profile,
            name=f"Archived dataset {index:03}",
            headers=["email"],
            index_column="email",
            row_count=0,
            archived_at=timezone.now(),
        )

    response = auth_client.get(reverse("archived_dataset_list"))
    content = response.content.decode()

    assert response.status_code == 200
    assert len(response.context["datasets"]) == 100
    assert "Page 1 of 2" in content

    page_two = auth_client.get(f"{reverse('archived_dataset_list')}?page=2")

    assert page_two.status_code == 200
    assert len(page_two.context["datasets"]) == 1
    assert "Page 2 of 2" in page_two.content.decode()


def test_dataset_detail_orders_row_cells_by_headers(auth_client, profile):
    dataset = Dataset.objects.create(
        profile=profile,
        name="Customers",
        headers=["customer_id", "name", "plan"],
        preview_rows=[{"name": "Ada Lovelace", "plan": "Scale", "customer_id": "C-1001"}],
        index_column="customer_id",
        row_count=1,
    )
    DatasetRow.objects.create(
        dataset=dataset,
        row_number=1,
        index_value="C-1001",
        data={"name": "Ada Lovelace", "plan": "Scale", "customer_id": "C-1001"},
    )

    response = auth_client.get(dataset.get_absolute_url())
    content = response.content.decode()

    assert response.status_code == 200
    assert "<title>Customers · Rowset</title>" in content
    customer_id_position = content.index("C-1001")
    name_position = content.index("Ada Lovelace")
    plan_position = content.index("Scale")
    assert customer_id_position < name_position < plan_position


def test_dataset_detail_renders_headers_for_sample_rows(auth_client, profile):
    dataset = Dataset.objects.create(
        profile=profile,
        name="Sample customers",
        headers=["sample_customer_id", "sample_plan"],
        preview_rows=[{"sample_customer_id": "C-1001", "sample_plan": "Scale"}],
        index_column="sample_customer_id",
        row_count=0,
    )

    response = auth_client.get(dataset.get_absolute_url())
    content = response.content.decode()

    assert response.status_code == 200
    assert response.context["rows_heading"] == "Sample rows"
    assert response.context["row_show_column_controls"] is False
    assert re.search(r'<th scope="col">\s*sample_customer_id\s*</th>', content)
    assert re.search(r'<th scope="col">\s*sample_plan\s*</th>', content)
    assert "C-1001" in content
    assert "Scale" in content


def test_dataset_detail_links_rows_and_truncates_cells(auth_client, profile):
    dataset = create_ready_dataset(profile)
    row = dataset.rows.first()

    response = auth_client.get(dataset.get_absolute_url())
    content = response.content.decode()

    assert response.status_code == 200
    assert reverse("dataset_row_detail", args=[dataset.key, row.id]) in content
    assert 'class="fb-focus block max-w-64 truncate' in content
    assert 'aria-label="View row 1 details"' in content
    assert content.count('aria-label="View row 1 details"') == 1
    assert 'aria-hidden="true" tabindex="-1"' in content


def test_dataset_detail_links_dataset_reference_cells(auth_client, profile):
    target = create_ready_dataset(profile)
    target.name = "Archived sprint tasks"
    target.archived_at = timezone.now()
    target.save(update_fields=["name", "archived_at"])
    source = Dataset.objects.create(
        profile=profile,
        name="Sprint history",
        headers=["sprint_id", "task_dataset"],
        column_schema={
            "sprint_id": {"type": DatasetColumnType.TEXT},
            "task_dataset": {
                "type": DatasetColumnType.REFERENCE,
                "target": "dataset",
            },
        },
        index_column="sprint_id",
        row_count=1,
    )
    DatasetRow.objects.create(
        dataset=source,
        row_number=1,
        index_value="SPRINT-1",
        data={
            "sprint_id": "SPRINT-1",
            "task_dataset": str(target.key),
        },
    )

    response = auth_client.get(source.get_absolute_url())
    content = response.content.decode()

    assert response.status_code == 200
    assert f'href="{target.get_absolute_url()}"' in content
    assert "Archived sprint tasks" in content
    assert "Archived dataset" in content


def test_dataset_detail_renders_rowset_dataset_urls_as_text(
    auth_client,
    profile,
):
    source_dataset = create_ready_dataset(profile)
    target_dataset = Dataset.objects.create(
        profile=profile,
        name="Sprint task board",
        headers=["task_id", "title"],
        index_column="task_id",
        row_count=0,
    )
    source_dataset.headers = ["name", "task_dataset_url"]
    source_dataset.save(update_fields=["headers"])
    row = source_dataset.rows.first()
    raw_url = f"https://rowset.lvtd.dev/datasets/{target_dataset.key}/"
    row.data = {
        "name": "Review Gate Sprint History",
        "task_dataset_url": raw_url,
    }
    row.save(update_fields=["data"])

    response = auth_client.get(source_dataset.get_absolute_url())
    content = main_content_html(response)

    assert response.status_code == 200
    assert raw_url in content
    assert f'href="{target_dataset.get_absolute_url()}"' not in content
    assert "Sprint task board" not in content
    assert "Ready" not in content
    assert "Open Rowset dataset Sprint task board" not in content


def test_dataset_detail_keeps_row_detail_link_for_single_rowset_url_column(
    auth_client,
    profile,
):
    source_dataset = create_ready_dataset(profile)
    target_dataset = create_ready_dataset(profile)
    target_dataset.name = "Sprint task board"
    target_dataset.save(update_fields=["name"])
    source_dataset.headers = ["task_dataset_url"]
    source_dataset.save(update_fields=["headers"])
    row = source_dataset.rows.first()
    raw_url = f"https://rowset.lvtd.dev/datasets/{target_dataset.key}/"
    row.data = {"task_dataset_url": raw_url}
    row.save(update_fields=["data"])
    row_url = reverse("dataset_row_detail", args=[source_dataset.key, row.id])

    response = auth_client.get(source_dataset.get_absolute_url())
    content = main_content_html(response)

    assert response.status_code == 200
    assert f'href="{row_url}"' in content
    assert raw_url in content
    assert f'href="{target_dataset.get_absolute_url()}"' not in content
    assert 'aria-label="View row 1 details"' in content
    assert content.count('aria-label="View row 1 details"') == 1
    assert 'class="sr-only">View row 1 details' not in content


def test_dataset_detail_renders_unresolved_rowset_urls_as_text(
    auth_client,
    profile,
):
    dataset = create_ready_dataset(profile)
    missing_dataset_key = "4b7b8e47-15a5-4bd5-82cb-8c4f4fd40ce9"
    raw_url = f"https://rowset.lvtd.dev/datasets/{missing_dataset_key}/"
    row = dataset.rows.first()
    row.data["name"] = raw_url
    row.save(update_fields=["data"])

    response = auth_client.get(dataset.get_absolute_url())
    content = response.content.decode()

    assert response.status_code == 200
    assert raw_url in content
    assert f'href="{raw_url}"' not in content
    assert "Open Rowset URL" not in content
    assert "Rowset dataset" not in content


def test_dataset_detail_does_not_link_protocol_relative_rowset_urls(
    auth_client,
    profile,
):
    dataset = create_ready_dataset(profile)
    target_dataset = create_ready_dataset(profile)
    dataset.headers = ["name", "task_dataset_url"]
    dataset.save(update_fields=["headers"])
    row = dataset.rows.first()
    raw_url = f"//evil.example/datasets/{target_dataset.key}/"
    row.data = {
        "name": "Review Gate Sprint History",
        "task_dataset_url": raw_url,
    }
    row.save(update_fields=["data"])

    response = auth_client.get(dataset.get_absolute_url())
    content = main_content_html(response)

    assert response.status_code == 200
    assert raw_url in content
    assert f'href="{raw_url}"' not in content
    assert f'href="{target_dataset.get_absolute_url()}"' not in content
    assert "Rowset dataset" not in content


def test_dataset_detail_falls_back_for_malformed_rowset_row_urls(
    auth_client,
    profile,
):
    dataset = create_ready_dataset(profile)
    target_dataset = create_ready_dataset(profile)
    raw_url = f"https://rowset.lvtd.dev/datasets/{target_dataset.key}/rows/not-a-row/"
    row = dataset.rows.first()
    row.data["name"] = raw_url
    row.save(update_fields=["data"])

    response = auth_client.get(dataset.get_absolute_url())
    content = main_content_html(response)

    assert response.status_code == 200
    assert raw_url in content
    assert f'href="{raw_url}"' not in content
    assert f'href="{target_dataset.get_absolute_url()}"' not in content
    assert "Rowset row" not in content


def test_dataset_detail_ignores_invalid_ipv6_rowset_url_candidates(
    auth_client,
    profile,
):
    dataset = create_ready_dataset(profile)
    raw_url = "https://[rowset.lvtd.dev/datasets/5f250d73-2a70-414e-826e-271e28837f28/"
    row = dataset.rows.first()
    row.data["name"] = raw_url
    row.save(update_fields=["data"])

    response = auth_client.get(dataset.get_absolute_url())
    content = response.content.decode()

    assert response.status_code == 200
    assert raw_url in content
    assert f'href="{raw_url}"' not in content
    assert "Rowset dataset" not in content


def test_dataset_detail_ignores_json_array_rowset_url_candidates(
    auth_client,
    profile,
):
    dataset = create_ready_dataset(profile)
    dataset.headers = ["report_id", "result", "checks_passed", "changed_files", "artifact_url"]
    dataset.column_schema = {
        "report_id": {"type": DatasetColumnType.TEXT},
        "result": {
            "type": DatasetColumnType.CHOICE,
            "choices": ["dry_run", "pending", "pass", "fail", "blocked"],
        },
        "checks_passed": {"type": DatasetColumnType.TEXT},
        "changed_files": {"type": DatasetColumnType.TEXT},
        "artifact_url": {"type": DatasetColumnType.URL},
    }
    dataset.index_column = "report_id"
    dataset.save(update_fields=["headers", "column_schema", "index_column"])
    row = dataset.rows.first()
    row.index_value = "sample-dry-run-report-001"
    row.data = {
        "report_id": "sample-dry-run-report-001",
        "result": "dry_run",
        "checks_passed": "[]",
        "changed_files": '["TODO: record changed files after the run"]',
        "artifact_url": "",
    }
    row.save(update_fields=["index_value", "data"])

    response = auth_client.get(dataset.get_absolute_url())
    content = response.content.decode()

    assert response.status_code == 200
    assert "sample-dry-run-report-001" in content
    assert "[]" in content
    assert "TODO: record changed files after the run" in content
    assert 'href="https://[]"' not in content
    assert "Rowset dataset" not in content


def test_dataset_detail_falls_back_for_unsupported_rowset_row_subpaths(
    auth_client,
    profile,
):
    dataset = create_ready_dataset(profile)
    target_dataset = create_ready_dataset(profile)
    target_row = target_dataset.rows.first()
    raw_url = f"https://rowset.lvtd.dev/datasets/{target_dataset.key}/rows/{target_row.id}/edit/"
    row = dataset.rows.first()
    row.data["name"] = raw_url
    row.save(update_fields=["data"])

    response = auth_client.get(dataset.get_absolute_url())
    content = main_content_html(response)

    assert response.status_code == 200
    assert raw_url in content
    assert f'href="{raw_url}"' not in content
    assert f'href="{target_row.get_absolute_url()}"' not in content
    assert f'href="{target_dataset.get_absolute_url()}"' not in content
    assert "Rowset row" not in content


def test_dataset_detail_falls_back_for_stale_rowset_row_urls(
    auth_client,
    profile,
):
    dataset = create_ready_dataset(profile)
    target_dataset = create_ready_dataset(profile)
    raw_url = f"https://rowset.lvtd.dev/datasets/{target_dataset.key}/rows/999999/"
    row = dataset.rows.first()
    row.data["name"] = raw_url
    row.save(update_fields=["data"])

    response = auth_client.get(dataset.get_absolute_url())
    content = main_content_html(response)

    assert response.status_code == 200
    assert raw_url in content
    assert f'href="{raw_url}"' not in content
    assert f'href="{target_dataset.get_absolute_url()}"' not in content
    assert "Rowset row" not in content


def test_dataset_detail_falls_back_for_root_relative_stale_rowset_row_urls(
    auth_client,
    profile,
):
    dataset = create_ready_dataset(profile)
    target_dataset = create_ready_dataset(profile)
    raw_url = f"/datasets/{target_dataset.key}/rows/999999/"
    row = dataset.rows.first()
    row.data["name"] = raw_url
    row.save(update_fields=["data"])

    response = auth_client.get(dataset.get_absolute_url())
    content = main_content_html(response)

    assert response.status_code == 200
    assert raw_url in content
    assert f'href="{raw_url}"' not in content
    assert f'href="{target_dataset.get_absolute_url()}"' not in content
    assert "Rowset row" not in content


def test_dataset_detail_does_not_resolve_disabled_share_urls_to_private_links(
    auth_client,
    profile,
):
    dataset = create_ready_dataset(profile)
    target_dataset = create_ready_dataset(profile)
    target_dataset.name = "Private Sprint Tasks"
    target_dataset.public_enabled = False
    target_dataset.save(update_fields=["name", "public_enabled"])
    raw_url = f"https://rowset.lvtd.dev/share/datasets/{target_dataset.public_key}/"
    row = dataset.rows.first()
    row.data["name"] = raw_url
    row.save(update_fields=["data"])

    response = auth_client.get(dataset.get_absolute_url())
    content = main_content_html(response)

    assert response.status_code == 200
    assert raw_url in content
    assert f'href="{raw_url}"' not in content
    assert target_dataset.get_absolute_url() not in content
    assert "Private Sprint Tasks" not in content
    assert "Open Rowset URL" not in content


def test_dataset_detail_paginates_rows_without_public_preview(auth_client, profile):
    dataset = create_ready_dataset(profile)
    dataset.rows.all().delete()
    total_rows = DATASET_DETAIL_ROW_PAGE_SIZE + 1
    DatasetRow.objects.bulk_create(
        [
            DatasetRow(
                dataset=dataset,
                row_number=row_number,
                index_value=f"person-{row_number:03}",
                data={
                    "name": f"Detail row {row_number:03}",
                    "email": f"person-{row_number:03}@example.com",
                },
            )
            for row_number in range(1, total_rows + 1)
        ]
    )
    dataset.row_count = total_rows
    dataset.public_enabled = False
    dataset.save(update_fields=["row_count", "public_enabled"])

    response = auth_client.get(f"{dataset.get_absolute_url()}?view=compact")
    content = response.content.decode()

    assert response.status_code == 200
    assert "Public preview:" not in content
    assert f"Showing 1-{DATASET_DETAIL_ROW_PAGE_SIZE} of {total_rows} rows" not in content
    assert "Page 1 of 2" in content
    assert 'href="?view=compact&amp;page=2"' in content
    assert "Detail row 001" in content
    assert f"Detail row {total_rows:03}" not in content

    page_two = auth_client.get(f"{dataset.get_absolute_url()}?view=compact&page=2")
    page_two_content = page_two.content.decode()
    assert page_two.status_code == 200
    assert "Page 2 of 2" in page_two_content
    assert f"Detail row {total_rows:03}" in page_two_content


def test_dataset_detail_filters_and_sorts_rows(auth_client, profile):
    dataset = configure_filterable_dataset(create_ready_dataset(profile))

    search_response = auth_client.get(dataset.get_absolute_url(), {"row_q": "grace"})
    search_content = search_response.content.decode()

    assert search_response.status_code == 200
    assert search_response.context["row_page_obj"].paginator.count == 1
    assert "Grace Hopper" in search_content
    assert "Ada Lovelace" not in search_content
    assert "Katherine Johnson" not in search_content
    assert 'value="grace"' in search_content

    filter_response = auth_client.get(
        dataset.get_absolute_url(),
        {
            "row_q": "a",
            "row_sort": "col_0",
            "row_dir": "desc",
            "filter_2": "10",
            "filter_3": "true",
        },
    )
    filter_content = filter_response.content.decode()

    assert filter_response.status_code == 200
    assert filter_response.context["row_page_obj"].paginator.count == 2
    assert "Ada Lovelace" in filter_content
    assert "Katherine Johnson" in filter_content
    assert "Grace Hopper" not in filter_content
    assert ">Clear</button>" in filter_content
    assert 'name="row_q" value="a"' in filter_content
    assert 'name="row_sort" value="col_0"' in filter_content
    assert 'name="row_dir" value="desc"' in filter_content
    assert 'name="filter_3" value="true"' in filter_content
    assert "Column filters" not in filter_content

    sort_response = auth_client.get(
        dataset.get_absolute_url(),
        {"row_sort": "col_0", "row_dir": "desc"},
    )
    sort_content = sort_response.content.decode()

    assert sort_response.status_code == 200
    assert sort_content.index("Katherine Johnson") < sort_content.index("Grace Hopper")
    assert sort_content.index("Grace Hopper") < sort_content.index("Ada Lovelace")

    numeric_sort_response = auth_client.get(
        dataset.get_absolute_url(),
        {"row_sort": "col_2"},
    )
    numeric_sort_content = numeric_sort_response.content.decode()

    assert numeric_sort_response.status_code == 200
    assert numeric_sort_content.index("Grace Hopper") < numeric_sort_content.index("Ada Lovelace")
    assert numeric_sort_content.index("Ada Lovelace") < numeric_sort_content.index(
        "Katherine Johnson"
    )


def test_dataset_detail_filters_numeric_columns_with_above_and_below(auth_client, profile):
    dataset = configure_filterable_dataset(create_ready_dataset(profile))

    above_response = auth_client.get(
        dataset.get_absolute_url(),
        {"filter_2": "9", "filter_op_2": "above"},
    )
    above_content = above_response.content.decode()

    assert above_response.status_code == 200
    assert above_response.context["row_page_obj"].paginator.count == 2
    assert above_response.context["row_filter_fields"][2]["operator"] == "above"
    assert "Ada Lovelace" in above_content
    assert "Katherine Johnson" in above_content
    assert "Grace Hopper" not in above_content
    assert 'name="filter_op_2"' in above_content
    assert '<option value="above" selected>Above</option>' in above_content

    below_response = auth_client.get(
        dataset.get_absolute_url(),
        {"filter_2": "9", "filter_op_2": "below"},
    )
    below_content = below_response.content.decode()

    assert below_response.status_code == 200
    assert below_response.context["row_page_obj"].paginator.count == 1
    assert "Grace Hopper" in below_content
    assert "Ada Lovelace" not in below_content
    assert "Katherine Johnson" not in below_content


def test_dataset_detail_filters_datetime_columns_with_above_and_below(auth_client, profile):
    dataset = configure_datetime_dataset(create_ready_dataset(profile))
    add_invalid_datetime_row(dataset)

    above_response = auth_client.get(
        dataset.get_absolute_url(),
        {"filter_2": "2026-05-14T08:30", "filter_op_2": "above"},
    )
    above_content = above_response.content.decode()

    assert above_response.status_code == 200
    assert above_response.context["row_page_obj"].paginator.count == 2
    assert above_response.context["row_filter_fields"][2]["operator"] == "above"
    assert "UTC later" in above_content
    assert "Next day" in above_content
    assert "Offset early" not in above_content
    assert "Invalid date" not in above_content
    assert "Invalid time" not in above_content
    assert "Invalid year" not in above_content
    assert 'name="filter_op_2"' in above_content
    assert '<option value="above" selected>Above</option>' in above_content

    below_response = auth_client.get(
        dataset.get_absolute_url(),
        {"filter_2": "2026-05-14T08:30", "filter_op_2": "below"},
    )
    below_content = below_response.content.decode()

    assert below_response.status_code == 200
    assert below_response.context["row_page_obj"].paginator.count == 1
    assert "Offset early" in below_content
    assert "UTC later" not in below_content
    assert "Next day" not in below_content
    assert "Invalid date" not in below_content
    assert "Invalid time" not in below_content
    assert "Invalid year" not in below_content


def test_dataset_detail_semantic_text_filters_accept_partial_values(auth_client, profile):
    dataset = create_ready_dataset(profile)
    dataset.headers = ["email", "website"]
    dataset.column_schema = {
        "email": {"type": DatasetColumnType.EMAIL},
        "website": {"type": DatasetColumnType.URL},
    }
    dataset.preview_rows = []
    dataset.rows.all().delete()
    dataset.save(update_fields=["headers", "column_schema", "preview_rows"])
    DatasetRow.objects.create(
        dataset=dataset,
        row_number=1,
        index_value="ada@example.com",
        data={"email": "ada@example.com", "website": "https://example.com/ada"},
    )

    response = auth_client.get(dataset.get_absolute_url())
    content = response.content.decode()

    assert response.status_code == 200
    assert "Column filters" not in content
    assert 'id="row-column-filter-0"' in content
    assert 'id="row-column-filter-1"' in content
    assert 'name="filter_0"' in content
    assert 'name="filter_1"' in content

    repeated_response = auth_client.get(
        dataset.get_absolute_url(),
        {"filter_0": ["not-a-match", "ada"]},
    )

    assert repeated_response.status_code == 200
    assert repeated_response.context["row_page_obj"].paginator.count == 1
    assert repeated_response.context["row_filter_fields"][0]["value"] == "ada"


def test_dataset_detail_renders_url_cells_as_text(auth_client, profile):
    dataset = create_ready_dataset(profile)
    dataset.headers = ["name", "website", "unsafe"]
    dataset.column_schema = {
        "name": {"type": DatasetColumnType.TEXT},
        "website": {"type": DatasetColumnType.URL},
        "unsafe": {"type": DatasetColumnType.TEXT},
    }
    dataset.save(update_fields=["headers", "column_schema"])
    row = dataset.rows.first()
    row.data = {
        "name": "Ada",
        "website": "https://example.com/ada?ref=rowset&ok=1",
        "unsafe": "javascript:alert(1)",
    }
    row.save(update_fields=["data"])

    response = auth_client.get(dataset.get_absolute_url())
    content = response.content.decode()

    assert response.status_code == 200
    assert "https://example.com/ada?ref=rowset&amp;ok=1" in content
    assert 'href="https://example.com/ada?ref=rowset&amp;ok=1"' not in content
    assert 'target="_blank" rel="nofollow ugc noopener noreferrer"' not in content
    assert "javascript:alert(1)" in content
    assert 'href="javascript:alert(1)"' not in content


def test_dataset_detail_keeps_row_detail_link_for_single_text_url_column(auth_client, profile):
    dataset = create_ready_dataset(profile)
    dataset.headers = ["website"]
    dataset.column_schema = {"website": {"type": DatasetColumnType.URL}}
    dataset.save(update_fields=["headers", "column_schema"])
    row = dataset.rows.first()
    row.data = {"website": "https://example.com/ada"}
    row.save(update_fields=["data"])
    row_url = reverse("dataset_row_detail", args=[dataset.key, row.id])

    response = auth_client.get(dataset.get_absolute_url())
    content = response.content.decode()

    assert response.status_code == 200
    assert "https://example.com/ada" in content
    assert 'href="https://example.com/ada"' not in content
    assert f'href="{row_url}"' in content
    assert 'aria-label="View row 1 details"' in content
    assert 'aria-label="Open external link for row 1"' not in content
    assert ">Open</a>" not in content


def test_dataset_detail_filtered_empty_state_does_not_show_preview_rows(auth_client, profile):
    dataset = configure_filterable_dataset(create_ready_dataset(profile))

    response = auth_client.get(dataset.get_absolute_url(), {"row_q": "missing"})
    content = response.content.decode()

    assert response.status_code == 200
    assert response.context["row_page_obj"].paginator.count == 0
    assert "No rows match these filters." in content
    assert "Ada" not in content


def test_dataset_detail_unknown_boolean_filter_returns_no_rows(auth_client, profile):
    dataset = configure_filterable_dataset(create_ready_dataset(profile))

    response = auth_client.get(dataset.get_absolute_url(), {"filter_3": "maybe"})
    content = response.content.decode()

    assert response.status_code == 200
    assert response.context["row_page_obj"].paginator.count == 0
    assert "No rows match these filters." in content
    assert "Ada Lovelace" not in content
    assert "Grace Hopper" not in content
    assert "Katherine Johnson" not in content


def test_dataset_detail_row_search_caps_wide_schema(auth_client, profile):
    dataset = create_ready_dataset(profile)
    headers = [f"field_{index:02d}" for index in range(25)]
    dataset.headers = headers
    dataset.column_schema = {header: {"type": DatasetColumnType.TEXT} for header in headers}
    dataset.row_count = 1
    dataset.preview_rows = []
    dataset.rows.all().delete()
    dataset.save(update_fields=["headers", "column_schema", "row_count", "preview_rows"])
    DatasetRow.objects.create(
        dataset=dataset,
        row_number=1,
        index_value="wide-row",
        data={
            **{header: "" for header in headers},
            "field_19": "Visible within cap",
            "field_20": "Hidden outside cap",
        },
    )

    within_cap_response = auth_client.get(dataset.get_absolute_url(), {"row_q": "visible"})
    within_cap_content = within_cap_response.content.decode()

    assert within_cap_response.status_code == 200
    assert within_cap_response.context["row_page_obj"].paginator.count == 1
    assert "Visible within cap" in within_cap_content

    outside_cap_response = auth_client.get(dataset.get_absolute_url(), {"row_q": "hidden"})
    outside_cap_content = outside_cap_response.content.decode()

    assert outside_cap_response.status_code == 200
    assert outside_cap_response.context["row_page_obj"].paginator.count == 0
    assert "No rows match these filters." in outside_cap_content
    assert "Hidden outside cap" not in outside_cap_content


def test_dataset_detail_row_search_empty_headers_returns_no_rows(auth_client, profile):
    dataset = create_ready_dataset(profile)
    dataset.headers = []
    dataset.column_schema = {}
    dataset.row_count = 1
    dataset.preview_rows = []
    dataset.rows.all().delete()
    dataset.save(update_fields=["headers", "column_schema", "row_count", "preview_rows"])
    DatasetRow.objects.create(
        dataset=dataset,
        row_number=1,
        index_value="empty-header-row",
        data={"stored_field": "Invisible to header search"},
    )

    response = auth_client.get(dataset.get_absolute_url(), {"row_q": "invisible"})
    content = response.content.decode()

    assert response.status_code == 200
    assert response.context["row_page_obj"].paginator.count == 0
    assert "No rows match these filters." in content
    assert "Invisible to header search" not in content


def test_dataset_row_detail_displays_full_row_data(auth_client, profile):
    dataset = create_ready_dataset(profile)
    dataset.headers = ["name", "email", "notes"]
    dataset.save(update_fields=["headers"])
    row = dataset.rows.first()
    full_value = "Line one\n" + "Full untruncated value " * 12
    row.data = {
        "name": "Ada",
        "email": "ada@example.com",
        "notes": full_value,
        "extra_field": "Stored outside declared headers",
    }
    row.save(update_fields=["data"])

    response = auth_client.get(reverse("dataset_row_detail", args=[dataset.key, row.id]))
    content = response.content.decode()

    assert response.status_code == 200
    assert "<title>People · ada@example.com · Rowset</title>" in content
    assert "Row 1" in content
    assert "notes" in content
    assert full_value in content
    assert "extra_field" in content
    assert "Stored outside declared headers" in content
    assert "← back to People." in content
    assert "Back to dataset" not in content
    assert 'td class="min-w-96 whitespace-pre-wrap break-words"' not in content
    assert '<span class="whitespace-pre-wrap break-words">Ada</span>' in content
    assert 'x-data="rowInlineEdit"' in content
    assert 'aria-label="Edit name"' in content
    assert 'aria-label="Edit email"' in content
    email_input_index = content.index('name="email"')
    email_input_snippet = content[email_input_index : email_input_index + 420]
    assert "required" in email_input_snippet
    assert "Save row" in content


def test_dataset_row_detail_links_previous_and_next_rows(auth_client, profile):
    dataset = create_ready_dataset(profile)
    previous_row = dataset.rows.get(row_number=1)
    current_row = dataset.rows.get(row_number=2)
    next_row = DatasetRow.objects.create(
        dataset=dataset,
        row_number=3,
        index_value="katherine@example.com",
        data={"name": "Katherine", "email": "katherine@example.com"},
    )

    response = auth_client.get(reverse("dataset_row_detail", args=[dataset.key, current_row.id]))
    content = response.content.decode()

    assert response.status_code == 200
    assert response.context["has_dataset_row_navigation"] is True
    assert response.context["previous_dataset_row"] == previous_row
    assert response.context["next_dataset_row"] == next_row
    previous_url = reverse("dataset_row_detail", args=[dataset.key, previous_row.id])
    next_url = reverse("dataset_row_detail", args=[dataset.key, next_row.id])
    assert f'href="{previous_url}"' in content
    assert f'href="{next_url}"' in content
    assert ">Previous Row</a>" in content
    assert ">Next Row</a>" in content
    row_data_section_start = content.index('aria-labelledby="row-data-heading"')
    row_data_section_end = content.index("</section>", row_data_section_start)
    assert content.index("Previous Row") > row_data_section_end
    assert content.index("Next Row") > row_data_section_end


def test_dataset_row_detail_disables_missing_row_navigation_edges(auth_client, profile):
    dataset = create_ready_dataset(profile)
    first_row = dataset.rows.get(row_number=1)
    last_row = dataset.rows.get(row_number=2)
    first_row_url = reverse("dataset_row_detail", args=[dataset.key, first_row.id])
    last_row_url = reverse("dataset_row_detail", args=[dataset.key, last_row.id])

    first_response = auth_client.get(first_row_url)
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

    last_response = auth_client.get(last_row_url)
    last_content = last_response.content.decode()

    assert last_response.status_code == 200
    assert last_response.context["previous_dataset_row"] == first_row
    assert last_response.context["previous_dataset_row_url"] == first_row_url
    assert last_response.context["next_dataset_row"] is None
    assert last_response.context["next_dataset_row_url"] == ""
    assert "Previous Row" in last_content
    assert "Next Row" in last_content
    assert f'href="{first_row_url}"' in last_content


def test_dataset_row_detail_hides_edit_controls_for_archived_dataset(auth_client, profile):
    dataset = create_ready_dataset(profile)
    dataset.archived_at = timezone.now()
    dataset.save(update_fields=["archived_at"])
    row = dataset.rows.get(row_number=1)

    response = auth_client.get(reverse("dataset_row_detail", args=[dataset.key, row.id]))
    content = response.content.decode()

    assert response.status_code == 200
    assert "Ada" in content
    assert "Edit individual values without leaving the row." not in content
    assert 'x-data="rowInlineEdit"' not in content
    assert 'aria-label="Edit name"' not in content
    assert "Save row" not in content


def test_dataset_row_create_view_creates_row(auth_client, profile):
    dataset = create_ready_dataset(profile)

    response = auth_client.post(
        reverse("dataset_row_create", args=[dataset.key]),
        data={"name": "Katherine", "email": "kat@example.com"},
    )

    assert response.status_code == 302
    row = dataset.rows.get(index_value="kat@example.com")
    assert response.url == row.get_absolute_url()
    dataset.refresh_from_db()
    assert dataset.row_count == 3
    assert row.data == {"name": "Katherine", "email": "kat@example.com"}
    assert dataset.mutations.filter(mutation_type=DatasetMutationType.ROW_CREATED).exists()


def test_dataset_row_create_view_renders_schema_specific_inputs(auth_client, profile):
    dataset = create_typed_row_dataset(profile)

    response = auth_client.get(reverse("dataset_row_create", args=[dataset.key]))
    content = response.content.decode()

    assert response.status_code == 200
    assert "<title>New row · Typed rows · Rowset</title>" in content
    fields = {field["header"]: field for field in response.context["row_form_fields"]}
    assert fields["row_id"]["input_type"] == "text"
    assert fields["row_id"]["is_textarea"] is False
    assert fields["status"]["is_choice"] is True
    assert [choice["value"] for choice in fields["status"]["choices"]] == [
        "Backlog",
        "Doing",
        "Done",
    ]
    assert fields["active"]["is_boolean"] is True
    assert fields["due_on"]["input_type"] == "date"
    assert fields["scheduled_at"]["input_type"] == "datetime-local"
    assert fields["count"]["input_type"] == "number"
    assert fields["count"]["input_step"] == "1"
    assert fields["count"]["input_mode"] == "numeric"
    assert fields["score"]["input_step"] == "any"
    assert fields["budget"]["input_step"] == "any"
    assert fields["contact"]["input_type"] == "email"
    assert fields["website"]["input_type"] == "url"
    assert fields["related_dataset"]["input_type"] == "text"
    assert fields["notes"]["is_textarea"] is True
    assert fields["photo"]["is_image"] is True
    assert 'name="status"' in content
    assert 'value="Doing"' in content
    assert 'name="active"' in content
    assert 'value="false"' in content
    assert 'name="due_on"' in content
    assert 'type="date"' in content
    assert 'name="scheduled_at"' in content
    assert 'type="datetime-local"' in content
    assert 'name="count"' in content
    assert 'step="1"' in content
    assert 'name="score"' in content
    assert 'step="any"' in content
    assert 'name="contact"' in content
    assert 'type="email"' in content
    assert 'name="website"' in content
    assert 'type="url"' in content
    assert "Image assets can be attached after the row is created." in content


def test_dataset_row_create_view_creates_row_from_schema_specific_inputs(
    auth_client,
    profile,
):
    dataset = create_typed_row_dataset(profile)

    response = auth_client.post(
        reverse("dataset_row_create", args=[dataset.key]),
        data=typed_row_post_data(
            row_id="ROW-2",
            status="Doing",
            active="false",
            count="3",
            score="9.75",
            budget="250.50",
            contact="grace@example.com",
            website="https://example.com/grace",
            notes="Follow up\nSend recap",
        ),
    )

    row = dataset.rows.get(index_value="ROW-2")
    assert response.status_code == 302
    assert response.url == row.get_absolute_url()
    assert row.data == {
        "row_id": "ROW-2",
        "status": "Doing",
        "active": "false",
        "due_on": "2026-07-01",
        "scheduled_at": "2026-07-01T09:30",
        "count": "3",
        "score": "9.75",
        "budget": "250.50",
        "contact": "grace@example.com",
        "website": "https://example.com/grace",
        "related_dataset": "",
        "notes": "Follow up\nSend recap",
        "photo": "",
    }


def test_dataset_row_create_view_rerenders_schema_specific_values_on_error(
    auth_client,
    profile,
):
    dataset = create_typed_row_dataset(profile)

    response = auth_client.post(
        reverse("dataset_row_create", args=[dataset.key]),
        data=typed_row_post_data(
            status="Doing",
            active="false",
            count="3",
            score="9.75",
            budget="250.50",
            contact="grace@example.com",
            website="https://example.com/grace",
            notes="Follow up",
        ),
    )
    content = response.content.decode()

    assert response.status_code == 200
    assert "Row with index" in content
    assert '<option value="Doing" selected>Doing</option>' in content
    assert '<option value="false" selected>False</option>' in content
    assert 'value="2026-07-01"' in content
    assert 'value="2026-07-01T09:30"' in content
    assert 'value="9.75"' in content
    assert "Follow up</textarea>" in content
    assert dataset.rows.count() == 1


def test_dataset_row_create_view_rerenders_service_errors(auth_client, profile):
    dataset = create_ready_dataset(profile)

    response = auth_client.post(
        reverse("dataset_row_create", args=[dataset.key]),
        data={"name": "Duplicate Ada", "email": "ada@example.com"},
    )
    content = response.content.decode()

    assert response.status_code == 200
    assert "Row with index" in content
    assert "Duplicate Ada" in content
    assert dataset.rows.count() == 2


def test_dataset_row_create_view_uses_generated_index(auth_client, profile):
    dataset = Dataset.objects.create(
        profile=profile,
        name="Tasks",
        headers=["rowset_id", "task"],
        index_column="rowset_id",
        index_generated=True,
        row_count=0,
    )

    response = auth_client.post(
        reverse("dataset_row_create", args=[dataset.key]),
        data={"task": "Ship UI CRUD"},
    )

    row = dataset.rows.get()
    dataset.refresh_from_db()
    assert response.status_code == 302
    assert response.url == row.get_absolute_url()
    assert row.index_value == "1"
    assert row.data == {"rowset_id": "1", "task": "Ship UI CRUD"}
    assert dataset.row_count == 1


def test_dataset_row_detail_updates_opened_fields(auth_client, profile):
    dataset = create_ready_dataset(profile)
    row = dataset.rows.get(row_number=1)

    response = auth_client.post(
        reverse("dataset_row_detail", args=[dataset.key, row.id]),
        data={"name": "Ada Lovelace"},
    )

    assert response.status_code == 302
    row.refresh_from_db()
    assert row.data == {"name": "Ada Lovelace", "email": "ada@example.com"}
    mutation = dataset.mutations.get(mutation_type=DatasetMutationType.ROW_UPDATED)
    assert mutation.metadata["changed_fields"] == ["name"]


def test_dataset_row_detail_rerenders_update_errors(auth_client, profile):
    dataset = create_ready_dataset(profile)
    row = dataset.rows.get(row_number=1)

    response = auth_client.post(
        reverse("dataset_row_detail", args=[dataset.key, row.id]),
        data={"email": "grace@example.com"},
    )
    content = response.content.decode()

    assert response.status_code == 200
    assert "Row with index" in content
    assert "grace@example.com" in content
    row.refresh_from_db()
    assert row.index_value == "ada@example.com"


def test_dataset_rows_bulk_action_deletes_selected_rows(auth_client, profile):
    dataset = create_ready_dataset(profile)
    selected_rows = list(dataset.rows.order_by("row_number"))

    response = auth_client.post(
        reverse("dataset_rows_bulk_action", args=[dataset.key]),
        data={
            "bulk_action": "delete",
            "row_id": [selected_rows[0].id, selected_rows[1].id],
        },
    )

    assert response.status_code == 302
    assert response.url == dataset.get_absolute_url()
    assert not DatasetRow.objects.filter(id__in=[row.id for row in selected_rows]).exists()
    dataset.refresh_from_db()
    assert dataset.row_count == 0
    assert dataset.mutations.filter(mutation_type=DatasetMutationType.ROW_DELETED).count() == 2


def test_dataset_rows_bulk_action_requires_selection(auth_client, profile):
    dataset = create_ready_dataset(profile)

    response = auth_client.post(
        reverse("dataset_rows_bulk_action", args=[dataset.key]),
        data={"bulk_action": "delete"},
    )

    assert response.status_code == 302
    assert dataset.rows.count() == 2


def test_dataset_row_detail_updates_row_fields_inline(auth_client, profile):
    dataset = create_ready_dataset(profile)
    row = dataset.rows.get(row_number=1)

    response = auth_client.post(
        reverse("dataset_row_detail", args=[dataset.key, row.id]),
        data={
            "name": "Ada Lovelace",
            "email": "ada+ui@example.com",
        },
    )

    row.refresh_from_db()
    assert response.status_code == 302
    assert response.url == row.get_absolute_url()
    assert row.index_value == "ada+ui@example.com"
    assert row.data == {
        "name": "Ada Lovelace",
        "email": "ada+ui@example.com",
    }
    assert dataset.mutations.filter(
        mutation_type=DatasetMutationType.ROW_UPDATED,
        target_identifier=row.id,
    ).exists()


def test_dataset_row_detail_rejects_other_users_inline_update(
    client,
    django_user_model,
    profile,
):
    dataset = create_ready_dataset(profile)
    row = dataset.rows.get(row_number=1)
    other_user = django_user_model.objects.create_user(
        username="other-row-editor",
        email="other-row-editor@example.com",
        password="password123",
    )
    client.force_login(other_user)

    response = client.post(
        reverse("dataset_row_detail", args=[dataset.key, row.id]),
        data={
            "name": "Edited elsewhere",
            "email": "edited@example.com",
        },
    )

    row.refresh_from_db()
    assert response.status_code == 404
    assert row.data["name"] == "Ada"
    assert row.index_value == "ada@example.com"


def test_dataset_row_detail_renders_url_cells_as_text(auth_client, profile):
    dataset = create_ready_dataset(profile)
    dataset.headers = ["name", "website", "unsafe"]
    dataset.save(update_fields=["headers"])
    row = dataset.rows.first()
    row.data = {
        "name": "Ada",
        "website": "https://example.com/ada",
        "unsafe": "https://example.com/<script>",
    }
    row.save(update_fields=["data"])

    response = auth_client.get(reverse("dataset_row_detail", args=[dataset.key, row.id]))
    content = response.content.decode()

    assert response.status_code == 200
    assert "https://example.com/ada" in content
    assert 'href="https://example.com/ada"' not in content
    assert 'target="_blank" rel="nofollow ugc noopener noreferrer"' not in content
    assert "https://example.com/&lt;script&gt;" in content
    assert 'href="https://example.com/&lt;script&gt;"' not in content


def test_dataset_row_detail_renders_rowset_row_urls_as_text(
    auth_client,
    profile,
):
    source_dataset = create_ready_dataset(profile)
    target_dataset = create_ready_dataset(profile)
    target_dataset.name = "Sprint task board"
    target_dataset.save(update_fields=["name"])
    target_row = target_dataset.rows.first()
    source_row = source_dataset.rows.first()
    raw_url = f"https://rowset.lvtd.dev/datasets/{target_dataset.key}/rows/{target_row.id}/"
    source_row.data["name"] = raw_url
    source_row.save(update_fields=["data"])

    response = auth_client.get(
        reverse("dataset_row_detail", args=[source_dataset.key, source_row.id])
    )
    content = response.content.decode()

    assert response.status_code == 200
    assert raw_url in content
    assert f'href="{target_row.get_absolute_url()}"' not in content
    assert "Sprint task board row 1" not in content


def test_dataset_row_detail_rejects_other_users_row(client, django_user_model, profile):
    dataset = create_ready_dataset(profile)
    row = dataset.rows.first()
    other_user = django_user_model.objects.create_user(
        username="other-row-viewer",
        email="other-row-viewer@example.com",
        password="password123",
    )
    client.force_login(other_user)

    response = client.get(reverse("dataset_row_detail", args=[dataset.key, row.id]))

    assert response.status_code == 404


def test_dataset_changes_rejects_other_users_dataset(client, django_user_model, profile):
    dataset = create_ready_dataset(profile)
    other_user = django_user_model.objects.create_user(
        username="other-changes-viewer",
        email="other-changes-viewer@example.com",
        password="password123",
    )
    client.force_login(other_user)

    response = client.get(dataset.get_changes_url())

    assert response.status_code == 404


def test_dataset_changes_field_details_are_collapsed_by_default(auth_client, profile):
    dataset = create_ready_dataset(profile)
    row = dataset.rows.get(row_number=1)
    mutation = record_dataset_mutation(
        dataset,
        DatasetMutationType.ROW_UPDATED,
        "Row 1 updated.",
        target_type="row",
        target_identifier=row.id,
        metadata={
            "row_id": row.id,
            "row_number": row.row_number,
            "changed_fields": ["email"],
            "field_changes": [
                {
                    "field": "email",
                    "before": "ada@example.com",
                    "after": "ada+updated@example.com",
                }
            ],
            "value_changes_recorded": True,
            "index_changed": True,
        },
    )

    response = auth_client.get(dataset.get_changes_url())
    content = response.content.decode()

    assert response.status_code == 200
    details_match = re.search(
        rf'<details\b[^>]*aria-labelledby="dataset-change-{mutation.id}-summary"[^>]*>',
        content,
    )
    assert details_match is not None
    assert not re.search(r"\sopen(?:[\s=>]|$)", details_match.group(0))
    assert f'id="dataset-change-{mutation.id}-summary"' in content
    assert "Full view" in content
    assert "Collapse" in content
    assert "ada@example.com" in content
    assert "ada+updated@example.com" in content


def test_dataset_detail_context_is_collapsed_by_default_and_wraps_content(auth_client, profile):
    dataset = create_ready_dataset(profile)
    dataset.description = "A" * 180
    dataset.instructions = "Keep " + ("agent-instruction-token" * 12)
    dataset.metadata = {"long_key": "metadata-value-token" * 12}
    dataset.save(update_fields=["description", "instructions", "metadata"])

    response = auth_client.get(dataset.get_absolute_url())

    content = response.content.decode()
    assert response.status_code == 200
    details_match = re.search(
        r'<details\b[^>]*aria-labelledby="dataset-context-heading"[^>]*>',
        content,
    )
    assert details_match is not None
    details_tag = details_match.group(0)
    assert not re.search(r"\sopen(?:[\s=>]|$)", details_tag)
    assert "fb-card" in details_tag
    assert "overflow-hidden" in details_tag
    assert "Show context" in content
    assert "Hide context" in content
    for class_name in ("max-w-full", "whitespace-pre-wrap", "break-words"):
        assert class_name in content
    for class_name in ("max-h-72", "overflow-auto"):
        assert class_name in content


def test_dataset_detail_shows_archive_action_for_active_dataset(auth_client, profile):
    dataset = create_ready_dataset(profile)

    response = auth_client.get(dataset.get_absolute_url())
    content = response.content.decode()

    assert response.status_code == 200
    assert reverse("dataset_archive", args=[dataset.key]) in content
    assert "Archive" in content
    assert "Dataset archived" not in content


def test_dataset_detail_shows_archived_badge_without_archive_action(auth_client, profile):
    dataset = create_ready_dataset(profile)
    dataset.archived_at = timezone.now()
    dataset.save(update_fields=["archived_at"])

    response = auth_client.get(dataset.get_absolute_url())
    content = response.content.decode()

    assert response.status_code == 200
    assert 'aria-label="Dataset archived"' in content
    assert reverse("dataset_archive", args=[dataset.key]) not in content
    assert reverse("dataset_restore", args=[dataset.key]) in content
    assert "Unarchive" in content


def test_dataset_archive_archives_owned_dataset(auth_client, profile):
    dataset = create_ready_dataset(profile)
    dataset.public_enabled = True
    dataset.save(update_fields=["public_enabled"])

    response = auth_client.post(reverse("dataset_archive", args=[dataset.key]))

    assert response.status_code == 302
    assert response.url == reverse("home")
    dataset.refresh_from_db()
    assert dataset.archived_at is not None
    assert dataset.public_enabled is False


def test_dataset_archive_requires_post(auth_client, profile):
    dataset = create_ready_dataset(profile)

    response = auth_client.get(reverse("dataset_archive", args=[dataset.key]))

    assert response.status_code == 405


def test_dataset_archive_uses_info_message_for_already_archived_dataset(auth_client, profile):
    dataset = create_ready_dataset(profile)
    dataset.archived_at = timezone.now()
    dataset.save(update_fields=["archived_at"])

    response = auth_client.post(reverse("dataset_archive", args=[dataset.key]))

    assert response.status_code == 302
    assert response.url == reverse("home")
    flash_messages = list(get_messages(response.wsgi_request))
    assert len(flash_messages) == 1
    assert flash_messages[0].level == message_constants.INFO
    assert str(flash_messages[0]) == "Dataset was already archived."


def test_dataset_archive_rejects_other_users_dataset(client, django_user_model, profile):
    dataset = create_ready_dataset(profile)
    other_user = django_user_model.objects.create_user(
        username="other-archive",
        email="other-archive@example.com",
        password="password123",
    )
    client.force_login(other_user)

    response = client.post(reverse("dataset_archive", args=[dataset.key]))

    assert response.status_code == 404
    dataset.refresh_from_db()
    assert dataset.archived_at is None


def test_dataset_restore_restores_owned_dataset(auth_client, profile):
    dataset = create_ready_dataset(profile)
    dataset.archived_at = timezone.now()
    dataset.save(update_fields=["archived_at"])

    response = auth_client.post(reverse("dataset_restore", args=[dataset.key]))

    assert response.status_code == 302
    assert response.url == dataset.get_absolute_url()
    dataset.refresh_from_db()
    assert dataset.archived_at is None
    flash_messages = list(get_messages(response.wsgi_request))
    assert len(flash_messages) == 1
    assert flash_messages[0].level == message_constants.SUCCESS
    assert str(flash_messages[0]) == "Dataset restored."


def test_dataset_restore_requires_post(auth_client, profile):
    dataset = create_ready_dataset(profile)
    dataset.archived_at = timezone.now()
    dataset.save(update_fields=["archived_at"])

    response = auth_client.get(reverse("dataset_restore", args=[dataset.key]))

    assert response.status_code == 405


def test_dataset_restore_rejects_other_users_dataset(client, django_user_model, profile):
    dataset = create_ready_dataset(profile)
    dataset.archived_at = timezone.now()
    dataset.save(update_fields=["archived_at"])
    other_user = django_user_model.objects.create_user(
        username="other-restore",
        email="other-restore@example.com",
        password="password123",
    )
    client.force_login(other_user)

    response = client.post(reverse("dataset_restore", args=[dataset.key]))

    assert response.status_code == 404
    dataset.refresh_from_db()
    assert dataset.archived_at is not None


def test_trial_account_can_restore_third_active_dataset(auth_client, profile):
    create_ready_dataset(profile)
    create_ready_dataset(profile)
    archived_dataset = create_ready_dataset(profile)
    archived_dataset.archived_at = timezone.now()
    archived_dataset.save(update_fields=["archived_at"])

    response = auth_client.post(reverse("dataset_restore", args=[archived_dataset.key]))

    assert response.status_code == 302
    assert response.url == archived_dataset.get_absolute_url()
    archived_dataset.refresh_from_db()
    assert archived_dataset.archived_at is None
    assert (
        Dataset.objects.filter(
            profile=profile,
            archived_at__isnull=True,
        ).count()
        == 3
    )
    flash_messages = list(get_messages(response.wsgi_request))
    assert len(flash_messages) == 1
    assert flash_messages[0].level == message_constants.SUCCESS
    assert str(flash_messages[0]) == "Dataset restored."


def test_dataset_delete_removes_owned_dataset(auth_client, profile):
    dataset = create_ready_dataset(profile)

    response = auth_client.post(reverse("dataset_delete", args=[dataset.key]))

    assert response.status_code == 302
    assert not Dataset.objects.filter(id=dataset.id).exists()
    assert not DatasetRow.objects.filter(dataset_id=dataset.id).exists()


def test_dataset_delete_rejects_other_users_dataset(client, django_user_model, profile):
    dataset = create_ready_dataset(profile)
    other_user = django_user_model.objects.create_user(
        username="other-delete",
        email="other-delete@example.com",
        password="password123",
    )
    client.force_login(other_user)

    response = client.post(reverse("dataset_delete", args=[dataset.key]))

    assert response.status_code == 404
    assert Dataset.objects.filter(id=dataset.id).exists()


def test_dataset_changes_hides_legacy_placeholder_diff_labels(auth_client, profile):
    dataset = create_ready_dataset(profile)
    row = dataset.rows.get(row_number=1)
    second_row = dataset.rows.get(row_number=2)
    record_dataset_mutation(
        dataset,
        DatasetMutationType.ROW_UPDATED,
        "Row 1 updated.",
        target_type="row",
        target_identifier=row.id,
        metadata={
            "row_id": row.id,
            "row_number": row.row_number,
            "changed_fields": ["name"],
            "field_changes": [
                {
                    "field": "name",
                    "before": "Previous value",
                    "after": "New value",
                }
            ],
            "index_changed": False,
        },
    )
    record_dataset_mutation(
        dataset,
        DatasetMutationType.ROW_UPDATED,
        "Row 2 updated.",
        target_type="row",
        target_identifier=second_row.id,
        metadata={
            "row_id": second_row.id,
            "row_number": second_row.row_number,
            "changed_fields": ["name"],
            "field_changes": [
                {
                    "field": "name",
                    "before": "",
                    "after": "Filled",
                }
            ],
            "index_changed": False,
        },
    )

    changes_content = auth_client.get(dataset.get_changes_url()).content.decode()

    assert "Row 1 updated." in changes_content
    assert "Row 2 updated." in changes_content
    assert "Not recorded" in changes_content
    assert "Blank" in changes_content
    assert "Filled" not in changes_content
    assert "Previous value" not in changes_content
    assert "New value" not in changes_content


def test_trial_account_can_create_51st_dataset_row(profile):
    result = create_profile_dataset(
        profile,
        name="Free row capped dataset",
        headers=["name"],
        rows=[{"name": str(index)} for index in range(50)],
    )

    row_result = create_profile_dataset_row(
        profile,
        result["dataset"]["key"],
        {"name": "51"},
    )

    dataset = Dataset.objects.get(key=result["dataset"]["key"])
    assert row_result["message"] == "Row created."
    assert dataset.row_count == 51


def test_paid_account_can_create_51st_dataset_row(profile):
    profile.state = ProfileStates.SUBSCRIBED
    profile.save(update_fields=["state"])
    result = create_profile_dataset(
        profile,
        name="Paid row uncapped dataset",
        headers=["name"],
        rows=[{"name": str(index)} for index in range(50)],
    )

    row_result = create_profile_dataset_row(
        profile,
        result["dataset"]["key"],
        {"name": "51"},
    )

    dataset = Dataset.objects.get(key=result["dataset"]["key"])
    assert row_result["message"] == "Row created."
    assert dataset.row_count == 51


def test_dataset_settings_page_has_section_navigation(auth_client, profile):
    dataset = create_ready_dataset(profile)

    response = auth_client.get(dataset.get_settings_url())

    assert response.status_code == 200
    content = response.content.decode()
    assert "<title>People settings · Rowset</title>" in content
    assert 'aria-labelledby="dataset-settings-nav-heading"' in content
    for section_id in [
        "dataset-context",
        "project",
        "relationships",
        "column-types",
        "public-preview",
        "danger-zone",
    ]:
        assert f'href="#{section_id}"' in content
        assert f'id="{section_id}"' in content


def test_dataset_owner_can_update_metadata_from_settings(auth_client, profile):
    dataset = create_ready_dataset(profile)

    response = auth_client.post(
        reverse("dataset_update_metadata", args=[dataset.key]),
        {
            "description": "Human-visible task board.",
            "instructions": "Keep acceptance criteria in notes before moving to done.",
            "metadata": json.dumps({"status_order": ["todo", "doing", "done"]}),
        },
    )

    assert response.status_code == 302
    dataset.refresh_from_db()
    assert dataset.description == "Human-visible task board."
    assert dataset.instructions == "Keep acceptance criteria in notes before moving to done."
    assert dataset.metadata == {"status_order": ["todo", "doing", "done"]}
    mutation = dataset.mutations.get(mutation_type=DatasetMutationType.DATASET_METADATA_UPDATED)
    assert mutation.actor_label == "Account"
    assert mutation.metadata["changed_fields"] == ["description", "instructions", "metadata"]


def test_dataset_detail_shows_column_descriptions_on_header_hover(
    auth_client,
    profile,
):
    dataset = create_ready_dataset(profile)
    dataset.column_schema = {
        "name": {
            "type": "text",
            "description": "Human-readable full name.",
        },
        "email": {"type": "email"},
    }
    dataset.save(update_fields=["column_schema"])

    response = auth_client.get(dataset.get_absolute_url())

    assert response.status_code == 200
    content = response.content.decode()
    assert 'x-data="rowColumnMenu"' in content
    assert 'title="Human-readable full name."' in content
    assert '@click="open($event)"' in content
    assert '@contextmenu="open($event)"' in content
    assert "<dialog" in content
    assert 'aria-describedby="row-column-menu-description-0"' in content
    assert 'id="row-column-menu-description-0"' in content
    assert 'name="row_sort" value="col_0"' in content
    assert "Contains text" in content
