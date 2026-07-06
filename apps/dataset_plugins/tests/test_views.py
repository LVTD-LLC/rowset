import pytest
from django.urls import reverse

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


def install_flashcards(profile):
    return ProfilePluginInstallation.objects.create(profile=profile, plugin_slug="flashcards")


def make_staff(profile):
    profile.user.is_staff = True
    profile.user.save(update_fields=["is_staff"])
    return profile


def test_plugin_marketplace_lists_official_plugins_and_installs_for_account(
    client,
    django_user_model,
):
    profile = make_staff(create_profile_with_api_key(django_user_model))
    client.force_login(profile.user)

    response = client.get(reverse("plugin_marketplace"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Flashcards" in content
    assert "Install plugin" in content

    install_response = client.post(reverse("plugin_install", args=["flashcards"]))

    assert install_response.status_code == 302
    assert install_response["Location"] == reverse("plugin_marketplace")
    assert ProfilePluginInstallation.objects.filter(
        profile=profile,
        plugin_slug="flashcards",
    ).exists()


def test_plugin_marketplace_returns_404_for_non_staff(client, django_user_model):
    profile = create_profile_with_api_key(django_user_model)
    client.force_login(profile.user)

    marketplace_response = client.get(reverse("plugin_marketplace"))
    install_response = client.post(reverse("plugin_install", args=["flashcards"]))
    uninstall_response = client.post(reverse("plugin_uninstall", args=["flashcards"]))

    assert marketplace_response.status_code == 404
    assert install_response.status_code == 404
    assert uninstall_response.status_code == 404


def test_dataset_settings_only_show_plugins_installed_for_the_account(
    client,
    django_user_model,
):
    profile = make_staff(create_profile_with_api_key(django_user_model))
    dataset = create_dataset(
        profile,
        headers=["front_title", "back_answer"],
        index_column="front_title",
    )
    client.force_login(profile.user)

    response = client.get(reverse("dataset_settings", args=[dataset.key]))

    assert response.status_code == 200
    assert "Flashcards" not in response.content.decode()

    install_flashcards(profile)

    response = client.get(reverse("dataset_settings", args=[dataset.key]))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Flashcards" in content
    assert "Plugin available" in content
    assert reverse("dataset_enable_plugin", args=[dataset.key, "flashcards"]) in content
    assert "Mapped Front question -&gt; front_title; Back answer -&gt; back_answer." in content


def test_dataset_settings_explain_why_installed_plugin_cannot_be_enabled(
    client,
    django_user_model,
):
    profile = make_staff(create_profile_with_api_key(django_user_model))
    dataset = create_dataset(
        profile,
        headers=["front_title", "notes"],
        index_column="front_title",
    )
    install_flashcards(profile)
    client.force_login(profile.user)

    response = client.get(reverse("dataset_settings", args=[dataset.key]))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Flashcards" in content
    assert "Needs columns" in content
    assert "Back answer" in content
    assert "Install plugins" not in content


def test_plugin_uninstall_returns_404_for_malformed_slug(client, django_user_model):
    profile = make_staff(create_profile_with_api_key(django_user_model))
    client.force_login(profile.user)

    response = client.post(reverse("plugin_uninstall", args=["-invalid"]))

    assert response.status_code == 404


def test_dataset_settings_can_enable_flashcards_plugin(client, django_user_model):
    profile = make_staff(create_profile_with_api_key(django_user_model))
    install_flashcards(profile)
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


def test_dataset_plugin_enable_returns_404_for_malformed_slug(client, django_user_model):
    profile = make_staff(create_profile_with_api_key(django_user_model))
    dataset = create_flashcard_dataset(profile)
    client.force_login(profile.user)

    response = client.post(
        reverse(
            "dataset_enable_plugin",
            kwargs={"dataset_key": dataset.key, "plugin_slug": "-invalid"},
        )
    )

    assert response.status_code == 404


def test_uninstalled_plugin_cannot_be_enabled_for_dataset(client, django_user_model):
    profile = make_staff(create_profile_with_api_key(django_user_model))
    dataset = create_flashcard_dataset(profile)
    client.force_login(profile.user)

    response = client.post(
        reverse(
            "dataset_enable_plugin",
            kwargs={"dataset_key": dataset.key, "plugin_slug": "flashcards"},
        )
    )

    assert response.status_code == 302
    assert response["Location"] == f"{dataset.get_settings_url()}#plugins"
    assert not DatasetPluginActivation.objects.filter(dataset=dataset).exists()


def test_dataset_settings_hides_plugins_for_non_staff(client, django_user_model):
    profile = create_profile_with_api_key(django_user_model)
    dataset = create_flashcard_dataset(profile)
    install_flashcards(profile)
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

    response = client.get(dataset.get_settings_url())

    assert response.status_code == 200
    assert b'href="#plugins"' not in response.content
    assert b"Flashcards" not in response.content


def test_dataset_plugin_actions_return_404_for_non_staff(client, django_user_model):
    profile = create_profile_with_api_key(django_user_model)
    dataset = create_flashcard_dataset(profile)
    install_flashcards(profile)
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

    enable_response = client.post(
        reverse(
            "dataset_enable_plugin",
            kwargs={"dataset_key": dataset.key, "plugin_slug": "flashcards"},
        ),
        {
            "column__front_question": "front_question",
            "column__back_answer": "back_answer",
        },
    )
    detail_response = client.get(
        reverse(
            "dataset_plugin_detail",
            kwargs={"dataset_key": dataset.key, "plugin_slug": "flashcards"},
        )
    )

    assert enable_response.status_code == 404
    assert detail_response.status_code == 404


def test_flashcards_plugin_view_renders_front_and_back(client, django_user_model):
    profile = make_staff(create_profile_with_api_key(django_user_model))
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
