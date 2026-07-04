from django.contrib.sitemaps.views import sitemap
from django.http import HttpResponse, HttpResponsePermanentRedirect

from rowset.sitemaps import sitemaps


def robots_txt(request):
    sitemap_url = request.build_absolute_uri("/sitemap.xml").replace("http://", "https://", 1)
    content = "\n".join(
        [
            "User-agent: *",
            "Allow: /",
            f"Sitemap: {sitemap_url}",
            "",
        ]
    )
    return HttpResponse(content, content_type="text/plain; charset=utf-8")


def public_sitemap(request, **kwargs):
    response = sitemap(request, sitemaps=sitemaps, **kwargs)
    response.headers.pop("X-Robots-Tag", None)
    return response


def redirect_without_trailing_slash(request, path, **kwargs):
    target = request.path_info.rstrip("/") or "/"
    if request.META.get("QUERY_STRING"):
        target = f"{target}?{request.META['QUERY_STRING']}"
    return HttpResponsePermanentRedirect(target)
