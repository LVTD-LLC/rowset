import pytest

from apps.dataset_plugins.models import DatasetPluginActivation, ProfilePluginInstallation
from apps.datasets.tests.factories import create_dataset, create_profile_with_api_key

pytestmark = pytest.mark.django_db


def create_flashcard_dataset(profile):
    return create_dataset(
        profile,
        name="Spanish flashcards",
        headers=["card_id", "front_question", "back_answer"],
        index_column="card_id",
        rows=[
            {
                "card_id": "card-1",
                "front_question": "What does hola mean?",
                "back_answer": "Hello",
            }
        ],
    )


def make_staff(profile):
    profile.user.is_staff = True
    profile.user.save(update_fields=["is_staff"])
    return profile


def test_rest_lists_available_dataset_plugins(client, django_user_model):
    profile = make_staff(create_profile_with_api_key(django_user_model))

    response = client.get(
        "/api/dataset-plugins",
        HTTP_AUTHORIZATION=f"Bearer {profile.key}",
    )

    assert response.status_code == 200
    assert response.json()["plugins"] == []

    ProfilePluginInstallation.objects.create(profile=profile, plugin_slug="flashcards")

    response = client.get(
        "/api/dataset-plugins",
        HTTP_AUTHORIZATION=f"Bearer {profile.key}",
    )

    assert response.status_code == 200
    assert response.json()["plugins"][0]["slug"] == "flashcards"


def test_rest_hides_dataset_plugins_from_non_staff(client, django_user_model):
    profile = create_profile_with_api_key(django_user_model)
    ProfilePluginInstallation.objects.create(profile=profile, plugin_slug="flashcards")
    dataset = create_flashcard_dataset(profile)
    DatasetPluginActivation.objects.create(
        profile=profile,
        dataset=dataset,
        plugin_slug="flashcards",
        enabled=True,
        config={
            "columns": {
                "front_question": "front_question",
                "back_answer": "back_answer",
            }
        },
    )

    available_response = client.get(
        "/api/dataset-plugins",
        HTTP_AUTHORIZATION=f"Bearer {profile.key}",
    )
    list_response = client.get(
        f"/api/datasets/{dataset.key}/plugins",
        HTTP_AUTHORIZATION=f"Bearer {profile.key}",
    )
    enable_response = client.post(
        f"/api/datasets/{dataset.key}/plugins/flashcards",
        {"config": {}},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {profile.key}",
    )

    assert available_response.status_code == 200
    assert available_response.json() == {"plugins": []}
    assert list_response.status_code == 200
    assert list_response.json() == {
        "dataset": str(dataset.key),
        "available_plugins": [],
        "activations": [],
    }
    assert enable_response.status_code == 404


def test_rest_enables_lists_and_disables_dataset_plugin(client, django_user_model):
    profile = make_staff(create_profile_with_api_key(django_user_model))
    ProfilePluginInstallation.objects.create(profile=profile, plugin_slug="flashcards")
    dataset = create_flashcard_dataset(profile)

    enable_response = client.post(
        f"/api/datasets/{dataset.key}/plugins/flashcards",
        {
            "config": {
                "columns": {
                    "front_question": "front_question",
                    "back_answer": "back_answer",
                }
            }
        },
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {profile.key}",
    )

    assert enable_response.status_code == 200
    assert enable_response.json()["activation"]["enabled"] is True
    assert DatasetPluginActivation.objects.get(dataset=dataset).enabled is True

    list_response = client.get(
        f"/api/datasets/{dataset.key}/plugins",
        HTTP_AUTHORIZATION=f"Bearer {profile.key}",
    )

    assert list_response.status_code == 200
    assert list_response.json()["activations"][0]["plugin"]["slug"] == "flashcards"

    disable_response = client.delete(
        f"/api/datasets/{dataset.key}/plugins/flashcards",
        HTTP_AUTHORIZATION=f"Bearer {profile.key}",
    )

    assert disable_response.status_code == 200
    assert disable_response.json()["activation"]["enabled"] is False
    assert DatasetPluginActivation.objects.get(dataset=dataset).enabled is False
