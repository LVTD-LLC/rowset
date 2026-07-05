from django.contrib.sitemaps.views import sitemap
from django.http import Http404, HttpResponse, HttpResponsePermanentRedirect
from django.urls import get_urlconf, is_valid_path
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


def redirect_to_canonical_no_slash(request, _path):
    if request.method not in {"GET", "HEAD"}:
        raise Http404

    target = request.path_info.rstrip("/") or "/"
    if not is_valid_path(target, urlconf=get_urlconf()):
        raise Http404

    if request.META.get("QUERY_STRING"):
        target = f"{target}?{request.META['QUERY_STRING']}"
    return HttpResponsePermanentRedirect(target)
