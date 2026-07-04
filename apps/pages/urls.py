from django.urls import path

from apps.pages import views
from apps.pages.seo import redirect_without_trailing_slash

urlpatterns = [
    path("", views.LandingPageView.as_view(), name="landing"),
    path("privacy-policy", views.PrivacyPolicyView.as_view(), name="privacy_policy"),
    path(
        "privacy-policy/",
        redirect_without_trailing_slash,
        {"path": "privacy-policy"},
        name="privacy_policy_slash_redirect",
    ),
    path("terms-of-service", views.TermsOfServiceView.as_view(), name="terms_of_service"),
    path(
        "terms-of-service/",
        redirect_without_trailing_slash,
        {"path": "terms-of-service"},
        name="terms_of_service_slash_redirect",
    ),
    path("pricing", views.PricingView.as_view(), name="pricing"),
    path(
        "pricing/",
        redirect_without_trailing_slash,
        {"path": "pricing"},
        name="pricing_slash_redirect",
    ),
    path("use-cases", views.UseCasesIndexView.as_view(), name="use_cases"),
    path(
        "use-cases/",
        redirect_without_trailing_slash,
        {"path": "use-cases"},
        name="use_cases_slash_redirect",
    ),
    path("use-cases/<slug:slug>", views.UseCaseDetailView.as_view(), name="use_case_detail"),
    path(
        "use-cases/<slug:slug>/",
        redirect_without_trailing_slash,
        {"path": "use-cases"},
        name="use_case_detail_slash_redirect",
    ),
]
