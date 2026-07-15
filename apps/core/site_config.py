from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.sites.models import Site
from django.core.exceptions import ImproperlyConfigured


def get_site_domain(site_url: str) -> str:
    parsed_url = urlsplit(site_url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        raise ImproperlyConfigured("SITE_URL must be an absolute HTTP or HTTPS URL.")
    return parsed_url.netloc


def sync_site_from_settings(*, using: str, **kwargs) -> None:
    Site.objects.using(using).update_or_create(
        pk=settings.SITE_ID,
        defaults={
            "domain": get_site_domain(settings.SITE_URL),
            "name": "Rowset",
        },
    )
