from urllib.parse import urlsplit

from allauth.account.views import SignupByPasskeyView, SignupView
from django.conf import settings
from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect
from django.templatetags.static import static
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_control
from django.views.generic import TemplateView
from django_q.tasks import async_task

from apps.core.analytics import ROWSET_SIGNUP_COMPLETED, track_activation_event
from apps.core.models import Profile
from apps.pages.schema import (
    article_schema,
    breadcrumb_list_schema,
    faq_page_schema,
    json_ld,
    organization_schema,
    software_application_schema,
    use_case_article_schema,
)
from apps.pages.use_cases import get_use_case_page, get_use_case_pages
from rowset.utils import build_absolute_public_url, get_rowset_logger

logger = get_rowset_logger(__name__)


def build_absolute_static_url(path: str) -> str:
    static_url = static(path)
    parsed_static_url = urlsplit(static_url)
    if parsed_static_url.scheme in {"http", "https"}:
        return static_url
    if parsed_static_url.netloc:
        public_scheme = urlsplit(settings.SITE_URL).scheme or "https"
        return f"{public_scheme}:{static_url}"
    return build_absolute_public_url(static_url)


class LandingPageView(TemplateView):
    template_name = "pages/landing-page.html"

    def get(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect("home")
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        if self.request.user.is_authenticated and settings.POSTHOG_API_KEY:
            user = self.request.user
            profile = user.profile

            async_task(
                "core.tasks.try_create_posthog_alias",
                profile_id=profile.id,
                cookies=self.request.COOKIES,
                source_function="LandingPageView - get_context_data",
                group="Create Posthog Alias",
            )

        payment_status = self.request.GET.get("payment")
        if payment_status == "success":
            messages.success(
                self.request,
                "Thanks for subscribing, I hope you enjoy the app!",
            )
        elif payment_status == "failed":
            messages.error(self.request, "Something went wrong with the payment.")

        context["use_case_pages"] = get_use_case_pages()
        context["schema_json"] = json_ld(
            [
                software_application_schema(),
                organization_schema(),
            ]
        )

        return context


class SignupTrackingMixin:
    tracking_source_name = "signup"

    def _track_signup(self):
        user = self.user
        profile = user.profile

        async_task(
            "core.tasks.try_create_posthog_alias",
            profile_id=profile.id,
            cookies=self.request.COOKIES,
            source_function=f"{self.tracking_source_name} - form_valid",
            group="Create Posthog Alias",
        )

        async_task(
            "core.tasks.track_event",
            profile_id=profile.id,
            event_name="user_signed_up",
            properties={
                "$set": {
                    "email": profile.user.email,
                    "username": profile.user.username,
                },
            },
            source_function=f"{self.tracking_source_name} - form_valid",
            group="Track Event",
        )
        track_activation_event(
            profile,
            ROWSET_SIGNUP_COMPLETED,
            {"signup_method": self.tracking_source_name},
            source_function=f"{self.tracking_source_name} - form_valid",
        )

    def form_valid(self, form):
        response = super().form_valid(form)
        self._track_signup()
        return response


class AccountSignupView(SignupTrackingMixin, SignupView):
    template_name = "account/signup.html"
    tracking_source_name = "AccountSignupView"


class AccountSignupByPasskeyView(SignupTrackingMixin, SignupByPasskeyView):
    template_name = "account/signup_by_passkey.html"
    tracking_source_name = "AccountSignupByPasskeyView"


class PricingView(TemplateView):
    template_name = "pages/pricing.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        if self.request.user.is_authenticated:
            try:
                profile = self.request.user.profile
                context["has_pro_subscription"] = profile.has_active_subscription
            except Profile.DoesNotExist:
                context["has_pro_subscription"] = False
        else:
            context["has_pro_subscription"] = False

        return context


class UseCasesIndexView(TemplateView):
    template_name = "pages/use-cases-index.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["use_case_pages"] = get_use_case_pages()
        return context


class UseCaseDetailView(TemplateView):
    template_name = "pages/use-case-detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        use_case = get_use_case_page(self.kwargs["slug"])
        if use_case is None:
            raise Http404("Use case not found")

        context["use_case"] = use_case
        context["related_use_cases"] = tuple(
            page for page in get_use_case_pages() if page["slug"] != use_case["slug"]
        )[:3]
        context["schema_json"] = json_ld(use_case_article_schema(use_case))
        return context


class DatabaseMcpServerPlaybookView(TemplateView):
    template_name = "pages/playbooks/database-mcp-server.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["mcp_url"] = build_absolute_public_url("/mcp/")
        context["schema_json"] = json_ld(
            [
                article_schema(
                    headline="Database MCP server: when to use Rowset instead",
                    description=(
                        "A practical guide to choosing between direct database MCP servers "
                        "and Rowset's hosted MCP dataset backend for AI-agent workflows."
                    ),
                    path="/playbooks/database-mcp-server",
                    date_published="2026-07-05",
                    date_modified="2026-07-05",
                ),
                breadcrumb_list_schema(
                    (
                        ("Home", "/"),
                        ("Database MCP server", "/playbooks/database-mcp-server"),
                    )
                ),
            ]
        )
        return context


# FAQ answers are plain text and intentionally render through Django autoescaping.
# Keep inline links in the template body, not inside this schema/source tuple.
AIRTABLE_ALTERNATIVE_FAQS = (
    (
        "Is Rowset a full Airtable replacement?",
        (
            "No. Airtable is a broader no-code app builder with views, automations, "
            "forms, templates, and collaboration features. Rowset is narrower: a "
            "private MCP and REST dataset backend for trusted AI agents."
        ),
    ),
    (
        "When should I choose Rowset over Airtable?",
        (
            "Choose Rowset when an agent needs to create, update, search, export, "
            "and share structured rows through a small authenticated backend without "
            "using browser automation or exposing a production database."
        ),
    ),
    (
        "Can I move Airtable data into Rowset?",
        (
            "Yes. Export the Airtable table to CSV, create a Rowset dataset with a "
            "stable index column, then give the agent instructions for how rows "
            "should be maintained."
        ),
    ),
)


@method_decorator(cache_control(public=True, max_age=3600), name="dispatch")
class AirtableAlternativeView(TemplateView):
    template_name = "pages/alternatives/airtable.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["faqs"] = AIRTABLE_ALTERNATIVE_FAQS
        context["canonical_url"] = build_absolute_public_url("/alternatives/airtable")
        context["og_image_url"] = build_absolute_static_url("vendors/images/logo.png")
        context["schema_json"] = json_ld(
            [
                article_schema(
                    headline="Airtable alternatives for AI-agent-managed datasets",
                    description=(
                        "A practical Airtable alternative guide for teams that need "
                        "trusted AI agents to maintain private structured rows over MCP and REST."
                    ),
                    path="/alternatives/airtable",
                    date_published="2026-07-05",
                    date_modified="2026-07-05",
                ),
                breadcrumb_list_schema(
                    (
                        ("Home", "/"),
                        ("Airtable alternatives", "/alternatives/airtable"),
                    )
                ),
                faq_page_schema(AIRTABLE_ALTERNATIVE_FAQS),
            ]
        )
        return context


class PrivacyPolicyView(TemplateView):
    template_name = "pages/privacy-policy.html"


class TermsOfServiceView(TemplateView):
    template_name = "pages/terms-of-service.html"
