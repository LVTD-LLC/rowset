import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command

from apps.datasets.models import Dataset, DatasetRow, Project, ProjectSection

pytestmark = pytest.mark.django_db


def test_seed_dashboard_demo_is_idempotent():
    email = "designer@example.com"

    call_command("seed_dashboard_demo", email=email, password="local-password")
    call_command("seed_dashboard_demo", email=email, password="local-password")

    user = get_user_model().objects.get(email=email)
    profile = user.profile
    project = Project.objects.get(profile=profile, name="Product launch")

    assert project.sections.filter(archived_at__isnull=True).count() == 3
    assert Dataset.objects.filter(profile=profile, project=project).count() == 9
    assert Dataset.objects.filter(profile=profile, project=project, section=None).count() == 3
    assert Project.objects.filter(profile=profile).count() == 4
    assert ProjectSection.objects.filter(profile=profile).count() == 11
    assert Dataset.objects.filter(profile=profile).count() == 26
    assert DatasetRow.objects.filter(dataset__profile=profile).count() == 130
    assert Dataset.objects.get(profile=profile, name="Pipeline").column_schema["status"] == {
        "type": "choice",
        "choices": ["Planned", "In progress", "Review", "Done", "Blocked"],
    }
    assert set(
        Dataset.objects.filter(profile=profile, section__name="Sales").values_list(
            "name", flat=True
        )
    ) == {"Accounts", "Pipeline"}
