import pytest

from apps.api.services import DatasetServiceError
from apps.dataset_plugins.models import DatasetPluginActivation, ProfilePluginInstallation
from apps.dataset_plugins.services import (
    dataset_plugin_marketplace_context,
    disable_profile_dataset_plugin,
    enable_profile_dataset_plugin,
    install_profile_dataset_plugin,
    list_available_dataset_plugins,
    list_profile_dataset_plugin_activations,
    uninstall_profile_dataset_plugin,
)
from apps.datasets.tests.factories import create_dataset, create_profile_with_api_key

pytestmark = pytest.mark.django_db


def create_flashcard_dataset(profile, *, headers=None):
    return create_dataset(
        profile,
        name="Spanish flashcards",
        headers=headers
        or [
            "card_id",
            "front_title",
            "front_question",
            "back_title",
            "back_answer",
            "tags",
        ],
        index_column="card_id",
        rows=[
            {
                "card_id": "card-1",
                "front_title": "Hola",
                "front_question": "What does hola mean?",
                "back_title": "Answer",
                "back_answer": "Hello",
                "tags": "greeting",
            }
        ],
    )


def install_flashcards(profile):
    return ProfilePluginInstallation.objects.create(profile=profile, plugin_slug="flashcards")


def test_plugin_marketplace_context_marks_installed_plugins(django_user_model):
    profile = create_profile_with_api_key(django_user_model)

    rows = dataset_plugin_marketplace_context(profile)

    assert rows[0]["plugin"]["slug"] == "flashcards"
    assert rows[0]["is_installed"] is False

    install_profile_dataset_plugin(profile, "flashcards")

    rows = dataset_plugin_marketplace_context(profile)
    assert rows[0]["plugin"]["slug"] == "flashcards"
    assert rows[0]["is_installed"] is True


def test_available_plugins_include_flashcards(django_user_model):
    profile = create_profile_with_api_key(django_user_model)

    result = list_available_dataset_plugins(profile)

    assert result["plugins"] == []

    install_profile_dataset_plugin(profile, "flashcards")
    result = list_available_dataset_plugins(profile)

    assert result["plugins"][0]["slug"] == "flashcards"
    assert result["plugins"][0]["name"] == "Flashcards"
    assert {role["key"] for role in result["plugins"][0]["column_roles"]} >= {
        "front_question",
        "back_answer",
    }


def test_enable_dataset_plugin_autodetects_flashcard_columns(django_user_model):
    profile = create_profile_with_api_key(django_user_model)
    install_flashcards(profile)
    dataset = create_flashcard_dataset(profile)

    result = enable_profile_dataset_plugin(profile, str(dataset.key), "flashcards")

    activation = DatasetPluginActivation.objects.get(dataset=dataset, plugin_slug="flashcards")
    assert activation.enabled is True
    assert activation.config["columns"] == {
        "front_title": "front_title",
        "front_question": "front_question",
        "back_title": "back_title",
        "back_answer": "back_answer",
        "tags": "tags",
    }
    assert result["activation"]["config"] == activation.config
    assert result["activation"]["plugin"]["slug"] == "flashcards"


def test_enable_dataset_plugin_accepts_explicit_column_mapping(django_user_model):
    profile = create_profile_with_api_key(django_user_model)
    install_flashcards(profile)
    dataset = create_flashcard_dataset(
        profile,
        headers=["id", "question", "answer", "note"],
    )

    result = enable_profile_dataset_plugin(
        profile,
        str(dataset.key),
        "flashcards",
        config={
            "columns": {
                "front_question": "question",
                "back_answer": "answer",
                "back_title": "note",
            }
        },
    )

    assert result["activation"]["config"]["columns"] == {
        "front_question": "question",
        "back_title": "note",
        "back_answer": "answer",
    }


def test_enable_dataset_plugin_rejects_missing_required_columns(django_user_model):
    profile = create_profile_with_api_key(django_user_model)
    install_flashcards(profile)
    dataset = create_dataset(
        profile,
        name="Incomplete cards",
        headers=["id", "front_question"],
        index_column="id",
        rows=[{"id": "card-1", "front_question": "Question"}],
    )

    with pytest.raises(DatasetServiceError, match="requires a column for Back answer") as exc_info:
        enable_profile_dataset_plugin(profile, str(dataset.key), "flashcards")

    assert exc_info.value.status_code == 400
    assert not DatasetPluginActivation.objects.filter(dataset=dataset).exists()


def test_enable_dataset_plugin_enforces_dataset_ownership(django_user_model):
    profile = create_profile_with_api_key(django_user_model, username="owner")
    other_profile = create_profile_with_api_key(django_user_model, username="other")
    install_flashcards(other_profile)
    dataset = create_flashcard_dataset(profile)

    with pytest.raises(DatasetServiceError, match="Dataset not found") as exc_info:
        enable_profile_dataset_plugin(other_profile, str(dataset.key), "flashcards")

    assert exc_info.value.status_code == 404


def test_enable_dataset_plugin_requires_account_installation(django_user_model):
    profile = create_profile_with_api_key(django_user_model)
    dataset = create_flashcard_dataset(profile)

    with pytest.raises(DatasetServiceError, match="Install Flashcards before enabling") as exc_info:
        enable_profile_dataset_plugin(profile, str(dataset.key), "flashcards")

    assert exc_info.value.status_code == 400
    assert not DatasetPluginActivation.objects.filter(dataset=dataset).exists()


def test_disable_dataset_plugin_marks_activation_disabled(django_user_model):
    profile = create_profile_with_api_key(django_user_model)
    install_flashcards(profile)
    dataset = create_flashcard_dataset(profile)
    enable_profile_dataset_plugin(profile, str(dataset.key), "flashcards")

    result = disable_profile_dataset_plugin(profile, str(dataset.key), "flashcards")

    activation = DatasetPluginActivation.objects.get(dataset=dataset, plugin_slug="flashcards")
    assert activation.enabled is False
    assert result["activation"]["enabled"] is False


def test_list_dataset_plugin_activations_returns_available_and_enabled(django_user_model):
    profile = create_profile_with_api_key(django_user_model)
    install_flashcards(profile)
    dataset = create_flashcard_dataset(profile)
    enable_profile_dataset_plugin(profile, str(dataset.key), "flashcards")

    result = list_profile_dataset_plugin_activations(profile, str(dataset.key))

    assert result["dataset"] == str(dataset.key)
    assert result["available_plugins"][0]["slug"] == "flashcards"
    assert result["activations"][0]["plugin"]["slug"] == "flashcards"
    assert result["activations"][0]["enabled"] is True


def test_uninstall_dataset_plugin_removes_account_install_and_activations(django_user_model):
    profile = create_profile_with_api_key(django_user_model)
    install_flashcards(profile)
    dataset = create_flashcard_dataset(profile)
    enable_profile_dataset_plugin(profile, str(dataset.key), "flashcards")

    removed = uninstall_profile_dataset_plugin(profile, "flashcards")

    assert removed is True
    assert not ProfilePluginInstallation.objects.filter(
        profile=profile,
        plugin_slug="flashcards",
    ).exists()
    assert not DatasetPluginActivation.objects.filter(
        profile=profile,
        plugin_slug="flashcards",
    ).exists()
