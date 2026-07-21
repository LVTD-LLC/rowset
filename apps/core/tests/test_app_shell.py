import re

import pytest

from apps.datasets.models import Dataset, Project, ProjectSection

pytestmark = pytest.mark.django_db


def test_authenticated_app_shell_renders_workspace_tree_and_utility_navigation(
    auth_client,
    profile,
):
    project = Project.objects.create(profile=profile, name="Product launch")
    section = ProjectSection.objects.create(
        profile=profile,
        project=project,
        name="Sales",
    )
    dataset = Dataset.objects.create(
        profile=profile,
        project=project,
        section=section,
        name="Pipeline",
        headers=["rowset_id", "company"],
        index_column="rowset_id",
        index_generated=True,
    )

    response = auth_client.get("/settings")

    assert response.status_code == 200
    content = response.content.decode()
    assert 'data-app-shell="sidebar"' in content
    assert 'aria-label="Workspace navigation"' in content
    assert f'href="{project.get_absolute_url()}"' in content
    assert content.count(f'href="{project.get_settings_url()}"') == 2
    assert content.count('aria-label="Settings for Product launch"') == 2
    assert f'href="{dataset.get_absolute_url()}"' in content
    assert "Product launch" in content
    assert "Sales" in content
    assert "Pipeline" in content
    assert ">Docs<" in content
    assert ">Blog<" in content
    assert ">Settings<" in content
    assert 'aria-controls="app-mobile-sidebar"' in content
    assert "data-sidebar-filter" in content
    assert 'aria-keyshortcuts="/"' in content
    assert "data-sidebar-resize-handle" in content
    assert f'data-sidebar-disclosure-key="project:{project.key}"' in content
    assert f'data-sidebar-disclosure-key="section:{section.key}"' in content
    assert content.count('@toggle="rememberSidebarDisclosure($event)"') >= 4
    assert 'window.Rowset.sidebarPreferences = sidebarPreferences' in content
    assert '"--app-sidebar-width"' in content
    assert '"rowset-sidebar-collapsed"' in content
    assert "document.currentScript.parentElement" in content
    assert 'aria-label="Collapse sidebar"' in content
    assert 'aria-keyshortcuts="Meta+B Control+B"' in content
    assert "data-command-palette-trigger" in content
    assert "Search everything" in content
    assert "lg:grid-cols-[var(--app-sidebar-width,18rem)_minmax(0,1fr)]" in content
    assert content.count('@click="toggleTheme"') == 2
    assert content.count(':aria-label="themeToggleLabel"') == 2
    assert 'localStorage.getItem("theme")' in content
    assert "site_header.html" not in content
    assert "ui-picker.js" not in content
    assert "data-uidotsh-pick" not in content


def test_authenticated_app_shell_omits_archived_workspace_items(auth_client, profile):
    archived_project = Project.objects.create(
        profile=profile,
        name="Archived project",
        archived_at="2026-01-01T00:00:00Z",
    )
    Dataset.objects.create(
        profile=profile,
        project=archived_project,
        name="Archived dataset",
        archived_at="2026-01-01T00:00:00Z",
    )

    response = auth_client.get("/home")

    content = response.content.decode()
    assert "Archived project" not in content
    assert "Archived dataset" not in content


def test_authenticated_app_shell_expands_the_project_for_a_dataset_deep_link(
    auth_client,
    profile,
):
    Project.objects.create(profile=profile, name="Alpha")
    project = Project.objects.create(profile=profile, name="Beta")
    section = ProjectSection.objects.create(profile=profile, project=project, name="Sales")
    dataset = Dataset.objects.create(
        profile=profile,
        project=project,
        section=section,
        name="Pipeline",
    )

    response = auth_client.get(dataset.get_absolute_url())

    content = response.content.decode()
    assert re.search(r'<details[^>]*data-navigation-project="Beta"[^>]*\sopen(?:\s|>)', content)
    assert re.search(r'<details[^>]*data-navigation-section="Sales"[^>]*\sopen(?:\s|>)', content)
