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
from django.http import (
    HttpRequest,
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseNotFound,
    JsonResponse,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from django.views.defaults import server_error as default_server_error
from django.views.generic import TemplateView, UpdateView
from django_htmx.http import HttpResponseClientRedirect

from apps.core.admin_dashboard import ADMIN_DASHBOARD_PERIODS, build_admin_dashboard_context
from apps.core.agent_skill import (
    ROWSET_AGENT_SETUP_INSTRUCTIONS,
    ROWSET_SKILL_INSTALL_COMMAND,
    load_rowset_features_skill_markdown,
    load_rowset_setup_skill_markdown,
    load_rowset_skill_markdown,
    load_rowset_use_cases_skill_markdown,
)
from apps.core.analytics import (
    ROWSET_CHECKOUT_STARTED,
    track_account_deleted_event,
    track_activation_event,
)
from apps.core.choices import TrialReward
from apps.core.forms import AgentApiKeyCreateForm, ProfileUpdateForm
from apps.core.models import AgentApiKey, Profile
from apps.core.services import (
    create_agent_api_key,
    get_agent_api_key_token,
    get_or_create_profile_for_user,
)
from apps.core.stripe_webhooks import EVENT_HANDLERS
from apps.core.trials import (
    TRIAL_REWARD_DEFINITIONS,
    TrialRewardUnavailableError,
    claim_trial_reward,
    get_trial_status,
)
from apps.datasets.views import DATASET_VIEW_MODE_GROUPED, DatasetListView
from rowset.utils import build_absolute_public_url, get_rowset_logger

stripe.api_key = settings.STRIPE_SECRET_KEY


logger = get_rowset_logger(__name__)

AGENT_API_KEY_MASK = "***"
CREATED_AGENT_API_KEY_QUERY_PARAM = "created_agent_api_key"
SERVER_ERROR_REDIRECT_MESSAGE = "Something went wrong. You have been redirected."
PROGRAMMATIC_ERROR_PATH_PREFIXES = ("/api", "/mcp")


def _is_programmatic_error_request(request: HttpRequest) -> bool:
    path = request.path_info or request.path
    return any(
        path == prefix or path.startswith(f"{prefix}/")
        for prefix in PROGRAMMATIC_ERROR_PATH_PREFIXES
    )


def server_error(request: HttpRequest):
    if _is_programmatic_error_request(request):
        return default_server_error(request)

    user = getattr(request, "user", None)
    target_url = reverse("home" if user and user.is_authenticated else "landing")
    messages.error(request, SERVER_ERROR_REDIRECT_MESSAGE, fail_silently=True)

    if getattr(request, "htmx", False):
        return HttpResponseClientRedirect(target_url)
    return redirect(target_url)


def page_not_found(_request: HttpRequest, exception: Exception):  # noqa: ARG001
    """Render 404s without request context or database-backed context processors."""
    return HttpResponseNotFound(render_to_string("404.html"))


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
        "trial_status": get_trial_status(profile),
        "trial_ends_at": profile.trial_ends_at,
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
    setup_instructions_url = build_absolute_public_url(reverse("agent_instructions_rowset_setup"))
    llms_txt_url = build_absolute_public_url(reverse("llms_txt"))
    api_docs_url = build_absolute_public_url("/api/docs")
    cli_docs_url = build_absolute_public_url("/docs/use-cli.md")
    docs_url = build_absolute_public_url(reverse("docs_home"))
    blog_url = build_absolute_public_url(reverse("blog_posts"))
    trial_rewards_url = build_absolute_public_url(reverse("trial_rewards"))
    if profile is None:
        profile = get_or_create_profile_for_user(request.user)
    if mask_api_key:
        api_key = AGENT_API_KEY_MASK
    elif api_key is None:
        api_key = AGENT_API_KEY_MASK

    return "\n".join(
        [
            "Set up Rowset for this user.",
            "",
            f"Rowset MCP URL: {mcp_url}",
            f"Rowset REST API base: {rest_api_base_url}",
            f"Rowset CLI guide: {cli_docs_url}",
            f"Rowset API key: {api_key}",
            f"Rowset setup skill: {setup_instructions_url}",
            f"Rowset skill: {instructions_url}",
            f"Rowset skill install: {ROWSET_SKILL_INSTALL_COMMAND}",
            f"Rowset current docs index: {llms_txt_url}",
            f"Rowset docs: {docs_url}",
            f"Rowset blog: {blog_url}",
            f"Rowset current API docs: {api_docs_url}",
            f"Rowset current capabilities: {rest_api_base_url}capabilities",
            f"Rowset trial rewards: {trial_rewards_url}",
            "",
            ROWSET_AGENT_SETUP_INSTRUCTIONS,
        ]
    )


class HomeView(DatasetListView):
    login_url = "account_login"
    template_name = "pages/home.html"
    paginate_by = 10
    default_view_mode = DATASET_VIEW_MODE_GROUPED
    view_mode_options = ((DATASET_VIEW_MODE_GROUPED, "Grouped by project/section"),)
    dataset_list_url_name = "home"
    dataset_list_eyebrow = "Home"
    dataset_list_title = "Datasets by project"
    dataset_list_description = (
        "Browse every active dataset your agents have created, grouped by project and section."
    )
    dataset_search_placeholder = "Name, project, or section"

    def get_profile(self):
        if not hasattr(self, "_profile"):
            self._profile = get_or_create_profile_for_user(self.request.user)
        return self._profile

    def get_grouped_ordering(self):
        if self.get_selected_sort() == "recent":
            return self.sort_ordering["recent"]
        return super().get_grouped_ordering()

    def paginate_queryset(self, queryset, page_size):
        paginator = self.get_paginator(
            queryset,
            page_size,
            orphans=self.get_paginate_orphans(),
            allow_empty_first_page=self.get_allow_empty(),
        )
        page = paginator.page(1)
        return paginator, page, page.object_list, page.has_other_pages()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        payment_status = self.request.GET.get("payment")
        if payment_status == "success":
            messages.success(self.request, "Thanks for subscribing, I hope you enjoy the app!")
        elif payment_status == "failed":
            messages.error(self.request, "Something went wrong with the payment.")

        profile = self.get_profile()
        context["dashboard_stats"] = context["dataset_stats"]
        show_agent_setup_prompt = profile.setup_completed_at is None
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
        context["profile"] = self.request.user.profile
        context.update(user_settings_context(self.request, self.request.user.profile))
        return context

    def post(self, request, *args, **kwargs):
        if request.POST.get("settings_section") == "design":
            profile = self.get_object()
            profile.choice_colorization_enabled = (
                request.POST.get("choice_colorization_enabled") == "on"
            )
            profile.save(update_fields=["choice_colorization_enabled", "updated_at"])
            messages.success(request, "Design settings updated")
            return redirect("settings")
        return super().post(request, *args, **kwargs)


def _trial_reward_cards(profile: Profile) -> list[dict]:
    claimed_rewards = set(profile.trial_reward_claims.values_list("reward", flat=True))
    email_verified = EmailAddress.objects.filter(user=profile.user, verified=True).exists()
    subscribed = profile.has_active_subscription
    return [
        {
            "key": definition.reward.value,
            "title": definition.title,
            "description": definition.description,
            "action_label": definition.action_label,
            "url": definition.url,
            "days": definition.days,
            "claimed": definition.reward.value in claimed_rewards,
            "available": not subscribed
            and (definition.reward != TrialReward.EMAIL_VERIFIED or email_verified),
        }
        for definition in TRIAL_REWARD_DEFINITIONS
    ]


def _trial_rewards_context(profile: Profile) -> dict:
    reward_cards = _trial_reward_cards(profile)
    completed_count = sum(card["claimed"] for card in reward_cards)
    return {
        "reward_cards": reward_cards,
        "completed_count": completed_count,
        "reward_count": len(reward_cards),
        "earned_days": sum(card["days"] for card in reward_cards if card["claimed"]),
        "trial_status": get_trial_status(profile),
        "trial_ends_at": profile.trial_ends_at,
    }


@login_required
@require_GET
def trial_rewards(request):
    return render(
        request,
        "pages/trial-rewards.html",
        _trial_rewards_context(request.user.profile),
    )


@login_required
@require_POST
def claim_trial_reward_view(request, reward):
    try:
        reward = TrialReward(reward)
    except ValueError:
        return HttpResponseBadRequest("Unknown trial reward.")

    claim_error = None
    try:
        result = claim_trial_reward(request.user.profile, reward)
    except TrialRewardUnavailableError as exc:
        result = None
        claim_error = str(exc)

    if not request.htmx:
        if claim_error:
            messages.error(request, claim_error)
        elif result.created:
            messages.success(
                request,
                f"Added {result.claim.days} extra days to your Rowset trial.",
            )
        else:
            messages.info(request, "You already claimed this trial reward.")
        return redirect("trial_rewards")

    context = _trial_rewards_context(request.user.profile)
    card = next(card for card in context["reward_cards"] if card["key"] == reward.value)
    card["claim_error"] = claim_error
    card["claim_was_pending"] = bool(result and result.claim.applied_at is None)
    return render(
        request,
        "components/trial-rewards-content.html",
        context,
    )


def agent_instructions_rowset_mcp(request):
    return HttpResponse(load_rowset_skill_markdown(), content_type="text/markdown; charset=utf-8")


def agent_instructions_rowset_setup(request):
    return HttpResponse(
        load_rowset_setup_skill_markdown(),
        content_type="text/markdown; charset=utf-8",
    )


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
        created_query = urlencode({CREATED_AGENT_API_KEY_QUERY_PARAM: created_agent_api_key_uuid})
        settings_url = f"{settings_url}?{created_query}"
    return redirect(settings_url)


@login_required
def resend_confirmation_email(request):
    user = request.user

    try:
        email_address = EmailAddress.objects.get_for_user(user, user.email)

        if not email_address:
            messages.error(request, "No email address found for your account.")
            logger.warning(
                "email.confirmation.completed",
                user_id=user.id,
                outcome="success",
                **{"operation.status": "skipped"},
                reason="address_missing",
            )
            return redirect("settings")

        if email_address.verified:
            messages.info(request, "Your email is already verified.")
            logger.info(
                "email.confirmation.completed",
                user_id=user.id,
                outcome="success",
                **{"operation.status": "skipped"},
                reason="already_verified",
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
            "email.confirmation.completed",
            user_id=user.id,
            outcome="success",
        )

    except Exception as exc:
        messages.error(request, "Failed to send confirmation email. Please try again later.")
        logger.error(
            "email.confirmation.completed",
            user_id=user.id,
            outcome="failure",
            error_type=type(exc).__name__,
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
        track_account_deleted_event(
            user.profile,
            session_id=(
                request.headers.get("X-PostHog-Session-ID")
                or request.POST.get("posthog_session_id")
            ),
        )
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
            error_type=type(exc).__name__,
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
            error_type=type(exc).__name__,
        )
        messages.error(request, "Unable to start checkout. Please try again.")
        return redirect("pricing")

    track_activation_event(
        profile,
        ROWSET_CHECKOUT_STARTED,
        {"plan": plan, "checkout_mode": "subscription"},
        source_function="create_checkout_session",
        session_id=(
            request.headers.get("X-PostHog-Session-ID") or request.POST.get("posthog_session_id")
        ),
    )
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
            error_type=type(exc).__name__,
        )
        messages.error(request, "Unable to open the billing portal. Please try again.")
        return redirect("pricing")

    return stripe_redirect(session.url)


class AdminPanelView(UserPassesTestMixin, TemplateView):
    template_name = "pages/admin-panel.html"
    login_url = "account_login"

    def get_template_names(self):
        if self.request.htmx:
            return ["components/admin-dashboard.html"]
        return super().get_template_names()

    def test_func(self):
        return self.request.user.is_superuser

    def handle_no_permission(self):
        messages.error(self.request, "You don't have permission to access this page.")
        return redirect("home")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        try:
            period_days = int(self.request.GET.get("period", ADMIN_DASHBOARD_PERIODS[0]))
        except TypeError:
            period_days = ADMIN_DASHBOARD_PERIODS[0]
        except ValueError:
            period_days = ADMIN_DASHBOARD_PERIODS[0]
        context.update(build_admin_dashboard_context(period_days))

        logger.info(
            "Admin panel accessed",
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
                error_type=type(exc).__name__,
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
