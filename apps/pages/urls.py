from django.urls import path
from django.views.generic import RedirectView, TemplateView

from apps.pages import views

LEGACY_CONTENT_REDIRECTS = {
    "docs/getting-started/introduction/": "/docs/quickstart/",
    "docs/features/datasets/": "/docs/datasets/",
    "docs/features/public-previews/": "/docs/share-public-previews/",
    "docs/features/agent-discovery/": "/docs/agent-discovery/",
    "docs/features/mcp/": "/docs/connect-mcp/",
    "docs/features/agent-access/": "/docs/configure-agent-access/",
    "docs/api-reference/introduction/": "/docs/api-overview/",
    "docs/api-reference/user/": "/docs/user-api/",
    "docs/api-reference/projects/": "/docs/project-api/",
    "docs/api-reference/datasets/": "/docs/dataset-api/",
    "docs/reference/api-overview/": "/docs/api-overview/",
    "docs/reference/user-api/": "/docs/user-api/",
    "docs/reference/project-api/": "/docs/project-api/",
    "docs/reference/dataset-api/": "/docs/dataset-api/",
    "docs/reference/mcp-tools/": "/docs/mcp-tools/",
    "docs/tutorials/first-agent-dataset/": "/docs/quickstart/",
    "docs/how-to-guides/configure-agent-access/": "/docs/configure-agent-access/",
    "docs/how-to-guides/connect-mcp/": "/docs/connect-mcp/",
    "docs/how-to-guides/help-agents-discover-rowset/": "/docs/agent-discovery/",
    "docs/how-to-guides/share-public-preview/": "/docs/share-public-previews/",
    "docs/explanation/datasets/": "/docs/datasets/",
    "docs/explanation/mcp-rest-and-previews/": "/docs/mcp-rest-public-previews/",
    "playbooks/database-mcp-server/": "/docs/database-mcp-server/",
    "alternatives/airtable/": "/blog/airtable-alternatives",
}

urlpatterns = [
    path("", views.LandingPageView.as_view(), name="landing"),
    *(
        path(
            old_path,
            RedirectView.as_view(url=new_path, permanent=True),
        )
        for old_path, new_path in LEGACY_CONTENT_REDIRECTS.items()
    ),
    path("use-cases/", views.legacy_use_case_redirect, name="legacy_use_cases"),
    path("use-cases/<slug:slug>/", views.legacy_use_case_redirect, name="legacy_use_case"),
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
    path("docs/use-cases/<slug:slug>/", views.docs_use_case_view, name="docs_use_case"),
    path("docs/<slug:slug>/", views.docs_page_view, name="docs_page"),
    path("tutorials/", views.tutorials_home_view, name="tutorials_home"),
    path("tutorials/<slug:slug>/", views.tutorial_page_view, name="tutorial_page"),
    path("blog/", views.blog_posts_view, name="blog_posts"),
    path("blog/<slug:slug>", views.blog_post_view, name="blog_post"),
    path("how-to/", views.legacy_how_to_redirect, name="how_to_guides"),
    path("how-to/<slug:slug>/", views.how_to_guide_view, name="how_to_guide"),
    path("explanations/", views.explanations_home_view, name="explanations_home"),
    path("explanations/<slug:slug>/", views.explanation_page_view, name="explanation_page"),
    path(
        "uses/",
        TemplateView.as_view(template_name="pages/uses.html"),
        name="uses",
    ),
]
