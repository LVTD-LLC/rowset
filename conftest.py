import json
import os

import pytest


def pytest_configure(config):
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "filebridge.settings")

    from django.conf import settings

    settings.STORAGES["staticfiles"]["BACKEND"] = (
        "django.contrib.staticfiles.storage.StaticFilesStorage"
    )


@pytest.fixture(autouse=True)
def webpack_manifest(settings, tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "entrypoints": {
                    "index": {
                        "assets": {
                            "css": ["http://assets.example/index.css"],
                            "js": ["http://assets.example/index.js"],
                        }
                    }
                },
                "index.css": "http://assets.example/index.css",
                "index.js": "http://assets.example/index.js",
            }
        ),
        encoding="utf-8",
    )
    settings.WEBPACK_LOADER = {"MANIFEST_FILE": manifest, "CACHE": False}

    from webpack_boilerplate import utils as webpack_utils

    webpack_utils._loaders.clear()
    yield
    webpack_utils._loaders.clear()
