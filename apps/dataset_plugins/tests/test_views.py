import pytest
from django.urls import reverse

from apps.dataset_plugins.models import DatasetPluginActivation
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


def test_dataset_settings_can_enable_flashcards_plugin(client, django_user_model):
    profile = create_profile_with_api_key(django_user_model)
    dataset = create_flashcard_dataset(profile)
    client.force_login(profile.user)

    settings_response = client.get(dataset.get_settings_url())

    assert settings_response.status_code == 200
    assert b"Plugins" in settings_response.content
    assert b"Flashcards" in settings_response.content

    response = client.post(
        reverse(
            "dataset_enable_plugin",
            kwargs={"dataset_key": dataset.key, "plugin_slug": "flashcards"},
        ),
        {
            "column__front_question": "front_question",
            "column__back_answer": "back_answer",
        },
    )

    activation = DatasetPluginActivation.objects.get(dataset=dataset, plugin_slug="flashcards")
    assert response.status_code == 302
    assert activation.enabled is True
    assert activation.config["columns"] == {
        "front_question": "front_question",
        "back_answer": "back_answer",
    }


def test_flashcards_plugin_view_renders_front_and_back(client, django_user_model):
    profile = create_profile_with_api_key(django_user_model)
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
    client.force_login(profile.user)

    response = client.get(
        reverse(
            "dataset_plugin_detail",
            kwargs={"dataset_key": dataset.key, "plugin_slug": "flashcards"},
        )
    )

    assert response.status_code == 200
    content = response.content.decode()
    assert "What does hola mean?" in content
    assert "Hello" in content
    assert "Reveal answer" in content
