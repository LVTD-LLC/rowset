from django.urls import path
from django.views.generic import RedirectView

from apps.pages import views

LEGACY_PUBLIC_REDIRECTS = {
    "docs/getting-started/introduction/": "/docs/quickstart",
    "docs/features/datasets/": "/docs/datasets",
    "docs/features/public-previews/": "/docs/share-public-previews",
    "docs/features/agent-discovery/": "/docs/agent-discovery",
    "docs/features/mcp/": "/docs/connect-mcp",
    "docs/features/agent-access/": "/docs/configure-agent-access",
    "docs/api-reference/introduction/": "/docs/api-overview",
    "docs/api-reference/user/": "/docs/user-api",
    "docs/api-reference/projects/": "/docs/project-api",
    "docs/api-reference/datasets/": "/docs/dataset-api",
    "docs/reference/api-overview/": "/docs/api-overview",
    "docs/reference/user-api/": "/docs/user-api",
    "docs/reference/project-api/": "/docs/project-api",
    "docs/reference/dataset-api/": "/docs/dataset-api",
    "docs/reference/mcp-tools/": "/docs/mcp-tools",
    "docs/tutorials/first-agent-dataset/": "/docs/quickstart",
    "docs/how-to-guides/configure-agent-access/": "/docs/configure-agent-access",
    "docs/how-to-guides/connect-mcp/": "/docs/connect-mcp",
    "docs/how-to-guides/help-agents-discover-rowset/": "/docs/agent-discovery",
    "docs/how-to-guides/share-public-preview/": "/docs/share-public-previews",
    "docs/explanation/datasets/": "/docs/datasets",
    "docs/explanation/mcp-rest-and-previews/": "/docs/mcp-rest-public-previews",
    "docs/use-cases/personal-crm/": "/use-cases/personal-crm",
    "docs/use-cases/agent-task-board/": "/use-cases/agent-task-board",
    "docs/use-cases/feedback-triage/": "/use-cases/feedback-triage",
    "docs/use-cases/content-pipeline/": "/use-cases/content-pipeline",
    "docs/use-cases/product-inventory-catalog/": "/use-cases/product-inventory-catalog",
    "docs/use-cases/bug-qa-tracker/": "/use-cases/bug-qa-tracker",
    "tutorials/": "/docs/quickstart",
    "tutorials/first-agent-dataset/": "/docs/quickstart",
    "how-to/": "/use-cases",
    "how-to/configure-agent-access/": "/docs/configure-agent-access",
    "how-to/connect-mcp/": "/docs/connect-mcp",
    "how-to/help-agents-discover-rowset/": "/docs/agent-discovery",
    "how-to/share-public-preview/": "/docs/share-public-previews",
    "how-to/personal-crm/": "/use-cases/personal-crm",
    "how-to/agent-task-board/": "/use-cases/agent-task-board",
    "how-to/feedback-triage/": "/use-cases/feedback-triage",
    "how-to/content-pipeline/": "/use-cases/content-pipeline",
    "how-to/product-inventory-catalog/": "/use-cases/product-inventory-catalog",
    "how-to/bug-qa-tracker/": "/use-cases/bug-qa-tracker",
    "explanations/": "/docs/quickstart",
    "explanations/datasets/": "/docs/datasets",
    "explanations/mcp-rest-and-previews/": "/docs/mcp-rest-public-previews",
    "explanations/database-mcp-server": "/docs/database-mcp-server",
    "explanations/database-mcp-server/": "/docs/database-mcp-server",
    "playbooks/database-mcp-server/": "/docs/database-mcp-server",
    "alternatives/airtable/": "/blog/airtable-alternatives",
}

urlpatterns = [
    path("", views.LandingPageView.as_view(), name="landing"),
    *(
        path(
            old_path,
            RedirectView.as_view(url=new_path, permanent=True, query_string=True),
        )
        for old_path, new_path in LEGACY_PUBLIC_REDIRECTS.items()
    ),
    path("llms.txt", views.llms_txt, name="llms_txt"),
    path("changelog.md", views.changelog_markdown, name="changelog_markdown"),
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
    path("vs/<slug:slug>.md", views.comparison_page_markdown, name="comparison_page_markdown"),
    path(
        "<slug:section_slug>/<slug:page_slug>.md",
        views.content_page_markdown,
        name="content_page_markdown",
    ),
    path(
        "use-cases/",
        RedirectView.as_view(pattern_name="use_cases", permanent=True, query_string=True),
    ),
    path(
        "use-cases/<slug:slug>/",
        RedirectView.as_view(pattern_name="use_case_page", permanent=True, query_string=True),
    ),
    path(
        "pricing/",
        RedirectView.as_view(pattern_name="pricing", permanent=True, query_string=True),
    ),
    path(
        "docs/",
        RedirectView.as_view(url="/docs/quickstart", permanent=True, query_string=True),
    ),
    path(
        "docs/<slug:slug>/",
        RedirectView.as_view(pattern_name="docs_page", permanent=True, query_string=True),
    ),
    path(
        "blog/",
        RedirectView.as_view(pattern_name="blog_posts", permanent=True, query_string=True),
    ),
    path(
        "blog/<slug:slug>/",
        RedirectView.as_view(pattern_name="blog_post", permanent=True, query_string=True),
    ),
    path(
        "vs/<slug:slug>/",
        RedirectView.as_view(pattern_name="comparison_page", permanent=True, query_string=True),
    ),
    path(
        "uses/",
        RedirectView.as_view(pattern_name="uses", permanent=True, query_string=True),
    ),
    path(
        "changelog/",
        RedirectView.as_view(pattern_name="changelog", permanent=True, query_string=True),
    ),
    path(
        "privacy-policy/",
        RedirectView.as_view(pattern_name="privacy_policy", permanent=True, query_string=True),
    ),
    path(
        "terms-of-service/",
        RedirectView.as_view(pattern_name="terms_of_service", permanent=True, query_string=True),
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
    path("changelog", views.changelog_view, name="changelog"),
    path("docs", views.docs_home_view, name="docs_home"),
    path("docs/<slug:slug>", views.docs_page_view, name="docs_page"),
    path("blog", views.blog_posts_view, name="blog_posts"),
    path("blog/<slug:slug>", views.blog_post_view, name="blog_post"),
    path("vs/<slug:slug>", views.comparison_page_view, name="comparison_page"),
    path("uses", views.UsesView.as_view(), name="uses"),
]
