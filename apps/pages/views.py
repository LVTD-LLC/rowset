from allauth.account.views import SignupByPasskeyView, SignupView
from django.conf import settings
from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect
from django.views.generic import TemplateView
from django_q.tasks import async_task

from apps.core.analytics import ROWSET_SIGNUP_COMPLETED, track_activation_event
from apps.core.models import Profile
from apps.pages.use_cases import get_use_case_page, get_use_case_pages
from rowset.utils import get_rowset_logger

logger = get_rowset_logger(__name__)


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
        return context


class PrivacyPolicyView(TemplateView):
    template_name = "pages/privacy-policy.html"


class TermsOfServiceView(TemplateView):
    template_name = "pages/terms-of-service.html"
