import json
import re
from typing import Any
from urllib.parse import unquote

ATTRIBUTION_COOKIE = "rowset_marketing_attribution"
ATTRIBUTION_VERSION = 1
CAMPAIGN_KEYS = (
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_content",
    "utm_term",
    "campaign_id",
)
_VALUE_RE = re.compile(r"^[a-z0-9][a-z0-9 ._\-/]*$", re.IGNORECASE)
_DOMAIN_RE = re.compile(r"^[a-z0-9.-]+$", re.IGNORECASE)
_ATTRIBUTION_PARSE_ERRORS = (TypeError, ValueError, json.JSONDecodeError)


def _sanitize_touch(touch: Any) -> dict[str, str]:
    if not isinstance(touch, dict):
        return {}
    clean = {
        key: item
        for key in CAMPAIGN_KEYS
        if isinstance((item := touch.get(key)), str)
        and 0 < len(item) <= 100
        and _VALUE_RE.fullmatch(item)
    }
    route = touch.get("landing_route")
    if isinstance(route, str) and route.startswith("/") and "?" not in route and len(route) <= 160:
        clean["landing_route"] = route
    domain = touch.get("referring_domain")
    if isinstance(domain, str) and len(domain) <= 253 and _DOMAIN_RE.fullmatch(domain):
        clean["referring_domain"] = domain.lower()
    return clean


def parse_attribution_cookie(value: str | None) -> dict[str, Any]:
    """Return only the small, allowlisted marketing context we trust for analytics."""
    if not value or len(value) > 4096:
        return {}
    try:
        raw = json.loads(unquote(value))
    except _ATTRIBUTION_PARSE_ERRORS:
        return {}
    if not isinstance(raw, dict) or raw.get("version") != ATTRIBUTION_VERSION:
        return {}

    result: dict[str, Any] = {"version": ATTRIBUTION_VERSION}
    for touch_name in ("first_touch", "latest_touch"):
        clean = _sanitize_touch(raw.get(touch_name))
        if clean:
            result[touch_name] = clean
    return result if len(result) > 1 else {}


def attribution_event_properties(attribution: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(attribution, dict):
        return {}
    properties: dict[str, Any] = {"attribution_version": ATTRIBUTION_VERSION}
    first = attribution.get("first_touch") or {}
    latest = attribution.get("latest_touch") or {}
    for key in CAMPAIGN_KEYS:
        if key in latest:
            properties[key] = latest[key]
        if key in first:
            properties[f"initial_{key}"] = first[key]
    for key in ("landing_route", "referring_domain"):
        if key in first:
            properties[f"initial_{key}"] = first[key]
    return properties if len(properties) > 1 else {}
