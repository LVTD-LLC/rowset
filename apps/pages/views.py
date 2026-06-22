from allauth.account.views import SignupByPasskeyView, SignupView
from django.conf import settings
from django.contrib import messages
from django.urls import reverse
from django.views.generic import TemplateView
from django_q.tasks import async_task

from apps.core.agent_skill import ROWSET_SKILL_INSTALL_COMMAND
from apps.core.models import Profile
from filebridge.utils import build_absolute_public_url, get_filebridge_logger

logger = get_filebridge_logger(__name__)


class LandingPageView(TemplateView):
    template_name = "pages/landing-page.html"

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
            messages.success(self.request, "Thanks for subscribing, I hope you enjoy the app!")
        elif payment_status == "failed":
            messages.error(self.request, "Something went wrong with the payment.")

        mcp_url = build_absolute_public_url("/mcp/")
        rest_api_base_url = build_absolute_public_url("/api/")
        instructions_url = build_absolute_public_url(reverse("agent_instructions_rowset_mcp"))
        signup_url = build_absolute_public_url(reverse("account_signup"))

        context["landing_agent_setup_prompt"] = "\n".join(
            [
                "Set yourself up to use Rowset for me.",
                "",
                f"Rowset MCP URL: {mcp_url}",
                f"Rowset REST API base: {rest_api_base_url}",
                f"Agent instructions/skill: {instructions_url}",
                f"Agent skill install: {ROWSET_SKILL_INSTALL_COMMAND}",
                "",
                "Read the skill URL or install the repo skill, configure Rowset as a remote "
                "Streamable HTTP MCP server, and use an agent API key as the bearer token. "
                f"If I do not have a Rowset account yet, tell me to sign up at {signup_url}. "
                "After signup, the key should be stored in a private ROWSET_API_KEY "
                "environment variable or client secret store, then configured as the MCP "
                "bearer-token env var. After setup, call get_user_info, then use "
                "get_all_datasets, create_dataset, row tools, exports, and "
                "update_dataset_public_preview as needed.",
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



class PrivacyPolicyView(TemplateView):
    template_name = "pages/privacy-policy.html"


class TermsOfServiceView(TemplateView):
    template_name = "pages/terms-of-service.html"
