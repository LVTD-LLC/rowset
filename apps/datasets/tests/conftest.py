import pytest

from apps.datasets.tests.factories import create_test_user, provision_profile_api_key


@pytest.fixture
def user(django_user_model):
    return create_test_user(
        django_user_model,
        username="csvuser",
        email="csvuser@example.com",
    )


@pytest.fixture
def auth_client(client, user):
    client.force_login(user)
    return client


@pytest.fixture
def profile(user):
    provision_profile_api_key(user.profile)
    return user.profile
