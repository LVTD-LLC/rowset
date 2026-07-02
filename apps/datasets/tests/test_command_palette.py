from django.urls import reverse

from apps.api.services import DatasetServiceError
from apps.datasets.choices import DatasetStatus
from apps.datasets.tests.factories import create_dataset, create_project, create_test_user


def test_command_palette_search_requires_login(client):
    response = client.get(reverse("command_palette_search"))

    assert response.status_code == 302
    assert response["Location"].startswith("/accounts/login/")


def test_authenticated_app_shell_includes_command_palette(auth_client):
    response = auth_client.get(reverse("home"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "data-command-palette-trigger" in content
    assert 'id="command-palette-query"' in content
    assert reverse("command_palette_search") in content


def test_command_palette_search_waits_for_meaningful_query(auth_client, monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("Search services should not run for short palette queries.")

    monkeypatch.setattr("apps.datasets.views.search_profile_datasets", fail_if_called)
    monkeypatch.setattr("apps.datasets.views.search_profile_projects", fail_if_called)
    monkeypatch.setattr("apps.datasets.views.search_profile_rows", fail_if_called)

    response = auth_client.get(reverse("command_palette_search"), {"q": "a"})

    assert response.status_code == 200
    content = response.content.decode()
    assert "Keep typing" in content
    assert "Search starts after 2 characters" in content


def test_command_palette_search_returns_dataset_project_and_row_results(
    auth_client,
    django_user_model,
    monkeypatch,
    profile,
):
    project = create_project(profile, name="Ada Ops", description="Project for Ada research")
    dataset = create_dataset(
        profile,
        name="Ada Research",
        project=project,
        description="Planning board for Ada Lovelace work",
        headers=["person_id", "name", "status"],
        index_column="person_id",
        rows=[
            {
                "person_id": "P-1",
                "name": "Ada Lovelace",
                "status": "Ready",
            }
        ],
    )
    row = dataset.rows.get(index_value="P-1")
    other_user = create_test_user(django_user_model, username="otherpaletteowner")
    create_dataset(other_user.profile, name="Other Ada Research")

    def fake_search_profile_rows(search_profile, **kwargs):
        assert search_profile == profile
        assert kwargs["query"] == "Ada"
        assert kwargs["status"] == DatasetStatus.READY
        assert kwargs["archived"] is False
        assert kwargs["limit"] == 5
        return {
            "count": 1,
            "results": [
                {
                    "rank": 1,
                    "score": 0.98,
                    "dataset": {
                        "key": str(dataset.key),
                        "name": dataset.name,
                    },
                    "row": {
                        "id": row.id,
                        "row_number": row.row_number,
                        "index_value": row.index_value,
                        "data": row.data,
                    },
                    "match": {
                        "source": "hybrid",
                        "snippet": "Dataset: Ada Research person_id: P-1 name: Ada Lovelace",
                    },
                }
            ],
        }

    monkeypatch.setattr("apps.datasets.views.search_profile_rows", fake_search_profile_rows)

    response = auth_client.get(reverse("command_palette_search"), {"q": "Ada"})

    assert response.status_code == 200
    content = response.content.decode()
    assert "Rows" in content
    assert "Datasets" in content
    assert "Projects" in content
    assert "P-1" in content
    assert "Ada Research" in content
    assert "Ada Ops" in content
    assert "Other Ada Research" not in content
    assert reverse("dataset_detail", args=[dataset.key]) in content
    assert reverse("project_detail", args=[project.key]) in content
    assert reverse("dataset_row_detail", args=[dataset.key, row.id]) in content


def test_command_palette_search_keeps_metadata_results_when_row_search_fails(
    auth_client,
    monkeypatch,
    profile,
):
    create_dataset(
        profile,
        name="Vector Backlog",
        description="Rows mention stale embedding jobs.",
        rows=[{"name": "Stale vector task", "email": "task@example.com"}],
    )

    def fail_row_search(*args, **kwargs):
        raise DatasetServiceError(503, "Profile row vector search failed.")

    monkeypatch.setattr("apps.datasets.views.search_profile_rows", fail_row_search)

    response = auth_client.get(reverse("command_palette_search"), {"q": "vector"})

    assert response.status_code == 200
    content = response.content.decode()
    assert "Vector Backlog" in content
    assert "Row search is unavailable right now." in content


def test_command_palette_search_keeps_row_results_when_metadata_search_fails(
    auth_client,
    monkeypatch,
    profile,
):
    dataset = create_dataset(
        profile,
        name="Fallback Rows",
        headers=["person_id", "name"],
        index_column="person_id",
        rows=[{"person_id": "P-2", "name": "Grace Hopper"}],
    )
    row = dataset.rows.get(index_value="P-2")

    def fail_dataset_search(*args, **kwargs):
        raise DatasetServiceError(503, "Dataset search failed.")

    def fail_project_search(*args, **kwargs):
        raise DatasetServiceError(503, "Project search failed.")

    def fake_search_profile_rows(search_profile, **kwargs):
        assert search_profile == profile
        return {
            "count": 1,
            "results": [
                {
                    "rank": 1,
                    "score": 0.91,
                    "dataset": {
                        "key": str(dataset.key),
                        "name": dataset.name,
                    },
                    "row": {
                        "id": row.id,
                        "row_number": row.row_number,
                        "index_value": row.index_value,
                        "data": row.data,
                    },
                    "match": {
                        "source": "hybrid",
                        "snippet": "person_id: P-2 name: Grace Hopper",
                    },
                }
            ],
        }

    monkeypatch.setattr("apps.datasets.views.search_profile_datasets", fail_dataset_search)
    monkeypatch.setattr("apps.datasets.views.search_profile_projects", fail_project_search)
    monkeypatch.setattr("apps.datasets.views.search_profile_rows", fake_search_profile_rows)

    response = auth_client.get(reverse("command_palette_search"), {"q": "Grace"})

    assert response.status_code == 200
    content = response.content.decode()
    assert "P-2" in content
    assert "Dataset search is unavailable right now." in content
    assert "Project search is unavailable right now." in content
