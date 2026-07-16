from django.db import DatabaseError
from django.templatetags.static import static

from apps.pages.models import ReferrerBanner
from apps.pages.search import build_canonical_url, search_robots_policy
from rowset.utils import build_absolute_public_url


def social_metadata(request):
    return {
        "rowset_social_image_url": build_absolute_public_url(
            static("vendors/images/rowset-social-card.png")
        )
    }


def search_metadata(request):
    return {
        "canonical_url": build_canonical_url(request.path),
        "search_robots_policy": search_robots_policy(),
    }


def _get_active_black_friday_banner():
    try:
        banner = ReferrerBanner.objects.get(referrer_printable_name__icontains="Black Friday")
    except ReferrerBanner.DoesNotExist:
        return None
    except ReferrerBanner.MultipleObjectsReturned:
        try:
            banner = (
                ReferrerBanner.objects.filter(referrer_printable_name__icontains="Black Friday")
                .filter(is_active=True)
                .first()
            )
        except DatabaseError:
            return None
    except DatabaseError:
        return None

    if banner and banner.should_display:
        return banner
    return None


def referrer_banner(request):
    """
    Adds referrer banner to context. Priority order:
    1. Exact match on ref or utm_source parameter (e.g., ProductHunt)
    2. Black Friday banner as fallback (if it exists and is active)
    Only displays one banner at most.
    """
    referrer_code = request.GET.get("ref") or request.GET.get("utm_source")

    try:
        if referrer_code:
            banner = ReferrerBanner.objects.get(referrer=referrer_code)
            if banner.should_display:
                return {"referrer_banner": banner}
    except ReferrerBanner.DoesNotExist:
        pass
    except DatabaseError:
        return {}

    black_friday_banner = _get_active_black_friday_banner()
    if black_friday_banner:
        return {"referrer_banner": black_friday_banner}

    return {}
