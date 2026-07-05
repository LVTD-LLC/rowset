from django.urls import path
from django.views.generic import TemplateView

from apps.pages import views

urlpatterns = [
    path("", views.LandingPageView.as_view(), name="landing"),
    path(
        "privacy-policy/",
        views.PrivacyPolicyView.as_view(),
        name="privacy_policy",
    ),
    path(
        "terms-of-service/",
        views.TermsOfServiceView.as_view(),
        name="terms_of_service",
    ),
    path("pricing/", views.PricingView.as_view(), name="pricing"),
    path(
        "use-cases/",
        views.UseCasesIndexView.as_view(),
        name="use_cases",
    ),
    path(
        "use-cases/<slug:slug>/",
        views.UseCaseDetailView.as_view(),
        name="use_case_detail",
    ),
    path(
        "playbooks/database-mcp-server/",
        views.DatabaseMcpServerPlaybookView.as_view(),
        name="database_mcp_server_playbook",
    ),
    path(
        "alternatives/airtable/",
        views.AirtableAlternativesView.as_view(),
        name="airtable_alternatives",
    ),
    path(
        "uses/",
        TemplateView.as_view(template_name="pages/uses.html"),
        name="uses",
    ),
]
