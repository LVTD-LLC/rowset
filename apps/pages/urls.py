from django.urls import path

from apps.pages import views
from apps.pages.seo import canonical_no_slash_path

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
    *canonical_no_slash_path("use-cases", views.UseCasesIndexView.as_view(), name="use_cases"),
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
]
