import hashlib
import hmac

from allauth.socialaccount.models import SocialApp
from django.conf import settings

from apps.core.choices import ProfileStates
from rowset.utils import get_rowset_logger

logger = get_rowset_logger(__name__)


def current_state(request):
    if request.user.is_authenticated:
        return {"current_state": request.user.profile.current_state}
    return {"current_state": ProfileStates.STRANGER}


def pro_subscription_status(request):
    """
    Adds a 'has_pro_subscription' variable to the context.
    This variable is True if the user has an active pro subscription, False otherwise.
    """
    if request.user.is_authenticated and hasattr(request.user, "profile"):
        return {"has_pro_subscription": request.user.profile.has_active_subscription}
    return {"has_pro_subscription": False}


def posthog_api_key(request):
    context = {
        "posthog_api_key": settings.POSTHOG_API_KEY,
        "posthog_host": settings.POSTHOG_HOST,
        "posthog_distinct_id": "",
        "posthog_user_email": "",
    }
    if request.user.is_authenticated and hasattr(request.user, "profile"):
        context["posthog_distinct_id"] = str(request.user.profile.id)
        context["posthog_user_email"] = request.user.email
    return context


def chatwoot_config(request):
    base_url = settings.CHATWOOT_BASE_URL.rstrip("/")
    website_token = settings.CHATWOOT_WEBSITE_TOKEN
    if not base_url or not website_token:
        return {"chatwoot": {"enabled": False}}

    config = {
        "enabled": True,
        "base_url": base_url,
        "website_token": website_token,
        "user": None,
    }

    if request.user.is_authenticated:
        identifier = str(request.user.id)
        user = {
            "identifier": identifier,
            "email": request.user.email,
            "name": request.user.get_full_name() or request.user.email,
        }
        if settings.CHATWOOT_HMAC_SECRET:
            user["identifier_hash"] = hmac.new(
                settings.CHATWOOT_HMAC_SECRET.encode(),
                identifier.encode(),
                hashlib.sha256,
            ).hexdigest()
        config["user"] = user

    return {"chatwoot": config}


def mjml_url(request):
    return {"mjml_url": settings.MJML_URL}


def available_social_providers(request):
    """
    Checks which social authentication providers are available.
    Returns a list of provider names from either SOCIALACCOUNT_PROVIDERS settings
    or SocialApp database entries, as django-allauth supports both configuration methods.
    """
    available_providers = set()

    configured_providers = getattr(settings, "SOCIALACCOUNT_PROVIDERS", {})

    available_providers.update(configured_providers.keys())

    try:
        social_apps = SocialApp.objects.all()
        for social_app in social_apps:
            available_providers.add(social_app.provider)
    except Exception as exc:
        logger.warning("Error retrieving SocialApp entries", error_type=type(exc).__name__)

    available_providers_list = sorted(list(available_providers))

    return {
        "available_social_providers": available_providers_list,
        "has_social_providers": len(available_providers_list) > 0,
    }
