import stripe
from allauth.account.internal.flows.email_verification import (
    send_verification_email_to_address,
)
from allauth.account.models import EmailAddress
from allauth.mfa.models import Authenticator
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.core.cache import cache
from django.db import transaction
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import redirect
from django.urls import reverse, reverse_lazy
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from django.views.generic import TemplateView, UpdateView

from apps.core.forms import ProfileUpdateForm
from apps.core.models import Profile
from apps.core.stripe_webhooks import EVENT_HANDLERS
from apps.datasets.choices import DatasetStatus
from filebridge.utils import build_absolute_public_url, get_filebridge_logger

stripe.api_key = settings.STRIPE_SECRET_KEY


logger = get_filebridge_logger(__name__)

AGENT_API_KEY_MASK = "***"


AGENT_INSTRUCTIONS_MARKDOWN = """# FileBridge Agent Skill

Use this when a user asks you to connect to FileBridge or work with FileBridge datasets.
FileBridge turns user-owned tabular data into datasets that agents can discover,
read, create, update, export, and share through MCP or the REST API.

## Prompt Inputs

The setup prompt should provide:

- `FileBridge MCP URL`
- `FileBridge REST API base`
- `FileBridge API key`
- this `SKILL.md` URL

## Setup

1. Configure your MCP client for a remote Streamable HTTP server named `filebridge`.
2. Use the provided MCP URL exactly as given.
3. When your MCP client opens the FileBridge authorization link, sign in and
   approve access in the browser.
4. If your client needs a token, use the API key as a bearer token. Never print it
   in logs, screenshots, public chats, or generated files.
5. After connecting, call the `get_user_info` tool to verify the connection.
6. Use `get_all_datasets` to discover datasets available to the authenticated
   profile before reading rows.
7. Use `create_dataset` when the user asks you to make a new ready dataset on the fly.
8. Use `get_dataset`, `list_dataset_rows`, `get_dataset_row`,
   `get_dataset_row_by_index`, `create_dataset_row`, `update_dataset_row`, and
   `delete_dataset_row` to inspect and manage ready dataset rows.
9. Use `update_dataset_public_preview` when the user asks to enable, disable,
   password-protect, or resize a public read-only preview.

## How To Work

- Prefer MCP tools over browser automation when working with FileBridge.
- Use `get_all_datasets` for dataset discovery. It returns paginated dataset
  metadata only, not row contents.
- Use `create_dataset` when a workflow needs a new dataset. It returns a dataset
  key that can be used immediately with row tools.
- Use row tools for dataset contents. They require a ready dataset and enforce the
  authenticated user's dataset ownership.
- Use `update_dataset_public_preview` for public sharing. Public previews are
  read-only browser pages, not a substitute for authenticated MCP or REST access.
- If MCP configuration is unavailable in your runtime, ask the user before falling
  back to REST API authentication. The user can copy their API key from FileBridge
  Settings.
- Ask the user before destructive changes such as deleting datasets or rows.
- Keep user data private and only access the FileBridge resources needed for the task.
"""


def build_agent_setup_prompt(
    request: HttpRequest,
    *,
    mask_api_key: bool = False,
    profile: Profile | None = None,
) -> str:
    mcp_url = build_absolute_public_url("/mcp/")
    rest_api_base_url = build_absolute_public_url("/api/")
    instructions_url = build_absolute_public_url(reverse("agent_instructions_filebridge_mcp"))
    if profile is None:
        profile, _created = Profile.objects.get_or_create(user=request.user)
    api_key = AGENT_API_KEY_MASK if mask_api_key else profile.key

    return "\n".join(
        [
            "Set up FileBridge for this user.",
            "",
            f"FileBridge MCP URL: {mcp_url}",
            f"FileBridge REST API base: {rest_api_base_url}",
            f"FileBridge API key: {api_key}",
            f"FileBridge skill: {instructions_url}",
            "",
            "Read the instructions/skill URL, configure FileBridge as a remote Streamable "
            "HTTP MCP server, and complete the browser authorization flow opened by your "
            "MCP client. Use the API key only when your client needs bearer-token auth "
            "or REST fallback. After setup, call get_user_info to verify the connection, "
            "then call get_all_datasets to discover available datasets. Use "
            "create_dataset when you need to create a dataset on the fly. Use "
            "update_dataset_public_preview when the user asks for a shareable read-only "
            "preview. Discover the current MCP tools and API docs at runtime before "
            "working with datasets.",
        ]
    )


