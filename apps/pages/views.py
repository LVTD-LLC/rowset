from allauth.account.views import SignupByPasskeyView, SignupView
from django.conf import settings
from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.generic import TemplateView
from django_q.tasks import async_task

from apps.core.analytics import ROWSET_SIGNUP_COMPLETED, track_activation_event
from apps.core.models import Profile
from apps.pages.blog import (
    BLOG_DESCRIPTION,
    BLOG_TITLE,
    BlogPostNotFound,
    BlogPostValidationError,
    blog_index_schema,
    blog_index_url,
    blog_post_schema,
    default_blog_image_url,
    get_blog_post,
    list_blog_posts,
)
from apps.pages.blog import (
    json_ld as blog_json_ld,
)
from apps.pages.content import get_content_section, render_content_page, render_content_section
from apps.pages.schema import (
    article_schema,
    breadcrumb_list_schema,
    json_ld,
    organization_schema,
    product_schema,
    software_application_schema,
    use_case_article_schema,
    use_case_item_list_schema,
)
from apps.pages.use_cases import get_use_case_page, get_use_case_pages
from rowset.utils import build_absolute_public_url, get_rowset_logger

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

        context["schema_json"] = json_ld(product_schema())
        return context


def docs_home_view(request):
    return render_content_section(request, "docs")


def docs_page_view(request, slug):
    return render_content_page(request, "docs", slug)


def tutorials_home_view(request):
    return render_content_section(request, "tutorials")


def tutorial_page_view(request, slug):
    return render_content_page(request, "tutorials", slug)


def blog_posts_view(request):
    blog_posts = list_blog_posts()
    return render(
        request,
        "blog/blog_posts.html",
        {
            "blog_title": BLOG_TITLE,
            "blog_description": BLOG_DESCRIPTION,
            "blog_posts": blog_posts,
            "canonical_url": blog_index_url(),
            "og_image_url": default_blog_image_url(),
            "schema_json": blog_json_ld(blog_index_schema(blog_posts)),
        },
    )


def blog_post_view(request, slug):
    try:
        blog_post = get_blog_post(slug)
    except (BlogPostNotFound, BlogPostValidationError) as exc:
        raise Http404("Blog post not found") from exc

    return render(
        request,
        "blog/blog_post.html",
        {
            "blog_post": blog_post,
            "canonical_url": blog_post.canonical_url,
            "schema_json": blog_json_ld(blog_post_schema(blog_post)),
        },
    )


class HowToIndexView(TemplateView):
    template_name = "pages/content/how_to_index.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["section"] = get_content_section("how-to")
        context["use_case_pages"] = get_use_case_pages()
        context["schema_json"] = json_ld(use_case_item_list_schema(context["use_case_pages"]))
        context["docs_base_template"] = (
            "base_app.html" if self.request.user.is_authenticated else "base_landing.html"
        )
        return context


class HowToUseCaseDetailView(TemplateView):
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
        context["docs_base_template"] = (
            "base_app.html" if self.request.user.is_authenticated else "base_landing.html"
        )
        return context


def how_to_guide_view(request, slug):
    try:
        return render_content_page(request, "how-to", slug)
    except Http404:
        return HowToUseCaseDetailView.as_view()(request, slug=slug)


def explanations_home_view(request):
    return render_content_section(
        request,
        "explanations",
        extra_pages=(
            {
                "title": "Database MCP server: when to use Rowset instead",
                "description": (
                    "A practical guide to choosing between direct database MCP servers "
                    "and Rowset's hosted MCP dataset backend."
                ),
                "url": reverse("explanation_page", kwargs={"slug": "database-mcp-server"}),
            },
        ),
    )


def explanation_page_view(request, slug):
    if slug == "database-mcp-server":
        return DatabaseMcpServerExplanationView.as_view()(request)
    return render_content_page(request, "explanations", slug)


class DatabaseMcpServerExplanationView(TemplateView):
    template_name = "pages/explanations/database-mcp-server.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        path = reverse("explanation_page", kwargs={"slug": "database-mcp-server"})
        context["mcp_url"] = build_absolute_public_url("/mcp/")
        context["schema_json"] = json_ld(
            [
                article_schema(
                    headline="Database MCP server: when to use Rowset instead",
                    description=(
                        "A practical guide to choosing between direct database MCP servers "
                        "and Rowset's hosted MCP dataset backend for AI-agent workflows."
                    ),
                    path=path,
                    date_published="2026-07-05",
                    date_modified="2026-07-05",
                ),
                breadcrumb_list_schema(
                    (
                        ("Home", "/"),
                        ("Explanations", reverse("explanations_home")),
                        ("Database MCP server", path),
                    )
                ),
            ]
        )
        return context


class AirtableAlternativesView(TemplateView):
    template_name = "pages/alternatives/airtable.html"


class PrivacyPolicyView(TemplateView):
    template_name = "pages/privacy-policy.html"


class TermsOfServiceView(TemplateView):
    template_name = "pages/terms-of-service.html"
