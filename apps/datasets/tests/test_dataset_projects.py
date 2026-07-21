import json
from datetime import timedelta

import pytest
from django.contrib import messages as message_constants
from django.contrib.messages import get_messages
from django.urls import reverse
from django.utils import timezone

from apps.api.services import serialize_dataset_detail
from apps.datasets import models as dataset_models
from apps.datasets.choices import DatasetColumnType, DatasetMutationType
from apps.datasets.models import Dataset, DatasetRow, Project
from apps.datasets.services import normalize_column_schema
from apps.datasets.tests.dataset_test_helpers import complete_agent_setup, create_ready_dataset
from apps.datasets.views import PROJECT_DETAIL_DATASET_PAGE_SIZE

pytestmark = pytest.mark.django_db


def test_home_project_sort_puts_unassigned_dataset_group_last(auth_client, profile):
    project = Project.objects.create(profile=profile, name="Research")
    Dataset.objects.create(
        profile=profile,
        name="Alpha loose dataset",
        headers=["id"],
        index_column="id",
    )
    Dataset.objects.create(
        profile=profile,
        project=project,
        name="Zulu project dataset",
        headers=["id"],
        index_column="id",
    )

    response = auth_client.get(reverse("home"), {"sort": "project", "view": "raw"})

    assert response.status_code == 200
    assert response.context["selected_view_mode"] == "grouped"
    assert [group["label"] for group in response.context["dataset_groups"]] == [
        "Research",
        "No project",
    ]
    assert [dataset.name for dataset in response.context["datasets"]] == [
        "Zulu project dataset",
        "Alpha loose dataset",
    ]


def test_dataset_list_groups_datasets_by_project(auth_client, profile):
    complete_agent_setup(profile)
    research = Project.objects.create(
        profile=profile,
        name="Research",
        description="Datasets for customer interviews.",
    )
    launch = Project.objects.create(profile=profile, name="Launch")
    people = create_ready_dataset(profile)
    people.project = research
    people.row_count = 10
    people.save(update_fields=["project", "row_count"])
    notes = Dataset.objects.create(
        profile=profile,
        project=research,
        name="Research notes",
        headers=["note_id", "body"],
        index_column="note_id",
        row_count=1,
    )
    Dataset.objects.create(
        profile=profile,
        project=launch,
        name="Launch tasks",
        headers=["task_id", "owner"],
        index_column="task_id",
        row_count=8,
    )
    Dataset.objects.create(
        profile=profile,
        name="Loose contacts",
        headers=["email"],
        index_column="email",
        row_count=4,
    )

    response = auth_client.get(reverse("home"), {"sort": "rows", "view": "grouped"})

    content = response.content.decode()
    groups = response.context["dataset_groups"]
    assert response.status_code == 200
    assert response.context["selected_view_mode"] == "grouped"
    assert [group["label"] for group in groups] == ["Launch", "Research", "No project"]
    assert [dataset.name for dataset in groups[1]["datasets"]] == ["People", notes.name]
    assert groups[1]["dataset_count"] == 2
    assert groups[1]["row_count"] == 11
    assert "Your data workspace" in content
    assert "border-l-2 border-emerald-200" not in content
    assert "No project" in content
    assert "Loose contacts" in content


def test_home_groups_project_datasets_by_section(auth_client, profile):
    project = Project.objects.create(profile=profile, name="Content")
    blog = dataset_models.ProjectSection.objects.create(
        profile=profile,
        project=project,
        name="Blog",
    )
    Dataset.objects.create(
        profile=profile,
        project=project,
        section=blog,
        name="Content ledger",
        headers=["slug"],
        index_column="slug",
    )
    Dataset.objects.create(
        profile=profile,
        project=project,
        name="Topic backlog",
        headers=["topic"],
        index_column="topic",
    )

    response = auth_client.get(reverse("home"))

    content = response.content.decode()
    group = response.context["dataset_groups"][0]
    assert response.status_code == 200
    assert group["label"] == "Content"
    assert [section_group["label"] for section_group in group["section_groups"]] == [
        "Blog",
        "Unsectioned",
    ]
    assert group["section_groups"][0]["datasets"][0].name == "Content ledger"
    assert group["section_groups"][1]["datasets"][0].name == "Topic backlog"
    assert "Blog" in content
    assert "No section" in content