class HomeView(LoginRequiredMixin, TemplateView):
    login_url = "account_login"
    template_name = "pages/home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        payment_status = self.request.GET.get("payment")
        if payment_status == "success":
            messages.success(self.request, "Thanks for subscribing, I hope you enjoy the app!")
            context["show_confetti"] = True
        elif payment_status == "failed":
            messages.error(self.request, "Something went wrong with the payment.")

        profile, _created = Profile.objects.get_or_create(user=self.request.user)
        context["recent_datasets"] = profile.datasets.exclude(status=DatasetStatus.PREVIEWED)[:5]
        context["agent_setup_prompt_masked"] = build_agent_setup_prompt(
            self.request,
            mask_api_key=True,
            profile=profile,
        )
        context["agent_setup_prompt_url"] = reverse("agent_setup_prompt")
        context["agent_instructions_url"] = build_absolute_public_url(
            reverse("agent_instructions_filebridge_mcp")
        )
        context["mcp_url"] = build_absolute_public_url("/mcp/")
        context["rest_api_base_url"] = build_absolute_public_url("/api/")
        return context


class UserSettingsView(LoginRequiredMixin, SuccessMessageMixin, UpdateView):
    login_url = "account_login"
    model = Profile
    form_class = ProfileUpdateForm
    success_message = "User Profile Updated"
    success_url = reverse_lazy("settings")
    template_name = "pages/user-settings.html"

    def get_object(self):
        return self.request.user.profile

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user

        email_address = EmailAddress.objects.get_for_user(user, user.email)
        context["email_verified"] = email_address is None or email_address.verified
        context["resend_confirmation_url"] = reverse("resend_confirmation")
        context["has_subscription"] = user.profile.has_active_subscription
        context["passkey_count"] = Authenticator.objects.filter(
            user=user,
            type=Authenticator.Type.WEBAUTHN,
        ).count()
        context["api_key"] = user.profile.key

        return context


def agent_instructions_filebridge_mcp(request):
    return HttpResponse(AGENT_INSTRUCTIONS_MARKDOWN, content_type="text/markdown; charset=utf-8")


@login_required
@require_GET
def agent_setup_prompt(request):
    profile, _created = Profile.objects.get_or_create(user=request.user)
    response = JsonResponse({"prompt": build_agent_setup_prompt(request, profile=profile)})
    response["Cache-Control"] = "no-store"
    return response


@login_required
def resend_confirmation_email(request):
    user = request.user

    try:
        email_address = EmailAddress.objects.get_for_user(user, user.email)

        if not email_address:
            messages.error(request, "No email address found for your account.")
            logger.warning(
                "[Resend Confirmation] No email address found",
                user_id=user.id,
                user_email=user.email,
            )
            return redirect("settings")

        if email_address.verified:
            messages.info(request, "Your email is already verified.")
            logger.info(
                "[Resend Confirmation] Email already verified",
                user_id=user.id,
                user_email=user.email,
            )
            return redirect("settings")

        sent = send_verification_email_to_address(request, email_address, signup=False)
        if not sent:
            messages.error(
                request,
                "Please wait before requesting another confirmation email.",
            )
            return redirect("settings")

        logger.info(
            "[Resend Confirmation] Email sent successfully",
            user_id=user.id,
            user_email=user.email,
        )

    except Exception as e:
        messages.error(request, "Failed to send confirmation email. Please try again later.")
        logger.error(
            "[Resend Confirmation] Failed to send email",
            user_id=user.id,
            user_email=user.email,
            error=str(e),
            exc_info=True,
        )

    return redirect("settings")


