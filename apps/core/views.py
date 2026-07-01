from urllib.parse import urlencode
from uuid import UUID

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
from django.db import IntegrityError, transaction
from django.db.models import Count, Q, Sum
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from django.views.generic import TemplateView, UpdateView

from apps.core.agent_skill import (
    ROWSET_AGENT_SETUP_INSTRUCTIONS,
    ROWSET_SKILL_INSTALL_COMMAND,
    load_rowset_features_skill_markdown,
    load_rowset_skill_markdown,
    load_rowset_use_cases_skill_markdown,
)
from apps.core.capabilities import render_rowset_llms_txt
from apps.core.forms import AgentApiKeyCreateForm, ProfileUpdateForm
from apps.core.models import AgentApiKey, Profile
from apps.core.services import create_agent_api_key, get_agent_api_key_token
from apps.core.stripe_webhooks import EVENT_HANDLERS
from apps.datasets.choices import DatasetStatus
from rowset.utils import build_absolute_public_url, get_rowset_logger

stripe.api_key = settings.STRIPE_SECRET_KEY


logger = get_rowset_logger(__name__)

AGENT_API_KEY_MASK = "***"
CREATED_AGENT_API_KEY_QUERY_PARAM = "created_agent_api_key"


def stripe_request_options():
    if settings.STRIPE_CONTEXT:
        return {"stripe_context": settings.STRIPE_CONTEXT}
    return {}


def stripe_redirect(url: str) -> HttpResponse:
    response = redirect(url)
    response.status_code = 303
    return response


def _serialize_created_agent_api_key(agent_api_key: AgentApiKey) -> dict:
    return {
        "uuid": str(agent_api_key.uuid),
        "name": agent_api_key.name,
        "access_level_label": agent_api_key.get_access_level_display(),
    }


def _created_agent_api_key_context_from_request(
    request: HttpRequest,
    profile: Profile,
) -> dict | None:
    created_agent_api_key_uuid = request.GET.get(CREATED_AGENT_API_KEY_QUERY_PARAM)
    if not created_agent_api_key_uuid:
        return None
    try:
        created_agent_api_key_uuid = UUID(created_agent_api_key_uuid)
    except ValueError:
        return None

    agent_api_key = (
        AgentApiKey.objects.filter(
            uuid=created_agent_api_key_uuid,
            profile=profile,
            revoked_at__isnull=True,
        )
        .only("uuid", "name", "access_level")
        .first()
    )
    if agent_api_key is None:
        return None
    return _serialize_created_agent_api_key(agent_api_key)


def user_settings_context(
    request: HttpRequest,
    profile: Profile,
    *,
    created_agent_api_key: dict | None = None,
) -> dict:
    user = request.user
    if created_agent_api_key is None:
        created_agent_api_key = _created_agent_api_key_context_from_request(request, profile)
    try:
        email_address = EmailAddress.objects.get_for_user(user, user.email)
    except EmailAddress.DoesNotExist:
        email_address = None

    return {
        "email_verified": email_address is None or email_address.verified,
        "resend_confirmation_url": reverse("resend_confirmation"),
        "has_subscription": profile.has_active_subscription,
        "passkey_count": Authenticator.objects.filter(
            user=user,
            type=Authenticator.Type.WEBAUTHN,
        ).count(),
        "agent_api_key_form": AgentApiKeyCreateForm(profile=profile),
        "agent_api_keys": profile.agent_api_keys.filter(revoked_at__isnull=True),
        "created_agent_api_key": created_agent_api_key,
    }


