from __future__ import annotations

import re
from typing import get_args

import posthog
from django.conf import settings

from rowset.public_request_context import PUBLIC_DATASET_CONTENT_SURFACES
from rowset.traffic import TrafficCategory
from rowset.utils import get_rowset_logger

logger = get_rowset_logger(__name__)

ROWSET_TRAFFIC_REQUEST_OBSERVED = "rowset_traffic_request_observed"

_TRAFFIC_CATEGORIES = frozenset(get_args(TrafficCategory))
_REQUEST_INTERFACES = frozenset({"web", "htmx", "rest", "mcp"})
_OUTCOMES = frozenset({"success", "failure"})
_STATUS_CLASSES = frozenset({"", "2xx", "3xx", "4xx", "5xx"})
_CONTENT_GROUPS = frozenset({"public_dataset"})
_SAFE_ROUTE = re.compile(r"[A-Za-z0-9:._/-]{1,160}")
_PUBLIC_CONTENT_ID = re.compile(r"pd_v1_[0-9a-f]{24}")


def capture_traffic_request(
    *,
    outcome: str,
    request_interface: str,
    route: str,
    status_class: str,
    traffic_category: TrafficCategory,
    content_group: str = "",
    content_id: str = "",
    content_surface: str = "",
) -> bool:
    """Capture one personless request event using bounded, non-identifying properties."""
    if not settings.POSTHOG_API_KEY:
        return False
    if (
        traffic_category not in _TRAFFIC_CATEGORIES
        or request_interface not in _REQUEST_INTERFACES
        or outcome not in _OUTCOMES
        or status_class not in _STATUS_CLASSES
    ):
        logger.warning("posthog.traffic_request.skipped", reason="unbounded_required_property")
        return False

    properties = {
        "$process_person_profile": False,
        "environment": settings.ENVIRONMENT,
        "event_version": 1,
        "outcome": outcome,
        "request_interface": request_interface,
        "traffic_category": traffic_category,
    }
    if status_class:
        properties["status_class"] = status_class
    if _SAFE_ROUTE.fullmatch(route):
        properties["route"] = route
    if content_group in _CONTENT_GROUPS:
        properties["content_group"] = content_group
    if content_surface in PUBLIC_DATASET_CONTENT_SURFACES:
        properties["content_surface"] = content_surface
    if content_group == "public_dataset" and _PUBLIC_CONTENT_ID.fullmatch(content_id):
        properties["content_id"] = content_id

    try:
        with posthog.new_context(fresh=True, capture_exceptions=False):
            posthog.capture(
                ROWSET_TRAFFIC_REQUEST_OBSERVED,
                properties=properties,
                disable_geoip=True,
            )
    except Exception as exc:
        logger.warning(
            "posthog.traffic_request.failed",
            error_type=type(exc).__name__,
        )
        return False
    return True
