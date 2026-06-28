from urllib.parse import urlsplit

from django import template

register = template.Library()

_ALLOWED_EXTERNAL_LINK_SCHEMES = {"http", "https"}
_UNSAFE_EXTERNAL_LINK_CHARS = frozenset("\"'<>`")


def safe_external_href(value) -> str:
    candidate = "" if value is None else str(value).strip()
    if (
        not candidate
        or any(char.isspace() for char in candidate)
        or any(char in candidate for char in _UNSAFE_EXTERNAL_LINK_CHARS)
    ):
        return ""

    try:
        parsed = urlsplit(candidate)
    except ValueError:
        return ""
    if (
        parsed.scheme.lower() not in _ALLOWED_EXTERNAL_LINK_SCHEMES
        or not parsed.netloc
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        return ""
    return candidate


@register.simple_tag
def dataset_external_href(value) -> str:
    return safe_external_href(value)
