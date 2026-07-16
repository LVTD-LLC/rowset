from urllib.parse import urlsplit

from django.conf import settings

CANONICAL_SITE_URL = "https://rowset.lvtd.dev"
INDEX_ROBOTS_POLICY = "index, follow"
NOINDEX_ROBOTS_POLICY = "noindex, nofollow, noarchive"


def _site_identity(url: str) -> tuple[str, str | None, int | None, str]:
    parsed = urlsplit(url.rstrip("/"))
    return parsed.scheme, parsed.hostname, parsed.port, parsed.path.rstrip("/")


_CANONICAL_SITE_IDENTITY = _site_identity(CANONICAL_SITE_URL)


def search_indexing_enabled() -> bool:
    return _site_identity(settings.SITE_URL) == _CANONICAL_SITE_IDENTITY


def search_robots_policy(page_policy: str = INDEX_ROBOTS_POLICY) -> str:
    if not search_indexing_enabled():
        return NOINDEX_ROBOTS_POLICY
    return page_policy


def build_canonical_url(path: str) -> str:
    canonical_path = urlsplit(path).path or "/"
    if not canonical_path.startswith("/"):
        canonical_path = f"/{canonical_path}"
    return f"{CANONICAL_SITE_URL}{canonical_path}"
