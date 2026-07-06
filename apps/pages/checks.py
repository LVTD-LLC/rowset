from django.core.checks import Error, register

from apps.pages.blog import iter_blog_post_validation_errors
from apps.pages.use_cases import get_use_case_page_registry_errors


@register("pages")
def check_use_case_page_registry(app_configs, **kwargs):
    return [
        Error(
            error,
            id="pages.E001",
        )
        for error in get_use_case_page_registry_errors()
    ]


@register()
def blog_post_content_check(app_configs, **kwargs):
    return [
        Error(
            str(error),
            hint="Fix the markdown frontmatter in apps/pages/content/blog before deploying.",
            id="pages.E002",
        )
        for error in iter_blog_post_validation_errors()
    ]
