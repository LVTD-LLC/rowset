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
    path("docs/", views.docs_home_view, name="docs_home"),
    path("docs/<slug:slug>/", views.docs_page_view, name="docs_page"),
    path("tutorials/", views.tutorials_home_view, name="tutorials_home"),
    path("tutorials/<slug:slug>/", views.tutorial_page_view, name="tutorial_page"),
    path(
        "how-to/",
        views.HowToIndexView.as_view(),
        name="how_to_guides",
    ),
    path(
        "how-to/<slug:slug>/",
        views.how_to_guide_view,
        name="how_to_guide",
    ),
    path("explanations/", views.explanations_home_view, name="explanations_home"),
    path("explanations/<slug:slug>/", views.explanation_page_view, name="explanation_page"),
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
