from django.core.checks import Error, register

from apps.blog.services import iter_blog_post_validation_errors


@register()
def blog_post_content_check(app_configs, **kwargs):
    return [
        Error(
            str(error),
            hint="Fix the markdown frontmatter in apps/pages/content/blog before deploying.",
            id="blog.E001",
        )
        for error in iter_blog_post_validation_errors()
    ]
