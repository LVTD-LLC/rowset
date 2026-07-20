from allauth.account.views import SignupByPasskeyView, SignupView
from django.contrib import messages
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.generic import TemplateView

from apps.core.analytics import ROWSET_SIGNUP_COMPLETED, track_activation_event
from apps.core.attribution import (
    ANALYTICS_CONSENT_COOKIE,
    ATTRIBUTION_COOKIE,
    sync_profile_marketing_attribution,
)
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
from apps.pages.comparisons import get_comparison_page, render_comparison_markdown
from apps.pages.content import render_content_page
from apps.pages.llms import render_llms_txt
from apps.pages.public_markdown import (
    build_ai_reader_context,
    build_public_markdown_context,
    markdown_response,
    render_blog_markdown,
    render_changelog_html,
    render_changelog_markdown,
    render_content_markdown,
    render_public_page_markdown,
)
from apps.pages.schema import (
    article_schema,
    breadcrumb_list_schema,
    faq_page_schema,
    json_ld,
    organization_schema,
    product_schema,
    software_application_schema,
)
from apps.pages.search import build_canonical_url, search_robots_policy
from apps.pages.use_cases import get_use_case_pages
from rowset.utils import build_absolute_public_url, get_rowset_logger

logger = get_rowset_logger(__name__)

SOCIAL_PROOF_SITES = (
    {"name": "djass.dev", "icon": "vendors/images/landing/customer-icons/djass.svg"},
    {"name": "awesome.lvtd.dev", "icon": "vendors/images/landing/customer-icons/awesome.svg"},
    {
        "name": "builtwithdjango.com",
        "icon": "vendors/images/landing/customer-icons/builtwithdjango.png",
    },
    {
        "name": "gettjalerts.com",
        "icon": "vendors/images/landing/customer-icons/gettjalerts.png",
    },
    {
        "name": "gettalentleads.com",
        "icon": "vendors/images/landing/customer-icons/gettalentleads.png",
    },
    {"name": "pagefresh.lvtd.dev", "icon": "vendors/images/landing/customer-icons/pagefresh.svg"},
    {
        "name": "pgsandbox-mcp.lvtd.dev",
        "icon": "vendors/images/landing/customer-icons/pgsandbox-mcp.svg",
    },
)


class PublicMarkdownContextMixin:
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(build_public_markdown_context(getattr(self.request, "path", "/")))
        return context


class LandingPageView(PublicMarkdownContextMixin, TemplateView):
    template_name = "pages/landing-page.html"

    def get(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect("home")
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        payment_status = self.request.GET.get("payment")
        if payment_status == "success":
            messages.success(
                self.request,
                "Thanks for subscribing, I hope you enjoy the app!",
            )
        elif payment_status == "failed":
            messages.error(self.request, "Checkout was canceled. You weren’t charged.")

        context["use_case_pages"] = get_use_case_pages()
        context["social_proof_sites"] = SOCIAL_PROOF_SITES
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

        if self.request.COOKIES.get(ANALYTICS_CONSENT_COOKIE) == "granted":
            sync_profile_marketing_attribution(
                profile,
                self.request.COOKIES.get(ATTRIBUTION_COOKIE),
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
    tracking_source_name = "password"


class AccountSignupByPasskeyView(SignupTrackingMixin, SignupByPasskeyView):
    template_name = "account/signup_by_passkey.html"
    tracking_source_name = "passkey"


class PricingView(PublicMarkdownContextMixin, TemplateView):
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
    return redirect("docs_page", slug="quickstart", permanent=True)


def docs_page_view(request, slug):
    if slug == "database-mcp-server":
        return DatabaseMcpServerExplanationView.as_view()(request)
    return render_content_page(request, "docs", slug)


def use_cases_view(request):
    return render_content_page(request, "use-cases", "index")


def use_case_page_view(request, slug):
    return render_content_page(request, "use-cases", slug)


def public_page_markdown(request, page_slug):
    return markdown_response(render_public_page_markdown(page_slug))


def content_page_markdown(request, section_slug, page_slug):
    return markdown_response(render_content_markdown(section_slug, page_slug))


def llms_txt(request):
    response = HttpResponse(render_llms_txt(), content_type="text/plain; charset=utf-8")
    response["Cache-Control"] = "public, max-age=300"
    return response


def changelog_view(request):
    path = reverse("changelog")
    return render(
        request,
        "pages/changelog.html",
        {
            "changelog_html": render_changelog_html(),
            "canonical_url": build_canonical_url(path),
            "docs_base_template": (
                "base_app.html" if request.user.is_authenticated else "base_landing.html"
            ),
            **build_public_markdown_context(path),
        },
    )


def changelog_markdown(request):
    return markdown_response(render_changelog_markdown())


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
            "docs_base_template": (
                "base_app.html" if request.user.is_authenticated else "base_landing.html"
            ),
            **build_public_markdown_context(reverse("blog_posts")),
        },
    )


