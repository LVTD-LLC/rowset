import pytest
from django.apps import apps
from django.contrib.sites.models import Site
from django.core.exceptions import ImproperlyConfigured
from django.db.models.signals import post_migrate
from django.test import override_settings

from apps.core.site_config import get_site_domain, sync_site_from_settings


@pytest.mark.parametrize(
    ("site_url", "expected_domain"),
    (
        ("https://rowset.example", "rowset.example"),
        ("http://localhost:8000", "localhost:8000"),
    ),
)
def test_get_site_domain(site_url, expected_domain):
    assert get_site_domain(site_url) == expected_domain


@pytest.mark.parametrize("site_url", ("rowset.example", "ftp://rowset.example"))
def test_get_site_domain_requires_absolute_http_url(site_url):
    with pytest.raises(ImproperlyConfigured, match="SITE_URL must be an absolute"):
        get_site_domain(site_url)


@pytest.mark.django_db
@override_settings(SITE_URL="https://self-hosted.example", SITE_ID=1)
def test_sync_site_from_settings_updates_configured_site():
    Site.objects.update_or_create(
        pk=1,
        defaults={"domain": "example.com", "name": "example.com"},
    )

    sync_site_from_settings(using="default")
    sync_site_from_settings(using="default")

    site = Site.objects.get(pk=1)
    assert site.domain == "self-hosted.example"
    assert site.name == "Rowset"
    assert Site.objects.filter(pk=1).count() == 1


@pytest.mark.django_db
@override_settings(SITE_URL="https://signal.example", SITE_ID=1)
def test_core_post_migrate_signal_syncs_configured_site():
    core_config = apps.get_app_config("core")

    post_migrate.send(
        sender=core_config,
        app_config=core_config,
        verbosity=0,
        interactive=False,
        using="default",
        plan=[],
        apps=apps,
    )

    site = Site.objects.get(pk=1)
    assert site.domain == "signal.example"
    assert site.name == "Rowset"
