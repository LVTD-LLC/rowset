from django.urls import path

from apps.pages import views

urlpatterns = [
    path("", views.LandingPageView.as_view(), name="landing"),
    path("llms.txt", views.llms_txt, name="llms_txt"),
    path(
        "docs.md",
        views.content_page_markdown,
        {"section_slug": "docs", "page_slug": "quickstart"},
        name="content_page_markdown",
    ),
    path(
        "use-cases.md",
        views.content_page_markdown,
        {"section_slug": "use-cases", "page_slug": "index"},
        name="content_page_markdown",
    ),
    path("<slug:page_slug>.md", views.public_page_markdown, name="public_page_markdown"),
    path("blog/<slug:slug>.md", views.blog_post_markdown, name="blog_post_markdown"),
    path(
        "<slug:section_slug>/<slug:page_slug>.md",
        views.content_page_markdown,
        name="content_page_markdown",
    ),
    path("use-cases", views.use_cases_view, name="use_cases"),
    path("use-cases/<slug:slug>", views.use_case_page_view, name="use_case_page"),
    path(
        "privacy-policy",
        views.PrivacyPolicyView.as_view(),
        name="privacy_policy",
    ),
    path(
        "terms-of-service",
        views.TermsOfServiceView.as_view(),
        name="terms_of_service",
    ),
    path("pricing", views.PricingView.as_view(), name="pricing"),
    path("docs", views.docs_home_view, name="docs_home"),
    path("docs/<slug:slug>", views.docs_page_view, name="docs_page"),
    path("blog", views.blog_posts_view, name="blog_posts"),
    path("blog/<slug:slug>", views.blog_post_view, name="blog_post"),
    path("uses", views.UsesView.as_view(), name="uses"),
]
