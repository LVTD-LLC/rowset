import hashlib
import hmac
import re

from allauth.socialaccount.models import SocialApp
from django.conf import settings
from django.db.models import Prefetch

from apps.core.choices import ProfileStates
from apps.datasets.models import Dataset, Project, ProjectSection
from rowset.utils import get_rowset_logger

logger = get_rowset_logger(__name__)

POSTHOG_PAGEVIEW_GROUPS = {
    "account_confirm_email": "auth",
    "account_login": "auth",
    "account_reset_password": "auth",
    "account_reset_password_done": "auth",
    "account_reset_password_from_key": "auth",
    "account_reset_password_from_key_done": "auth",
    "account_signup": "auth",
    "account_signup_by_passkey": "auth",
    "blog_post": "blog",
    "blog_posts": "blog",
    "changelog": "marketing",
    "comparison_page": "marketing",
    "docs_home": "docs",
    "docs_page": "docs",
    "landing": "marketing",
    "pricing": "marketing",
    "privacy_policy": "marketing",
    "public_dataset": "public_dataset",
    "public_dataset_row_detail": "public_dataset",
    "socialaccount_login": "auth",
    "terms_of_service": "marketing",
    "use_case_page": "marketing",
    "use_cases": "marketing",
    "uses": "marketing",
}
POSTHOG_ROUTE_PARAMETER_PATTERN = re.compile(r"<(?:[^:>]+:)?([^>]+)>")


def app_navigation(request):
    """Return the authenticated project tree used by the shared app shell."""
    if not request.user.is_authenticated or not hasattr(request.user, "profile"):
        return {
            "app_navigation_projects": [],
            "show_trial_rewards_link": False,
        }

    profile = request.user.profile

    active_sections = ProjectSection.objects.filter(archived_at__isnull=True).order_by("name", "id")
    active_datasets = Dataset.objects.filter(archived_at__isnull=True).order_by("name", "id")
    projects = list(
        Project.objects.filter(
            profile=profile,
            archived_at__isnull=True,
        )
        .prefetch_related(
            Prefetch("sections", queryset=active_sections, to_attr="navigation_sections"),
            Prefetch("datasets", queryset=active_datasets, to_attr="navigation_datasets"),
        )
        .order_by("name", "id")
    )

    for project in projects:
        datasets_by_section_id = {}
        project.navigation_unsectioned_datasets = []
        project.navigation_is_current = request.path == project.get_absolute_url()
        active_section_ids = {section.id for section in project.navigation_sections}
        for dataset in project.navigation_datasets:
            dataset.navigation_is_current = request.path == dataset.get_absolute_url()
            project.navigation_is_current = (
                project.navigation_is_current or dataset.navigation_is_current
            )
            if dataset.section_id in active_section_ids:
                datasets_by_section_id.setdefault(dataset.section_id, []).append(dataset)
            else:
                project.navigation_unsectioned_datasets.append(dataset)
        for section in project.navigation_sections:
            section.navigation_datasets = datasets_by_section_id.get(section.id, [])
            section.navigation_is_current = any(
                dataset.navigation_is_current for dataset in section.navigation_datasets
            )

    return {
        "app_navigation_projects": projects,
        "app_navigation_unassigned_datasets": list(
            active_datasets.filter(profile=profile, project__isnull=True)
        ),
        "show_trial_rewards_link": bool(
            profile.trial_started_at
            and profile.setup_completed_at
            and not profile.has_active_subscription
        ),
    }


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
    resolver_match = getattr(request, "resolver_match", None)
    content_group = POSTHOG_PAGEVIEW_GROUPS.get(
        getattr(resolver_match, "url_name", None),
        "",
    )
    route = getattr(resolver_match, "route", "") if content_group else ""
    normalized_route = (
        f"/{POSTHOG_ROUTE_PARAMETER_PATTERN.sub(r':\1', route).lstrip('/')}"
        if content_group
        else ""
    )
    context = {
        "posthog_api_key": settings.POSTHOG_API_KEY,
        "posthog_content_group": content_group,
        "posthog_host": settings.POSTHOG_HOST,
        "posthog_distinct_id": "",
        "posthog_pageview_enabled": bool(settings.POSTHOG_API_KEY and normalized_route),
        "posthog_pageview_route": normalized_route,
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
