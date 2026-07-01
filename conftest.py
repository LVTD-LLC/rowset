import os


def pytest_configure(config):
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "rowset.settings")

    from django.conf import settings

    settings.STORAGES["staticfiles"]["BACKEND"] = (
        "django.contrib.staticfiles.storage.StaticFilesStorage"
    )
