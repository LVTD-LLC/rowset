from django.core.checks import Error, register

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