def blog_post_view(request, slug):
    try:
        blog_post = get_blog_post(slug)
    except (BlogPostNotFound, BlogPostValidationError) as exc:
        raise Http404("Blog post not found") from exc

    path = reverse("blog_post", kwargs={"slug": blog_post.slug})
    return render(
        request,
        "blog/blog_post.html",
        {
            "blog_post": blog_post,
            "canonical_url": blog_post.canonical_url,
            "search_robots_policy": search_robots_policy(blog_post.robots),
            "schema_json": blog_json_ld(blog_post_schema(blog_post)),
            "docs_base_template": (
                "base_app.html" if request.user.is_authenticated else "base_landing.html"
            ),
            **build_ai_reader_context(path),
        },
    )


def blog_post_markdown(request, slug):
    try:
        blog_post = get_blog_post(slug)
    except (BlogPostNotFound, BlogPostValidationError) as exc:
        raise Http404("Blog post not found") from exc

    return markdown_response(render_blog_markdown(blog_post))


def comparison_page_view(request, slug):
    comparison_page = get_comparison_page(slug)
    path = comparison_page.get_absolute_url()
    return render(
        request,
        "pages/comparisons/comparison_page.html",
        {
            "comparison_page": comparison_page,
            "canonical_url": build_canonical_url(path),
            "docs_base_template": (
                "base_app.html" if request.user.is_authenticated else "base_landing.html"
            ),
            "schema_json": json_ld(
                [
                    article_schema(
                        headline=comparison_page.title,
                        description=comparison_page.description,
                        path=path,
                        date_published=comparison_page.published_at.isoformat(),
                        date_modified=comparison_page.updated_at.isoformat(),
                    ),
                    breadcrumb_list_schema((("Home", "/"), (comparison_page.title, path))),
                    faq_page_schema(comparison_page.faqs),
                ]
            ),
            **build_ai_reader_context(path),
        },
    )


def comparison_page_markdown(request, slug):
    return markdown_response(render_comparison_markdown(get_comparison_page(slug)))


class DatabaseMcpServerExplanationView(TemplateView):
    template_name = "pages/explanations/database-mcp-server.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        path = reverse("docs_page", kwargs={"slug": "database-mcp-server"})
        context["mcp_url"] = build_absolute_public_url("/mcp/")
        context.update(build_ai_reader_context(path))
        context["docs_base_template"] = (
            "base_app.html" if self.request.user.is_authenticated else "base_landing.html"
        )
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
                        ("Docs", reverse("docs_page", kwargs={"slug": "quickstart"})),
                        ("Database MCP server", path),
                    )
                ),
            ]
        )
        return context


class PrivacyPolicyView(PublicMarkdownContextMixin, TemplateView):
    template_name = "pages/privacy-policy.html"


class TermsOfServiceView(PublicMarkdownContextMixin, TemplateView):
    template_name = "pages/terms-of-service.html"


class UsesView(PublicMarkdownContextMixin, TemplateView):
    template_name = "pages/uses.html"
