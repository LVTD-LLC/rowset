from urllib.parse import urlsplit, urlunsplit

import structlog
from django.conf import settings


def build_absolute_public_url(path: str) -> str:
    site_url = settings.SITE_URL.rstrip("/")
    parsed_url = urlsplit(site_url)
    local_hosts = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}

    if parsed_url.scheme == "http" and parsed_url.hostname not in local_hosts:
        site_url = urlunsplit(
            (
                "https",
                parsed_url.netloc,
                parsed_url.path,
                parsed_url.query,
                parsed_url.fragment,
            )
        ).rstrip("/")

    return f"{site_url}{path}"


def get_filebridge_logger(name):
    """This will add a `filebridge` prefix to logger for easy configuration."""

    return structlog.get_logger(
        f"filebridge.{name}",
        project="filebridge"
    )