@login_required
@require_POST
def delete_account(request):
    """Permanently delete the current user and all related data.

    Safety: requires a confirmation text value.
    """

    confirmation = request.POST.get("confirmation", "")
    if confirmation != "DELETE":
        messages.error(request, "Type DELETE to confirm account deletion.")
        return redirect("settings")

    user_id = request.user.id

    # Ensure we log the user out and remove data in a single flow.
    with transaction.atomic():
        user = request.user
        logout(request)
        user.delete()

    logger.info("User account deleted", user_id=user_id)
    return redirect(f"{reverse('landing')}?account_deleted=1")


@login_required
@require_POST
def create_checkout_session(request, pk, plan):
    user = request.user
    profile = user.profile
    price_id = get_price_id_for_plan(plan)
    if not price_id:
        logger.warning("Stripe price id not configured for plan", plan=plan, user_id=user.id)
        messages.error(request, "Unable to find pricing for the selected plan.")
        return redirect("pricing")

    try:
        customer = get_or_create_stripe_customer(profile, user)
    except stripe.error.StripeError as exc:
        logger.error(
            "Stripe customer setup failed",
            profile_id=profile.id,
            error=str(exc),
        )
        messages.error(request, "Unable to start checkout. Please try again.")
        return redirect("pricing")

    base_success_url = request.build_absolute_uri(reverse("home"))
    base_cancel_url = request.build_absolute_uri(reverse("home"))

    success_params = {"payment": "success"}
    success_url = f"{base_success_url}?{urlencode(success_params)}"

    cancel_params = {"payment": "failed"}
    cancel_url = f"{base_cancel_url}?{urlencode(cancel_params)}"

    session_params = {
        "customer": customer.id,
        "payment_method_types": ["card"],
        "allow_promotion_codes": True,
        "automatic_tax": {"enabled": True},
        "line_items": [
            {
                "price": price_id,
                "quantity": 1,
            }
        ],
        "mode": "subscription",
        "success_url": success_url,
        "cancel_url": cancel_url,
        "customer_update": {
            "address": "auto",
        },
        "client_reference_id": str(user.id),
        "metadata": {
            "user_id": user.id,
            "pk": pk,
            "price_id": price_id,
            "plan": plan,
        },
        "subscription_data": {"metadata": {"user_id": user.id, "plan": plan}},
    }

    try:
        checkout_session = stripe.checkout.Session.create(**session_params)
    except stripe.error.StripeError as exc:
        logger.error(
            "Stripe checkout session creation failed",
            profile_id=profile.id,
            plan=plan,
            error=str(exc),
        )
        messages.error(request, "Unable to start checkout. Please try again.")
        return redirect("pricing")

    return redirect(checkout_session.url, code=303)


@login_required
def create_customer_portal_session(request):
    user = request.user
    profile = user.profile
    if not profile.stripe_customer_id:
        messages.error(request, "No Stripe customer found for this account.")
        return redirect("pricing")

    try:
        session = stripe.billing_portal.Session.create(
            customer=profile.stripe_customer_id,
            return_url=request.build_absolute_uri(reverse("home")),
        )
    except stripe.error.StripeError as exc:
        logger.error(
            "Stripe portal session creation failed",
            profile_id=profile.id,
            stripe_customer_id=profile.stripe_customer_id,
            error=str(exc),
        )
        messages.error(request, "Unable to open the billing portal. Please try again.")
        return redirect("pricing")

    return redirect(session.url, code=303)


