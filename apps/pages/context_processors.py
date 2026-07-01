def referrer_banner(request):
    """
    Adds referrer banner to context. Priority order:
    1. Exact match on ref or utm_source parameter (e.g., ProductHunt)
    2. Black Friday banner as fallback (if it exists and is active)
    Only displays one banner at most.
    """
    from django.db import DatabaseError

    from apps.pages.models import ReferrerBanner

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

    try:
        black_friday_banner = ReferrerBanner.objects.get(
            referrer_printable_name__icontains="Black Friday"
        )
        if black_friday_banner.should_display:
            return {"referrer_banner": black_friday_banner}
    except ReferrerBanner.DoesNotExist:
        pass
    except ReferrerBanner.MultipleObjectsReturned:
        black_friday_banner = (
            ReferrerBanner.objects.filter(referrer_printable_name__icontains="Black Friday")
            .filter(is_active=True)
            .first()
        )
        if black_friday_banner and black_friday_banner.should_display:
            return {"referrer_banner": black_friday_banner}
    except DatabaseError:
        return {}

    return {}
