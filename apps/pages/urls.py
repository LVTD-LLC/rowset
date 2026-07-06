from django.urls import path
from django.views.generic import TemplateView

from apps.pages import views

urlpatterns = [
    path("", views.LandingPageView.as_view(), name="landing"),
    path("use-cases/", views.use_cases_view, name="use_cases"),
    path("use-cases/<slug:slug>/", views.use_case_page_view, name="use_case_page"),
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
    path("blog/", views.blog_posts_view, name="blog_posts"),
    path("blog/<slug:slug>", views.blog_post_view, name="blog_post"),
    path(
        "uses/",
        TemplateView.as_view(template_name="pages/uses.html"),
        name="uses",
    ),
]
