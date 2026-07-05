from django.contrib.sitemaps.views import sitemap
from django.http import HttpResponse, HttpResponseNotAllowed, HttpResponsePermanentRedirect
from django.urls import path
from django.views.decorators.cache import cache_control

from rowset.sitemaps import sitemaps
from rowset.utils import build_absolute_public_url


@cache_control(public=True, max_age=86400)
def robots_txt(request):
    sitemap_url = build_absolute_public_url("/sitemap.xml")
    content = "\n".join(
        [
            "User-agent: *",
            "Allow: /",
            f"Sitemap: {sitemap_url}",
            "",
            "",
        ]
    )
    return HttpResponse(content, content_type="text/plain; charset=utf-8")


@cache_control(public=True, max_age=86400)
def public_sitemap(request, **kwargs):
    response = sitemap(request, sitemaps=sitemaps, **kwargs)
    response.headers.pop("X-Robots-Tag", None)
    return response


def redirect_to_canonical_no_slash(request, **kwargs):
    if request.method not in {"GET", "HEAD"}:
        return HttpResponseNotAllowed(["GET", "HEAD"])

    target = request.path_info.rstrip("/") or "/"

    if request.META.get("QUERY_STRING"):
        target = f"{target}?{request.META['QUERY_STRING']}"
    return HttpResponsePermanentRedirect(target)


def canonical_no_slash_path(route, view, *, name):
    """Register a relative no-slash route and its canonical slash redirect."""
    if route.startswith("/"):
        raise ValueError("Canonical no-slash routes must be relative and must not start with '/'.")
    if route.endswith("/"):
        raise ValueError("Canonical no-slash routes must not end with '/'.")

    return (
        path(route, view, name=name),
        path(f"{route}/", redirect_to_canonical_no_slash, name=f"{name}_slash_redirect"),
    )