class AdminPanelView(UserPassesTestMixin, TemplateView):
    template_name = "pages/admin-panel.html"
    login_url = "account_login"

    def test_func(self):
        return self.request.user.is_superuser

    def handle_no_permission(self):
        messages.error(self.request, "You don't have permission to access this page.")
        return redirect("home")

    def get_context_data(self, **kwargs):
        from datetime import timedelta

        from django.contrib.auth.models import User
        from django.utils import timezone

        from apps.core.models import Feedback, Profile

        context = super().get_context_data(**kwargs)

        now = timezone.now()
        week_ago = now - timedelta(days=7)
        month_ago = now - timedelta(days=30)

        total_users = User.objects.count()
        total_profiles = Profile.objects.count()
        total_feedback = Feedback.objects.count()

        new_users_week = User.objects.filter(date_joined__gte=week_ago).count()
        new_users_month = User.objects.filter(date_joined__gte=month_ago).count()
        feedback_week = Feedback.objects.filter(created_at__gte=week_ago).count()

        recent_users = User.objects.select_related("profile").order_by("-date_joined")[:10]
        recent_feedback = Feedback.objects.select_related("profile__user").order_by("-created_at")[
            :10
        ]

        # Calculate average users per day for last 30 days
        avg_users_per_day = new_users_month / 30 if new_users_month > 0 else 0

        context.update(
            {
                "total_users": total_users,
                "total_profiles": total_profiles,
                "total_feedback": total_feedback,
                "new_users_week": new_users_week,
                "new_users_month": new_users_month,
                "feedback_week": feedback_week,
                "recent_users": recent_users,
                "recent_feedback": recent_feedback,
                "avg_users_per_day": avg_users_per_day,
            }
        )

        logger.info(
            "Admin panel accessed",
            email=self.request.user.email,
            profile_id=self.request.user.profile.id,
        )

        return context


def get_price_id_for_plan(plan):
    plan_key = (plan or "").lower()
    price_id = settings.STRIPE_PRICE_IDS.get(plan_key) or None
    return price_id


def get_or_create_stripe_customer(profile, user):
    if profile.stripe_customer_id:
        try:
            return stripe.Customer.retrieve(profile.stripe_customer_id)
        except stripe.error.InvalidRequestError as exc:
            logger.warning(
                "Stripe customer lookup failed",
                profile_id=profile.id,
                stripe_customer_id=profile.stripe_customer_id,
                error=str(exc),
            )

    customer = stripe.Customer.create(
        email=user.email,
        name=user.get_full_name() or user.username,
        metadata={"user_id": user.id},
    )
    profile.stripe_customer_id = customer.id
    profile.save(update_fields=["stripe_customer_id"])
    return customer


@csrf_exempt
def stripe_webhook(request):
    logger.info("Stripe webhook received", request=request)

    if request.method != "POST":
        return HttpResponse(status=405)

    if not settings.STRIPE_WEBHOOK_SECRET:
        logger.error("Stripe webhook secret not configured")
        return HttpResponse(status=500)

    payload = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE")
    if not sig_header:
        return HttpResponseBadRequest("Missing Stripe-Signature header")

    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=sig_header,
            secret=settings.STRIPE_WEBHOOK_SECRET,
        )
    except ValueError:
        return HttpResponseBadRequest("Invalid payload")
    except stripe.error.SignatureVerificationError:
        return HttpResponseBadRequest("Invalid signature")

    event_id = event.get("id")
    if event_id:
        cache_key = f"stripe_event:{event_id}"
        if cache.get(cache_key):
            logger.info(
                "Duplicate Stripe webhook received",
                event_type=event.get("type"),
                event_id=event_id,
            )
            return HttpResponse(status=200)

    handler = EVENT_HANDLERS.get(event.get("type"))
    if handler:
        handler(event)
    else:
        logger.info(
            "Unhandled Stripe webhook",
            event_type=event.get("type"),
            event_id=event.get("id"),
        )

    if event_id:
        cache.set(cache_key, True, timeout=60 * 60 * 24)

    return HttpResponse(status=200)
