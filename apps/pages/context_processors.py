from django.db import DatabaseError

from apps.pages.models import ReferrerBanner


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