def build_agent_setup_prompt(
    request: HttpRequest,
    *,
    mask_api_key: bool = False,
    profile: Profile | None = None,
    api_key: str | None = None,
) -> str:
    mcp_url = build_absolute_public_url("/mcp/")
    rest_api_base_url = build_absolute_public_url("/api/")
    instructions_url = build_absolute_public_url(reverse("agent_instructions_rowset_mcp"))
    if profile is None:
        profile, _created = Profile.objects.get_or_create(user=request.user)
    if mask_api_key:
        api_key = AGENT_API_KEY_MASK
    elif api_key is None:
        api_key = profile.key

    return "\n".join(
        [
            "Set up Rowset for this user.",
            "",
            f"Rowset MCP URL: {mcp_url}",
            f"Rowset REST API base: {rest_api_base_url}",
            f"Rowset API key: {api_key}",
            f"Rowset skill: {instructions_url}",
            f"Rowset skill install: {ROWSET_SKILL_INSTALL_COMMAND}",
            "",
            ROWSET_AGENT_SETUP_INSTRUCTIONS,
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
        elif payment_status == "failed":
            messages.error(self.request, "Something went wrong with the payment.")

        profile, _created = Profile.objects.get_or_create(user=self.request.user)
        dashboard_datasets = profile.datasets.filter(archived_at__isnull=True).exclude(
            status=DatasetStatus.PREVIEWED
        )
        dashboard_summary = dashboard_datasets.aggregate(
            total_datasets=Count("id"),
            total_rows=Sum("row_count"),
            public_preview_count=Count("id", filter=Q(public_enabled=True)),
        )
        recent_datasets = list(
            dashboard_datasets.select_related("project", "updated_by_agent_api_key").order_by(
                "-updated_at"
            )[:5]
        )
        context["recent_datasets"] = recent_datasets
        context["dashboard_stats"] = {
            "total_datasets": dashboard_summary["total_datasets"] or 0,
            "total_projects": profile.projects.filter(archived_at__isnull=True).count(),
            "total_rows": dashboard_summary["total_rows"] or 0,
            "public_preview_count": dashboard_summary["public_preview_count"] or 0,
        }
        show_agent_setup_prompt = not profile.agent_setup_prompt_dismissed and not recent_datasets
        context["show_agent_setup_prompt"] = show_agent_setup_prompt
        if show_agent_setup_prompt:
            active_agent_api_key = profile.agent_api_keys.filter(revoked_at__isnull=True).first()
            context["agent_api_key_form"] = AgentApiKeyCreateForm(profile=profile)
            context["active_agent_api_key"] = active_agent_api_key
            if active_agent_api_key:
                context["agent_setup_prompt_masked"] = build_agent_setup_prompt(
                    self.request,
                    mask_api_key=True,
                    profile=profile,
                )
                context["agent_setup_prompt_url"] = reverse(
                    "agent_api_key_setup_prompt",
                    args=[active_agent_api_key.uuid],
                )
            context["agent_setup_prompt_dismiss_url"] = reverse("dismiss_agent_setup_prompt")
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
        context.update(user_settings_context(self.request, self.request.user.profile))
        return context


def agent_instructions_rowset_mcp(request):
    return HttpResponse(load_rowset_skill_markdown(), content_type="text/markdown; charset=utf-8")


def agent_instructions_rowset_features(request):
    return HttpResponse(
        load_rowset_features_skill_markdown(),
        content_type="text/markdown; charset=utf-8",
    )


def agent_instructions_rowset_use_cases(request):
    return HttpResponse(
        load_rowset_use_cases_skill_markdown(),
        content_type="text/markdown; charset=utf-8",
    )


def llms_txt(request):
    response = HttpResponse(
        render_rowset_llms_txt(
            site_url=build_absolute_public_url("/").rstrip("/"),
            mcp_url=build_absolute_public_url("/mcp/"),
            rest_api_base_url=build_absolute_public_url("/api/").rstrip("/"),
            api_docs_url=build_absolute_public_url("/api/docs"),
            setup_skill_url=build_absolute_public_url(reverse("agent_instructions_rowset_mcp")),
            features_skill_url=build_absolute_public_url(
                reverse("agent_instructions_rowset_features")
            ),
            use_cases_skill_url=build_absolute_public_url(
                reverse("agent_instructions_rowset_use_cases")
            ),
        ),
        content_type="text/plain; charset=utf-8",
    )
    response["Cache-Control"] = "public, max-age=300"
    return response


@login_required
@require_GET
def agent_setup_prompt(request):
    profile, _created = Profile.objects.get_or_create(user=request.user)
    response = JsonResponse({"prompt": build_agent_setup_prompt(request, profile=profile)})
    response["Cache-Control"] = "no-store"
    return response


@login_required
@require_GET
def agent_api_key_setup_prompt(request, agent_api_key_uuid):
    profile = request.user.profile
    agent_api_key = get_object_or_404(
        AgentApiKey,
        uuid=agent_api_key_uuid,
        profile=profile,
        revoked_at__isnull=True,
    )
    api_key = get_agent_api_key_token(agent_api_key)
    if api_key is None:
        api_key = f"[full {agent_api_key.name} key with prefix {agent_api_key.key_prefix}...]"
    response = JsonResponse(
        {
            "prompt": build_agent_setup_prompt(
                request,
                profile=profile,
                api_key=api_key,
            )
        }
    )
    response["Cache-Control"] = "no-store"
    return response


@login_required
@require_GET
def agent_api_key_token(request, agent_api_key_uuid):
    agent_api_key = get_object_or_404(
        AgentApiKey,
        uuid=agent_api_key_uuid,
        profile=request.user.profile,
        revoked_at__isnull=True,
    )
    api_key = get_agent_api_key_token(agent_api_key)
    if api_key is None:
        return JsonResponse({"error": "API key token is unavailable."}, status=404)
    response = JsonResponse({"api_key": api_key})
    response["Cache-Control"] = "no-store"
    return response


@login_required
@require_POST
def create_agent_api_key_view(request):
    profile = request.user.profile
    return_home = request.POST.get("next") == "home"
    form = AgentApiKeyCreateForm(request.POST, profile=profile)
    if not form.is_valid():
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
        if return_home:
            return redirect("home")
        return redirect("settings")

    try:
        credential = create_agent_api_key(
            profile,
            form.cleaned_data["name"],
            form.cleaned_data["access_level"],
        )
    except IntegrityError:
        messages.error(request, "An API key with this name already exists.")
        if return_home:
            return redirect("home")
        return redirect("settings")

    messages.success(
        request,
        f"Created an API key for {credential.agent_api_key.name}.",
    )
    if return_home:
        return redirect("home")
    context = {
        "object": profile,
        "profile": profile,
        "form": ProfileUpdateForm(instance=profile),
        **user_settings_context(
            request,
            profile,
            created_agent_api_key=_serialize_created_agent_api_key(credential.agent_api_key),
        ),
    }
    response = render(request, UserSettingsView.template_name, context)
    response["Cache-Control"] = "no-store"
    return response


@login_required
@require_POST
def revoke_agent_api_key_view(request, agent_api_key_uuid):
    agent_api_key = get_object_or_404(
        AgentApiKey,
        uuid=agent_api_key_uuid,
        profile=request.user.profile,
    )
    if agent_api_key.revoked_at is None:
        agent_api_key.revoked_at = timezone.now()
        agent_api_key.save(update_fields=["revoked_at", "updated_at"])
        messages.success(request, f"Revoked {agent_api_key.name}.")
    else:
        messages.info(request, f"{agent_api_key.name} is already revoked.")

    settings_url = reverse("settings")
    created_agent_api_key_uuid = request.POST.get("created_agent_api_key_uuid")
    if created_agent_api_key_uuid:
        created_query = urlencode(
            {CREATED_AGENT_API_KEY_QUERY_PARAM: created_agent_api_key_uuid}
        )
        settings_url = f"{settings_url}?{created_query}"
    return redirect(settings_url)


@login_required
@require_POST
def dismiss_agent_setup_prompt(request):
    profile, _created = Profile.objects.get_or_create(user=request.user)
    if not profile.agent_setup_prompt_dismissed:
        profile.agent_setup_prompt_dismissed = True
        profile.save(update_fields=["agent_setup_prompt_dismissed", "updated_at"])
    return redirect("home")


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
        checkout_session = stripe.checkout.Session.create(
            **session_params,
            **stripe_request_options(),
        )
    except stripe.error.StripeError as exc:
        logger.error(
            "Stripe checkout session creation failed",
            profile_id=profile.id,
            plan=plan,
            error=str(exc),
        )
        messages.error(request, "Unable to start checkout. Please try again.")
        return redirect("pricing")

    return stripe_redirect(checkout_session.url)


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
            **stripe_request_options(),
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

    return stripe_redirect(session.url)


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
        from apps.datasets.models import Dataset, Project

        context = super().get_context_data(**kwargs)

        now = timezone.now()
        week_ago = now - timedelta(days=7)
        month_ago = now - timedelta(days=30)
        visible_datasets = Dataset.objects.filter(archived_at__isnull=True).exclude(
            status=DatasetStatus.PREVIEWED
        )

        total_users = User.objects.count()
        profile_count = Profile.objects.count()
        total_feedback = Feedback.objects.count()
        total_datasets = visible_datasets.count()
        total_projects = Project.objects.count()
        dataset_summary = visible_datasets.aggregate(
            total_rows=Sum("row_count"),
            public_preview_count=Count("id", filter=Q(public_enabled=True)),
        )

        new_users_week = User.objects.filter(date_joined__gte=week_ago).count()
        new_users_month = User.objects.filter(date_joined__gte=month_ago).count()
        feedback_week = Feedback.objects.filter(created_at__gte=week_ago).count()
        datasets_week = visible_datasets.filter(created_at__gte=week_ago).count()
        datasets_month = visible_datasets.filter(created_at__gte=month_ago).count()
        projects_week = Project.objects.filter(created_at__gte=week_ago).count()
        projects_month = Project.objects.filter(created_at__gte=month_ago).count()

        recent_users = User.objects.select_related("profile").order_by("-date_joined")[:10]
        recent_feedback = Feedback.objects.select_related("profile__user").order_by("-created_at")[
            :10
        ]
        recent_datasets = visible_datasets.select_related("profile__user", "project").order_by(
            "-created_at"
        )[:10]
        recent_projects = (
            Project.objects.select_related("profile__user")
            .annotate(
                dataset_count=Count(
                    "datasets",
                    filter=Q(datasets__archived_at__isnull=True)
                    & ~Q(datasets__status=DatasetStatus.PREVIEWED),
                )
            )
            .order_by("-created_at")[:10]
        )

        # Calculate average users per day for last 30 days
        avg_users_per_day = new_users_month / 30 if new_users_month > 0 else 0

        context.update(
            {
                "total_users": total_users,
                "profile_count": profile_count,
                "total_feedback": total_feedback,
                "total_datasets": total_datasets,
                "total_projects": total_projects,
                "total_rows": dataset_summary["total_rows"] or 0,
                "public_preview_count": dataset_summary["public_preview_count"] or 0,
                "new_users_week": new_users_week,
                "new_users_month": new_users_month,
                "feedback_week": feedback_week,
                "datasets_week": datasets_week,
                "datasets_month": datasets_month,
                "projects_week": projects_week,
                "projects_month": projects_month,
                "recent_users": recent_users,
                "recent_feedback": recent_feedback,
                "recent_datasets": recent_datasets,
                "recent_projects": recent_projects,
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
            return stripe.Customer.retrieve(
                profile.stripe_customer_id,
                **stripe_request_options(),
            )
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
        **stripe_request_options(),
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