def test_dataset_detail_links_project_reference_cells(auth_client, profile):
    target = Project.objects.create(
        profile=profile,
        name="Launch ops",
        description="Project referenced from a dataset cell.",
    )
    source = Dataset.objects.create(
        profile=profile,
        name="Sprint history",
        headers=["sprint_id", "owning_project"],
        column_schema={
            "sprint_id": {"type": DatasetColumnType.TEXT},
            "owning_project": {
                "type": DatasetColumnType.REFERENCE,
                "target": "project",
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
            "owning_project": str(target.key),
        },
    )

    response = auth_client.get(source.get_absolute_url())
    content = response.content.decode()

    assert response.status_code == 200
    assert f'href="{target.get_absolute_url()}"' in content
    assert "Launch ops" in content


def test_dataset_detail_renders_archived_project_reference_cells_without_dead_link(
    auth_client,
    profile,
):
    target = Project.objects.create(profile=profile, name="Archived launch ops")
    target.archived_at = timezone.now()
    target.save(update_fields=["archived_at"])
    source = Dataset.objects.create(
        profile=profile,
        name="Sprint history",
        headers=["sprint_id", "owning_project"],
        column_schema={
            "sprint_id": {"type": DatasetColumnType.TEXT},
            "owning_project": {
                "type": DatasetColumnType.REFERENCE,
                "target": "project",
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
            "owning_project": str(target.key),
        },
    )

    response = auth_client.get(source.get_absolute_url())
    content = response.content.decode()

    assert response.status_code == 200
    assert f'href="{target.get_absolute_url()}"' not in content
    assert "Archived launch ops" in content


def test_project_detail_dataset_rows_omit_status_and_actions(auth_client, profile):
    project = Project.objects.create(profile=profile, name="Launch")
    dataset = create_ready_dataset(profile)
    dataset.project = project
    dataset.save(update_fields=["project"])

    response = auth_client.get(project.get_absolute_url())

    content = response.content.decode()
    assert response.status_code == 200
    assert "Datasets by section" in content
    assert "People" in content
    assert reverse("dataset_export", args=[dataset.key, "csv"]) not in content
    assert reverse("dataset_export", args=[dataset.key, "parquet"]) not in content
    assert dataset.get_settings_url() not in content
    assert "Dataset status" not in content


def test_project_detail_links_to_settings_and_hides_project_edit_actions(auth_client, profile):
    project = Project.objects.create(
        profile=profile,
        name="Frontier",
        description="Canonical Rowset project for Frontier.",
    )

    response = auth_client.get(project.get_absolute_url())
    content = response.content.decode()

    assert response.status_code == 200
    assert "<title>Frontier · Rowset</title>" in content
    assert "Project details" not in content
    assert ">Frontier</h1>" in content
    assert "Project context" in content
    assert "Canonical Rowset project for Frontier." in content
    assert project.get_settings_url() in content
    assert "View all datasets" in content
    assert 'x-data="projectDetail"' not in content
    assert reverse("project_update", args=[project.key]) not in content
    assert reverse("project_update_metadata", args=[project.key]) not in content
    assert reverse("project_delete", args=[project.key]) not in content


def test_project_context_and_archived_datasets_are_collapsed_on_detail(auth_client, profile):
    project = Project.objects.create(
        profile=profile,
        name="Frontier",
        description="Canonical Rowset project for Frontier.",
        metadata={"owner": "ops"},
    )

    response = auth_client.get(project.get_absolute_url())
    content = response.content.decode()

    assert response.status_code == 200
    assert "<details open" not in content
    assert "Project context" in content
    assert "Archived datasets" in content
    assert response.context["metadata_json"] == '{\n  "owner": "ops"\n}'


def test_project_settings_shows_project_forms_sections_and_delete_warning(auth_client, profile):
    project = Project.objects.create(
        profile=profile,
        name="Frontier",
        description="Canonical Rowset project for Frontier.",
        metadata={"github_repo": "https://github.com/acme/frontier"},
    )
    section = dataset_models.ProjectSection.objects.create(
        profile=profile,
        project=project,
        name="Blog",
        description="Editorial datasets",
    )

    response = auth_client.get(project.get_settings_url())
    content = response.content.decode()

    assert response.status_code == 200
    assert "<title>Frontier settings · Rowset</title>" in content
    assert "Project settings" in content
    assert 'aria-labelledby="project-settings-nav-heading"' in content
    assert reverse("project_update", args=[project.key]) in content
    assert reverse("project_update_metadata", args=[project.key]) in content
    assert reverse("project_section_create", args=[project.key]) in content
    assert reverse("project_section_delete", args=[project.key, section.key]) in content
    assert reverse("project_delete", args=[project.key]) in content
    assert "Warning" in content
    assert (
        "return confirm('Delete project Frontier? Assigned datasets will stay in Rowset "
        "and become ungrouped. This cannot be undone.');"
    ) in content
    assert "Canonical Rowset project for Frontier." in content
    assert "https://github.com/acme/frontier" in content
    assert "Blog" in content


def test_home_omits_standalone_project_management(auth_client, profile):
    project = Project.objects.create(profile=profile, name="Frontier")
    dataset = create_ready_dataset(profile)
    dataset.project = project
    dataset.save(update_fields=["project"])

    response = auth_client.get(reverse("home"))
    content = response.content.decode()

    assert response.status_code == 200
    assert "Frontier" in content
    assert "projects-overview" not in content
    assert "New project" not in content
    assert reverse("project_delete", args=[project.key]) not in content


def test_project_delete_removes_owned_project_and_detaches_datasets(auth_client, profile):
    project = Project.objects.create(profile=profile, name="Launch")
    dataset = create_ready_dataset(profile)
    dataset.project = project
    dataset.save(update_fields=["project"])

    response = auth_client.post(reverse("project_delete", args=[project.key]))

    assert response.status_code == 302
    assert response.url == reverse("home")
    assert not Project.objects.filter(id=project.id).exists()
    dataset.refresh_from_db()
    assert dataset.project is None
    flash_messages = list(get_messages(response.wsgi_request))
    assert len(flash_messages) == 1
    assert flash_messages[0].level == message_constants.SUCCESS
    assert str(flash_messages[0]) == "Deleted Launch. Assigned datasets are now ungrouped."


def test_project_delete_requires_post(auth_client, profile):
    project = Project.objects.create(profile=profile, name="Launch")

    response = auth_client.get(reverse("project_delete", args=[project.key]))

    assert response.status_code == 405
    assert Project.objects.filter(id=project.id).exists()


def test_project_delete_rejects_other_users_project(client, django_user_model, profile):
    project = Project.objects.create(profile=profile, name="Launch")
    other_user = django_user_model.objects.create_user(
        username="other-project-delete",
        email="other-project-delete@example.com",
        password="password123",
    )
    client.force_login(other_user)

    response = client.post(reverse("project_delete", args=[project.key]))

    assert response.status_code == 404
    assert Project.objects.filter(id=project.id).exists()


def test_project_delete_rejects_user_without_profile(client, django_user_model, profile):
    project = Project.objects.create(profile=profile, name="Launch")
    user_without_profile = django_user_model.objects.create_user(
        username="missing-profile-project-delete",
        email="missing-profile-project-delete@example.com",
        password="password123",
    )
    user_without_profile.profile.delete()
    client.force_login(user_without_profile)

    response = client.post(reverse("project_delete", args=[project.key]))

    assert response.status_code == 404
    assert Project.objects.filter(id=project.id).exists()


def test_normalize_column_schema_accepts_project_reference_metadata():
    schema = normalize_column_schema(
        ["owning_project"],
        {
            "owning_project": {
                "type": "reference",
                "target": "project",
                "description": "Project responsible for this row.",
            }
        },
        reject_unknown=True,
    )

    assert schema == {
        "owning_project": {
            "type": "reference",
            "target": "project",
            "description": "Project responsible for this row.",
        }
    }


def test_normalize_column_schema_infers_project_reference_alias_target():
    schema = normalize_column_schema(
        ["owning_project", "fallback_project"],
        {
            "owning_project": "project_reference",
            "fallback_project": {"type": "rowset_project"},
        },
        reject_unknown=True,
    )

    assert schema == {
        "owning_project": {
            "type": "reference",
            "target": "project",
        },
        "fallback_project": {
            "type": "reference",
            "target": "project",
        },
    }


def test_dataset_api_project_reference_columns_accept_archived_projects(api_client, profile):
    target = Project.objects.create(profile=profile, name="Review Gate")
    target.archived_at = timezone.now()
    target.save(update_fields=["archived_at"])

    response = api_client.post(
        "/api/datasets",
        data={
            "name": "Review Gate Sprint History",
            "headers": ["sprint_id", "owning_project"],
            "index_column": "sprint_id",
            "column_types": {
                "owning_project": {
                    "type": "reference",
                    "target": "project",
                }
            },
            "rows": [
                {
                    "sprint_id": "RG-SPRINT-001",
                    "owning_project": str(target.key),
                }
            ],
        },
        content_type="application/json",
    )

    assert response.status_code == 201
    dataset = Dataset.objects.get(key=response.json()["dataset"]["key"], profile=profile)
    row = dataset.rows.get(index_value="RG-SPRINT-001")
    assert row.data["owning_project"] == str(target.key)

    payload = serialize_dataset_detail(dataset)
    reference = payload["project_references"]["owning_project"][str(target.key)]
    assert reference["name"] == "Review Gate"
    assert reference["archived_at"] == target.archived_at
    assert reference["dataset_count"] == 0


def test_dataset_api_project_reference_columns_reject_missing_projects(api_client, profile):
    missing_key = "38698383-f515-4b60-b426-4f4ae3bc94ce"

    response = api_client.post(
        "/api/datasets",
        data={
            "name": "Review Gate Sprint History",
            "headers": ["sprint_id", "owning_project"],
            "index_column": "sprint_id",
            "column_types": {
                "owning_project": {
                    "type": "reference",
                    "target": "project",
                }
            },
            "rows": [
                {
                    "sprint_id": "RG-SPRINT-001",
                    "owning_project": missing_key,
                }
            ],
        },
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "Column 'owning_project' references a project that does not exist or is not owned "
        "by this profile."
    )


def test_dataset_api_project_reference_columns_reject_other_profile_projects(
    api_client,
    profile,
    django_user_model,
):
    other_user = django_user_model.objects.create_user(
        username="projectreferenceother",
        email="projectreferenceother@example.com",
        password="password123",
    )
    other_project = Project.objects.create(profile=other_user.profile, name="Other launch")
    source = Dataset.objects.create(
        profile=profile,
        name="Sprint history",
        headers=["sprint_id", "owning_project"],
        column_schema={
            "sprint_id": {"type": DatasetColumnType.TEXT},
            "owning_project": {
                "type": DatasetColumnType.REFERENCE,
                "target": "project",
            },
        },
        index_column="sprint_id",
        row_count=0,
    )

    response = api_client.post(
        f"/api/datasets/{source.key}/rows",
        data={
            "data": {
                "sprint_id": "RG-SPRINT-001",
                "owning_project": str(other_project.key),
            }
        },
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "Column 'owning_project' references a project that does not exist or is not owned "
        "by this profile."
    )
    assert not source.rows.exists()


def test_dataset_api_project_reference_columns_canonicalize_row_writes(api_client, profile):
    target = Project.objects.create(profile=profile, name="Launch")
    source = Dataset.objects.create(
        profile=profile,
        name="Sprint history",
        headers=["sprint_id", "owning_project"],
        column_schema={
            "sprint_id": {"type": DatasetColumnType.TEXT},
            "owning_project": {
                "type": DatasetColumnType.REFERENCE,
                "target": "project",
            },
        },
        index_column="sprint_id",
        row_count=0,
    )

    create_response = api_client.post(
        f"/api/datasets/{source.key}/rows",
        data={
            "data": {
                "sprint_id": "RG-SPRINT-001",
                "owning_project": target.get_absolute_url(),
            }
        },
        content_type="application/json",
    )

    assert create_response.status_code == 200
    row = source.rows.get(index_value="RG-SPRINT-001")
    assert row.data["owning_project"] == str(target.key)

    invalid_patch = api_client.patch(
        f"/api/datasets/{source.key}/rows/{row.id}",
        data={"data": {"owning_project": "38698383-f515-4b60-b426-4f4ae3bc94ce"}},
        content_type="application/json",
    )

    assert invalid_patch.status_code == 400
    assert invalid_patch.json()["detail"] == (
        "Column 'owning_project' references a project that does not exist or is not owned "
        "by this profile."
    )
    row.refresh_from_db()
    assert row.data["owning_project"] == str(target.key)


def test_dataset_api_project_reference_index_canonicalizes_row_writes(api_client, profile):
    target = Project.objects.create(profile=profile, name="Launch")
    source = Dataset.objects.create(
        profile=profile,
        name="Sprint history",
        headers=["owning_project", "sprint_id"],
        column_schema={
            "owning_project": {
                "type": DatasetColumnType.REFERENCE,
                "target": "project",
            },
            "sprint_id": {"type": DatasetColumnType.TEXT},
        },
        index_column="owning_project",
        row_count=0,
    )

    response = api_client.post(
        f"/api/datasets/{source.key}/rows",
        data={
            "data": {
                "owning_project": target.get_absolute_url(),
                "sprint_id": "RG-SPRINT-001",
            }
        },
        content_type="application/json",
    )

    assert response.status_code == 200
    row = source.rows.get()
    assert row.index_value == str(target.key)
    assert row.data["owning_project"] == str(target.key)


def test_project_api_creates_lists_and_returns_project_datasets(api_client, profile):
    create_project_response = api_client.post(
        "/api/projects",
        data={
            "name": "Launch",
            "description": "Launch datasets",
            "metadata": {
                "github_repo": "https://github.com/acme/launch",
                "source_thread": {
                    "url": "https://acme.slack.com/archives/C123/p456",
                },
            },
        },
        content_type="application/json",
    )

    assert create_project_response.status_code == 201
    project_key = create_project_response.json()["project"]["key"]
    assert create_project_response.json()["project"]["metadata"] == {
        "github_repo": "https://github.com/acme/launch",
        "source_thread": {
            "url": "https://acme.slack.com/archives/C123/p456",
        },
    }

    create_dataset_response = api_client.post(
        "/api/datasets",
        data={
            "name": "Launch contacts",
            "project_key": project_key,
            "headers": ["email", "name"],
            "index_column": "email",
            "rows": [{"email": "ada@example.com", "name": "Ada"}],
        },
        content_type="application/json",
    )

    assert create_dataset_response.status_code == 201
    assert create_dataset_response.json()["dataset"]["project"]["key"] == project_key
    project = Project.objects.get(key=project_key, profile=profile)
    Dataset.objects.create(
        profile=profile,
        project=project,
        name="Draft upload",
        headers=["email", "name"],
        index_column="email",
    )

    list_response = api_client.get("/api/projects")
    assert list_response.status_code == 200
    assert list_response.json()["projects"][0]["dataset_count"] == 2
    assert list_response.json()["projects"][0]["metadata"]["github_repo"] == (
        "https://github.com/acme/launch"
    )

    detail_response = api_client.get(f"/api/projects/{project_key}")
    assert detail_response.status_code == 200
    assert detail_response.json()["project"]["name"] == "Launch"
    assert detail_response.json()["project"]["metadata"]["source_thread"]["url"] == (
        "https://acme.slack.com/archives/C123/p456"
    )
    assert detail_response.json()["datasets"]["count"] == 2
    assert detail_response.json()["datasets"]["total_count"] == 2
    assert [dataset["name"] for dataset in detail_response.json()["datasets"]["datasets"]] == [
        "Draft upload",
        "Launch contacts",
    ]
    project_dataset = detail_response.json()["datasets"]["datasets"][0]
    assert {
        "instructions",
        "metadata",
        "headers",
        "column_schema",
        "index_column",
        "public_enabled",
        "public_key",
    } <= set(project_dataset)


def test_project_api_updates_project_details(api_client, profile):
    project = Project.objects.create(
        profile=profile,
        name="Launch",
        description="Launch datasets",
    )

    response = api_client.patch(
        f"/api/projects/{project.key}",
        data={"name": "Launch operations", "description": ""},
        content_type="application/json",
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["message"] == "Project updated."
    assert payload["project"]["name"] == "Launch operations"
    assert payload["project"]["description"] == ""
    project.refresh_from_db()
    assert project.name == "Launch operations"
    assert project.description == ""


def test_project_api_archives_project_and_hides_it_from_project_endpoints(api_client, profile):
    project = Project.objects.create(
        profile=profile,
        name="Launch",
        description="Launch datasets",
    )
    dataset = Dataset.objects.create(
        profile=profile,
        project=project,
        name="Launch contacts",
        headers=["email", "name"],
        index_column="email",
    )

    response = api_client.delete(f"/api/projects/{project.key}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["message"] == "Project archived."
    assert payload["project"]["key"] == str(project.key)
    assert payload["project"]["archived_at"] is not None
    project.refresh_from_db()
    assert project.archived_at is not None
    dataset.refresh_from_db()
    assert dataset.archived_at is None
    assert dataset.project == project

    list_response = api_client.get("/api/projects")
    assert list_response.status_code == 200
    assert list_response.json()["projects"] == []

    search_response = api_client.get("/api/projects?query=Launch")
    assert search_response.status_code == 200
    assert search_response.json()["projects"] == []

    detail_response = api_client.get(f"/api/projects/{project.key}")
    assert detail_response.status_code == 404
    assert detail_response.json()["detail"] == "Project not found."

    dataset_list_response = api_client.get("/api/datasets")
    assert dataset_list_response.status_code == 200
    assert dataset_list_response.json()["datasets"][0]["key"] == str(dataset.key)
    assert dataset_list_response.json()["datasets"][0]["project"] is None

    duplicate_name_response = api_client.post(
        "/api/projects",
        data={"name": "Launch"},
        content_type="application/json",
    )
    assert duplicate_name_response.status_code == 201


def test_project_api_rejects_null_project_name(api_client, profile):
    project = Project.objects.create(
        profile=profile,
        name="Launch",
        description="Launch datasets",
    )

    response = api_client.patch(
        f"/api/projects/{project.key}",
        data={"name": None},
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "Project name cannot be null. Omit it to leave the current value unchanged."
    )
    project.refresh_from_db()
    assert project.name == "Launch"


def test_project_api_rejects_blank_project_name_at_schema_boundary(api_client, profile):
    project = Project.objects.create(
        profile=profile,
        name="Launch",
        description="Launch datasets",
    )

    response = api_client.patch(
        f"/api/projects/{project.key}",
        data={"name": ""},
        content_type="application/json",
    )

    assert response.status_code == 422
    project.refresh_from_db()
    assert project.name == "Launch"


def test_project_api_rejects_case_insensitive_duplicate_names(api_client, profile):
    Project.objects.create(profile=profile, name="Launch")

    response = api_client.post(
        "/api/projects",
        data={"name": "launch"},
        content_type="application/json",
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Project name already exists."
    assert Project.objects.filter(profile=profile).count() == 1


def test_project_api_updates_project_metadata(api_client, profile):
    project = Project.objects.create(
        profile=profile,
        name="Launch",
        metadata={"github_repo": "https://github.com/acme/old"},
    )

    response = api_client.patch(
        f"/api/projects/{project.key}/metadata",
        data={
            "metadata": {
                "github_repo": "https://github.com/acme/launch",
                "notion_doc": "https://notion.so/acme/launch",
            }
        },
        content_type="application/json",
    )

    assert response.status_code == 200
    assert response.json()["message"] == "Project metadata updated."
    assert response.json()["project"]["metadata"] == {
        "github_repo": "https://github.com/acme/launch",
        "notion_doc": "https://notion.so/acme/launch",
    }
    project.refresh_from_db()
    assert project.metadata == {
        "github_repo": "https://github.com/acme/launch",
        "notion_doc": "https://notion.so/acme/launch",
    }


def test_project_api_rejects_non_object_project_metadata(api_client, profile):
    project = Project.objects.create(profile=profile, name="Launch")

    response = api_client.patch(
        f"/api/projects/{project.key}/metadata",
        data={"metadata": ["not", "an", "object"]},
        content_type="application/json",
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "payload", "metadata"]
    project.refresh_from_db()
    assert project.metadata == {}


def test_project_api_rejects_null_project_metadata(api_client, profile):
    project = Project.objects.create(profile=profile, name="Launch")

    response = api_client.patch(
        f"/api/projects/{project.key}/metadata",
        data={"metadata": None},
        content_type="application/json",
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "payload", "metadata"]
    project.refresh_from_db()
    assert project.metadata == {}


def test_dataset_api_updates_project_assignment(api_client, profile):
    project = Project.objects.create(profile=profile, name="Customers")
    dataset = create_ready_dataset(profile)

    attach_response = api_client.patch(
        f"/api/datasets/{dataset.key}/project",
        data={"project_key": str(project.key)},
        content_type="application/json",
    )

    assert attach_response.status_code == 200
    assert attach_response.json()["dataset"]["project"]["key"] == str(project.key)
    dataset.refresh_from_db()
    assert dataset.project == project

    detach_response = api_client.patch(
        f"/api/datasets/{dataset.key}/project",
        data={"project_key": None},
        content_type="application/json",
    )

    assert detach_response.status_code == 200
    assert detach_response.json()["dataset"]["project"] is None
    dataset.refresh_from_db()
    assert dataset.project is None


def test_project_section_api_creates_section_and_assigns_dataset(api_client, profile):
    assert hasattr(dataset_models, "ProjectSection")
    project = Project.objects.create(profile=profile, name="Rowset")

    section_response = api_client.post(
        f"/api/projects/{project.key}/sections",
        data={
            "name": "Blog",
            "description": "Content operations datasets.",
            "metadata": {"goal": "content-led growth"},
        },
        content_type="application/json",
    )

    assert section_response.status_code == 201
    section_payload = section_response.json()["section"]
    assert section_payload["name"] == "Blog"
    assert section_payload["description"] == "Content operations datasets."
    assert section_payload["metadata"] == {"goal": "content-led growth"}
    assert section_payload["dataset_count"] == 0

    dataset_response = api_client.post(
        "/api/datasets",
        data={
            "name": "Content ledger",
            "headers": ["slug", "status"],
            "rows": [{"slug": "launch-post", "status": "draft"}],
            "index_column": "slug",
            "project_key": str(project.key),
            "section_key": section_payload["key"],
        },
        content_type="application/json",
    )

    assert dataset_response.status_code == 201
    dataset_payload = dataset_response.json()["dataset"]
    assert dataset_payload["project"]["key"] == str(project.key)
    assert dataset_payload["section"]["key"] == section_payload["key"]
    assert dataset_payload["section"]["name"] == "Blog"

    detail_response = api_client.get(f"/api/projects/{project.key}")

    assert detail_response.status_code == 200
    detail_payload = detail_response.json()
    assert "sections" not in detail_payload
    assert "dataset_groups" not in detail_payload
    assert detail_payload["datasets"]["datasets"][0]["key"] == dataset_payload["key"]

    sections_response = api_client.get(f"/api/projects/{project.key}/sections")

    assert sections_response.status_code == 200
    sections_payload = sections_response.json()
    assert sections_payload["count"] == 1
    assert sections_payload["total_count"] == 1
    assert sections_payload["sections"][0]["key"] == section_payload["key"]
    assert sections_payload["sections"][0]["dataset_count"] == 1


def test_dataset_api_rejects_section_from_another_project(api_client, profile):
    assert hasattr(dataset_models, "ProjectSection")
    ProjectSection = dataset_models.ProjectSection
    project = Project.objects.create(profile=profile, name="Rowset")
    other_project = Project.objects.create(profile=profile, name="Other")
    section = ProjectSection.objects.create(
        profile=profile,
        project=other_project,
        name="Blog",
    )
    dataset = create_ready_dataset(profile)

    response = api_client.patch(
        f"/api/datasets/{dataset.key}/project",
        data={"project_key": str(project.key), "section_key": str(section.key)},
        content_type="application/json",
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Project section not found."
    dataset.refresh_from_db()
    assert dataset.project is None
    assert dataset.section is None


def test_project_section_api_archives_section_and_unsections_datasets(api_client, profile):
    assert hasattr(dataset_models, "ProjectSection")
    ProjectSection = dataset_models.ProjectSection
    project = Project.objects.create(profile=profile, name="Rowset")
    section = ProjectSection.objects.create(profile=profile, project=project, name="Blog")
    dataset = create_ready_dataset(profile)
    dataset.project = project
    dataset.section = section
    dataset.save(update_fields=["project", "section"])

    response = api_client.delete(f"/api/projects/{project.key}/sections/{section.key}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["message"] == "Project section archived."
    assert payload["section"]["key"] == str(section.key)
    assert payload["section"]["archived_at"] is not None
    section.refresh_from_db()
    assert section.archived_at is not None
    dataset.refresh_from_db()
    assert dataset.project == project
    assert dataset.section is None

    list_response = api_client.get(f"/api/projects/{project.key}/sections")

    assert list_response.status_code == 200
    assert list_response.json()["sections"] == []


def test_project_detail_api_reports_dataset_total_count_on_paginated_page(api_client, profile):
    project = Project.objects.create(profile=profile, name="Rowset")
    first = create_ready_dataset(profile)
    first.name = "Signals"
    first.project = project
    first.save(update_fields=["name", "project"])
    second = create_ready_dataset(profile)
    second.name = "Inventory"
    second.project = project
    second.save(update_fields=["name", "project"])

    response = api_client.get(f"/api/projects/{project.key}?limit=1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["datasets"]["count"] == 1
    assert payload["datasets"]["total_count"] == 2
    assert payload["datasets"]["limit"] == 1
    assert payload["datasets"]["offset"] == 0
    assert payload["datasets"]["has_more"] is True
    assert payload["datasets"]["datasets"][0]["key"] == str(second.key)
    assert "dataset_groups" not in payload


def test_project_detail_api_omits_section_groups_from_dataset_page(api_client, profile):
    assert hasattr(dataset_models, "ProjectSection")
    ProjectSection = dataset_models.ProjectSection
    project = Project.objects.create(profile=profile, name="Rowset")
    blog = ProjectSection.objects.create(profile=profile, project=project, name="Blog")
    first = create_ready_dataset(profile)
    first.name = "Signals"
    first.project = project
    first.save(update_fields=["name", "project"])
    second = create_ready_dataset(profile)
    second.name = "Inventory"
    second.project = project
    second.save(update_fields=["name", "project"])
    sectioned = create_ready_dataset(profile)
    sectioned.name = "Content ledger"
    sectioned.project = project
    sectioned.section = blog
    sectioned.save(update_fields=["name", "project", "section"])

    response = api_client.get(f"/api/projects/{project.key}?limit=1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["datasets"]["count"] == 1
    assert payload["datasets"]["datasets"][0]["key"] == str(sectioned.key)
    assert "sections" not in payload
    assert "dataset_groups" not in payload


def test_dataset_api_rejects_invalid_project_assignment_dataset_key(api_client, profile):
    project = Project.objects.create(profile=profile, name="Customers")

    response = api_client.patch(
        "/api/datasets/not-a-uuid/project",
        data={"project_key": str(project.key)},
        content_type="application/json",
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Dataset not found."


def test_dataset_api_rejects_other_users_project_assignment(api_client, django_user_model, profile):
    dataset = create_ready_dataset(profile)
    other_user = django_user_model.objects.create_user(
        username="project-owner",
        email="project-owner@example.com",
        password="password123",
    )
    other_project = Project.objects.create(profile=other_user.profile, name="Other")

    response = api_client.patch(
        f"/api/datasets/{dataset.key}/project",
        data={"project_key": str(other_project.key)},
        content_type="application/json",
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Project not found."
    dataset.refresh_from_db()
    assert dataset.project is None


def test_dataset_api_updates_column_types_to_project_reference(api_client, profile):
    target = Project.objects.create(profile=profile, name="Launch")
    dataset = Dataset.objects.create(
        profile=profile,
        name="Sprint history",
        headers=["sprint_id", "owning_project"],
        column_schema={
            "sprint_id": {"type": DatasetColumnType.TEXT},
            "owning_project": {"type": DatasetColumnType.TEXT},
        },
        index_column="sprint_id",
        row_count=1,
    )
    DatasetRow.objects.create(
        dataset=dataset,
        row_number=1,
        index_value="RG-SPRINT-001",
        data={
            "sprint_id": "RG-SPRINT-001",
            "owning_project": str(target.key),
        },
    )

    response = api_client.patch(
        f"/api/datasets/{dataset.key}/column-types",
        data={
            "column_types": {
                "owning_project": {
                    "type": "reference",
                    "target": "project",
                }
            }
        },
        content_type="application/json",
    )

    assert response.status_code == 200
    assert response.json()["dataset"]["column_schema"]["owning_project"] == {
        "type": "reference",
        "target": "project",
    }
    dataset.refresh_from_db()
    assert dataset.column_schema["owning_project"] == {
        "type": "reference",
        "target": "project",
    }


def test_dataset_api_rejects_project_reference_column_type_for_other_profile_value(
    api_client,
    profile,
    django_user_model,
):
    other_user = django_user_model.objects.create_user(
        username="projecttypeother",
        email="projecttypeother@example.com",
        password="password123",
    )
    other_project = Project.objects.create(profile=other_user.profile, name="Other launch")
    dataset = Dataset.objects.create(
        profile=profile,
        name="Sprint history",
        headers=["sprint_id", "owning_project"],
        column_schema={
            "sprint_id": {"type": DatasetColumnType.TEXT},
            "owning_project": {"type": DatasetColumnType.TEXT},
        },
        index_column="sprint_id",
        row_count=1,
    )
    DatasetRow.objects.create(
        dataset=dataset,
        row_number=1,
        index_value="RG-SPRINT-001",
        data={
            "sprint_id": "RG-SPRINT-001",
            "owning_project": str(other_project.key),
        },
    )

    response = api_client.patch(
        f"/api/datasets/{dataset.key}/column-types",
        data={
            "column_types": {
                "owning_project": {
                    "type": "reference",
                    "target": "project",
                }
            }
        },
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "Column 'owning_project' references a project that does not exist or is not owned "
        "by this profile."
    )
    dataset.refresh_from_db()
    assert dataset.column_schema["owning_project"] == {"type": DatasetColumnType.TEXT}


def test_dataset_owner_can_create_project(auth_client, profile):
    response = auth_client.post(
        reverse("project_create"),
        {
            "name": "Launch",
            "description": "Launch datasets",
            "metadata": json.dumps({"github_repo": "https://github.com/acme/launch"}),
        },
    )

    project = Project.objects.get(profile=profile, name="Launch")
    assert response.status_code == 302
    assert response.url == project.get_absolute_url()
    assert project.description == "Launch datasets"
    assert project.metadata == {"github_repo": "https://github.com/acme/launch"}


def test_project_owner_can_update_metadata_from_settings(auth_client, profile):
    project = Project.objects.create(
        profile=profile,
        name="Launch",
        metadata={"github_repo": "https://github.com/acme/old"},
    )

    response = auth_client.post(
        reverse("project_update_metadata", args=[project.key]),
        {
            "metadata": json.dumps(
                {
                    "github_repo": "https://github.com/acme/launch",
                    "slack_thread": "https://acme.slack.com/archives/C123/p456",
                }
            )
        },
    )

    assert response.status_code == 302
    assert response.url == project.get_settings_url()
    project.refresh_from_db()
    assert project.metadata == {
        "github_repo": "https://github.com/acme/launch",
        "slack_thread": "https://acme.slack.com/archives/C123/p456",
    }


def test_dataset_owner_can_update_project_details(auth_client, profile):
    project = Project.objects.create(
        profile=profile,
        name="Launch",
        description="Launch datasets",
    )

    response = auth_client.post(
        reverse("project_update", args=[project.key]),
        {"name": "Launch operations", "description": ""},
    )

    assert response.status_code == 302
    assert response.url == project.get_settings_url()
    project.refresh_from_db()
    assert project.name == "Launch operations"
    assert project.description == ""


def test_project_update_preserves_description_when_post_omits_field(auth_client, profile):
    project = Project.objects.create(
        profile=profile,
        name="Launch",
        description="Launch datasets",
    )

    response = auth_client.post(
        reverse("project_update", args=[project.key]),
        {"name": "Launch operations"},
    )

    assert response.status_code == 302
    assert response.url == project.get_settings_url()
    project.refresh_from_db()
    assert project.name == "Launch operations"
    assert project.description == "Launch datasets"


def test_project_update_rejects_other_users_project(client, django_user_model, profile):
    other_user = django_user_model.objects.create_user(
        username="other-project-owner",
        email="other-project-owner@example.com",
        password="password123",
    )
    project = Project.objects.create(profile=other_user.profile, name="Other")
    client.force_login(profile.user)

    response = client.post(
        reverse("project_update", args=[project.key]),
        {"name": "Stolen", "description": "Nope"},
    )

    assert response.status_code == 404
    project.refresh_from_db()
    assert project.name == "Other"


def test_project_detail_rejects_project_update_post(auth_client, profile):
    project = Project.objects.create(
        profile=profile,
        name="Launch",
        description="Launch datasets",
    )

    response = auth_client.post(
        project.get_absolute_url(),
        {"name": " Frontier ", "description": " Updated plan "},
    )

    assert response.status_code == 405
    project.refresh_from_db()
    assert project.name == "Launch"
    assert project.description == "Launch datasets"


def test_project_update_rejects_duplicate_project_name_from_settings(auth_client, profile):
    project = Project.objects.create(
        profile=profile,
        name="Launch",
        description="Launch datasets",
    )
    Project.objects.create(profile=profile, name="Frontier")

    response = auth_client.post(
        reverse("project_update", args=[project.key]),
        {"name": "frontier", "description": "Updated plan"},
    )

    assert response.status_code == 302
    assert response.url == project.get_settings_url()
    flash_messages = list(get_messages(response.wsgi_request))
    assert len(flash_messages) == 1
    assert flash_messages[0].level == message_constants.ERROR
    assert str(flash_messages[0]) == "Project name already exists."
    project.refresh_from_db()
    assert project.name == "Launch"
    assert project.description == "Launch datasets"


def test_project_detail_update_post_does_not_expose_other_users_project(
    client,
    django_user_model,
    profile,
):
    project = Project.objects.create(
        profile=profile,
        name="Launch",
        description="Launch datasets",
    )
    other_user = django_user_model.objects.create_user(
        username="projectother",
        email="projectother@example.com",
        password="password123",
    )
    client.force_login(other_user)

    response = client.post(
        project.get_absolute_url(),
        {"name": "Frontier", "description": "Updated plan"},
    )

    assert response.status_code == 405
    project.refresh_from_db()
    assert project.name == "Launch"
    assert project.description == "Launch datasets"


def test_project_update_raises_not_found_for_service_404(
    auth_client,
    monkeypatch,
    profile,
):
    from apps.api.services import DatasetServiceError

    project = Project.objects.create(
        profile=profile,
        name="Launch",
        description="Launch datasets",
    )

    def raise_not_found(*args, **kwargs):
        raise DatasetServiceError(404, "Project not found.")

    monkeypatch.setattr("apps.datasets.views.update_profile_project", raise_not_found)

    response = auth_client.post(
        reverse("project_update", args=[project.key]),
        {"name": "Launch operations", "description": "Updated plan"},
    )

    assert response.status_code == 404
    project.refresh_from_db()
    assert project.name == "Launch"
    assert project.description == "Launch datasets"


def test_project_detail_paginates_assigned_datasets(auth_client, profile):
    project = Project.objects.create(profile=profile, name="Large project")
    for index in range(101):
        Dataset.objects.create(
            profile=profile,
            project=project,
            name=f"Project dataset {index:03}",
            headers=["email"],
            index_column="email",
            row_count=0,
        )
    Dataset.objects.create(
        profile=profile,
        project=project,
        name="Draft upload",
        headers=["email"],
        index_column="email",
    )

    response = auth_client.get(f"{project.get_absolute_url()}?archived_page=2")
    content = response.content.decode()

    assert response.status_code == 200
    assert len(response.context["datasets"]) == 100
    assert "102 datasets" in content
    assert "Draft upload" in content
    assert "Page 1 of 2" in content
    assert "archived_page=2&amp;page=2" in content

    page_two = auth_client.get(f"{project.get_absolute_url()}?page=2")

    assert page_two.status_code == 200
    assert len(page_two.context["datasets"]) == 2
    assert "Page 2 of 2" in page_two.content.decode()


def test_project_detail_groups_datasets_by_section(auth_client, profile):
    assert hasattr(dataset_models, "ProjectSection")
    ProjectSection = dataset_models.ProjectSection
    project = Project.objects.create(profile=profile, name="Rowset")
    blog = ProjectSection.objects.create(profile=profile, project=project, name="Blog")
    Dataset.objects.create(
        profile=profile,
        project=project,
        section=blog,
        name="Content ledger",
        headers=["slug"],
        index_column="slug",
    )
    Dataset.objects.create(
        profile=profile,
        project=project,
        name="Backlog",
        headers=["signal"],
        index_column="signal",
    )
    Dataset.objects.create(
        profile=profile,
        project=project,
        name="Signals",
        headers=["signal"],
        index_column="signal",
    )

    response = auth_client.get(project.get_absolute_url())
    content = response.content.decode()

    assert response.status_code == 200
    assert response.context["section_groups"][0]["label"] == "Blog"
    assert response.context["section_groups"][0]["datasets"][0].name == "Content ledger"
    assert response.context["section_groups"][1]["label"] == "Unsectioned"
    assert response.context["section_groups"][1]["dataset_count"] == 2
    assert len(response.context["section_groups"][1]["datasets"]) == 2
    assert response.context["section_groups"][1]["datasets"][0].name == "Signals"
    assert "Blog" in content
    assert "Unsectioned" in content


def test_project_detail_groups_archived_datasets_by_section_in_collapsed_block(
    auth_client,
    profile,
):
    assert hasattr(dataset_models, "ProjectSection")
    ProjectSection = dataset_models.ProjectSection
    project = Project.objects.create(profile=profile, name="Rowset")
    blog = ProjectSection.objects.create(profile=profile, project=project, name="Blog")
    sectioned = create_ready_dataset(profile)
    sectioned.name = "Archived content ledger"
    sectioned.project = project
    sectioned.section = blog
    sectioned.archived_at = timezone.now()
    sectioned.save(update_fields=["name", "project", "section", "archived_at"])
    unsectioned = create_ready_dataset(profile)
    unsectioned.name = "Archived backlog"
    unsectioned.project = project
    unsectioned.archived_at = timezone.now()
    unsectioned.save(update_fields=["name", "project", "archived_at"])

    response = auth_client.get(project.get_absolute_url())
    content = response.content.decode()

    assert response.status_code == 200
    assert "<details open" not in content
    assert response.context["archived_section_groups"][0]["label"] == "Blog"
    assert response.context["archived_section_groups"][0]["datasets"][0].name == (
        "Archived content ledger"
    )
    assert response.context["archived_section_groups"][1]["label"] == "Unsectioned"
    assert response.context["archived_section_groups"][1]["datasets"][0].name == (
        "Archived backlog"
    )
    assert "Archived datasets" in content
    assert "Archived content ledger" in content
    assert "Archived backlog" in content


def test_project_detail_paginates_archived_datasets(auth_client, profile):
    project = Project.objects.create(profile=profile, name="Rowset")
    archived_at = timezone.now()
    total_archived = PROJECT_DETAIL_DATASET_PAGE_SIZE + 1
    for index in range(total_archived):
        Dataset.objects.create(
            profile=profile,
            project=project,
            name=f"Archived dataset {index:03d}",
            headers=["slug"],
            index_column="slug",
            archived_at=archived_at - timedelta(minutes=index),
        )

    response = auth_client.get(project.get_absolute_url())
    content = response.content.decode()

    assert response.status_code == 200
    assert response.context["archived_page_obj"].paginator.count == total_archived
    assert len(response.context["archived_datasets"]) == PROJECT_DETAIL_DATASET_PAGE_SIZE
    assert "Archived dataset 000" in content
    assert "Archived dataset 099" in content
    assert "Archived dataset 100" not in content
    assert "archived_page=2#archived-datasets" in content

    second_page_response = auth_client.get(f"{project.get_absolute_url()}?archived_page=2")
    second_page_content = second_page_response.content.decode()

    assert second_page_response.status_code == 200
    assert len(second_page_response.context["archived_datasets"]) == 1
    assert "Archived dataset 100" in second_page_content
    assert '<details id="archived-datasets"' in second_page_content
    assert "open" in second_page_content


def test_dataset_owner_can_assign_project_from_settings(auth_client, profile):
    dataset = create_ready_dataset(profile)
    project = Project.objects.create(profile=profile, name="Customer work")

    response = auth_client.post(
        reverse("dataset_update_project", args=[dataset.key]),
        {"project_key": str(project.key)},
    )

    assert response.status_code == 302
    dataset.refresh_from_db()
    assert dataset.project == project
    mutation = dataset.mutations.get(mutation_type=DatasetMutationType.DATASET_PROJECT_UPDATED)
    assert mutation.actor_label == "Account"
    assert mutation.metadata["project_name"] == "Customer work"

    detach_response = auth_client.post(
        reverse("dataset_update_project", args=[dataset.key]),
        {"project_key": ""},
    )

    assert detach_response.status_code == 302
    dataset.refresh_from_db()
    assert dataset.project is None


def test_dataset_owner_can_assign_project_section_from_settings(auth_client, profile):
    assert hasattr(dataset_models, "ProjectSection")
    ProjectSection = dataset_models.ProjectSection
    dataset = create_ready_dataset(profile)
    project = Project.objects.create(profile=profile, name="Rowset")
    section = ProjectSection.objects.create(profile=profile, project=project, name="Blog")

    response = auth_client.post(
        reverse("dataset_update_project", args=[dataset.key]),
        {"project_key": str(project.key), "section_key": str(section.key)},
    )

    assert response.status_code == 302
    dataset.refresh_from_db()
    assert dataset.project == project
    assert dataset.section == section
    mutation = dataset.mutations.get(mutation_type=DatasetMutationType.DATASET_PROJECT_UPDATED)
    assert mutation.metadata["section_name"] == "Blog"


def test_dataset_project_settings_rejects_mismatched_section_with_message(auth_client, profile):
    assert hasattr(dataset_models, "ProjectSection")
    ProjectSection = dataset_models.ProjectSection
    dataset = create_ready_dataset(profile)
    project = Project.objects.create(profile=profile, name="Rowset")
    other_project = Project.objects.create(profile=profile, name="Other")
    section = ProjectSection.objects.create(profile=profile, project=other_project, name="Blog")

    response = auth_client.post(
        reverse("dataset_update_project", args=[dataset.key]),
        {"project_key": str(project.key), "section_key": str(section.key)},
    )

    assert response.status_code == 302
    assert response.url == dataset.get_settings_url()
    dataset.refresh_from_db()
    assert dataset.project is None
    assert dataset.section is None
    flash_messages = list(get_messages(response.wsgi_request))
    assert len(flash_messages) == 1
    assert flash_messages[0].level == message_constants.ERROR
    assert str(flash_messages[0]) == "Project section not found."


def test_dataset_project_settings_marks_section_options_by_project(auth_client, profile):
    assert hasattr(dataset_models, "ProjectSection")
    ProjectSection = dataset_models.ProjectSection
    dataset = create_ready_dataset(profile)
    rowset_project = Project.objects.create(profile=profile, name="Rowset")
    other_project = Project.objects.create(profile=profile, name="Other")
    rowset_section = ProjectSection.objects.create(
        profile=profile,
        project=rowset_project,
        name="Blog",
    )
    other_section = ProjectSection.objects.create(
        profile=profile,
        project=other_project,
        name="Sales",
    )

    response = auth_client.get(dataset.get_settings_url())
    content = response.content.decode()

    assert response.status_code == 200
    assert 'x-data="datasetProject"' in content
    assert 'x-ref="projectSelect"' in content
    assert '@change="syncSections()"' in content
    assert 'x-ref="sectionSelect"' in content
    assert f'value="{rowset_section.key}"' in content
    assert f'data-project-key="{rowset_project.key}"' in content
    assert "Rowset / Blog" in content
    assert f'value="{other_section.key}"' in content
    assert f'data-project-key="{other_project.key}"' in content
    assert "Other / Sales" in content
