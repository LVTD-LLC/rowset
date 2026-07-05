from django.urls import path
from django.views.generic import RedirectView, TemplateView

from apps.pages import views


def canonical_no_slash_path(route, view, *, name):
    return (
        path(route, view, name=name),
        path(
            f"{route}/",
            RedirectView.as_view(pattern_name=name, permanent=True, query_string=True),
            name=f"{name}_slash_redirect",
        ),
    )


urlpatterns = [
    path("", views.LandingPageView.as_view(), name="landing"),
    *canonical_no_slash_path(
        "privacy-policy",
        views.PrivacyPolicyView.as_view(),
        name="privacy_policy",
    ),
    *canonical_no_slash_path(
        "terms-of-service",
        views.TermsOfServiceView.as_view(),
        name="terms_of_service",
    ),
    *canonical_no_slash_path("pricing", views.PricingView.as_view(), name="pricing"),
    *canonical_no_slash_path(
        "use-cases",
        views.UseCasesIndexView.as_view(),
        name="use_cases",
    ),
    *canonical_no_slash_path(
        "use-cases/<slug:slug>",
        views.UseCaseDetailView.as_view(),
        name="use_case_detail",
    ),
    *canonical_no_slash_path(
        "playbooks/database-mcp-server",
        views.DatabaseMcpServerPlaybookView.as_view(),
        name="database_mcp_server_playbook",
    ),
    *canonical_no_slash_path(
        "uses",
        TemplateView.as_view(template_name="pages/uses.html"),
        name="uses",
    ),
]
