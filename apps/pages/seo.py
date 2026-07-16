from django.contrib.sitemaps.views import sitemap
from django.contrib.staticfiles.storage import staticfiles_storage
from django.http import HttpResponse, HttpResponsePermanentRedirect
from django.views.decorators.cache import cache_control

from apps.pages.search import NOINDEX_ROBOTS_POLICY, build_canonical_url, search_indexing_enabled
from rowset.sitemaps import sitemaps


@cache_control(public=True, max_age=86400)
def favicon(_request):
    return HttpResponsePermanentRedirect(staticfiles_storage.url("vendors/images/favicon.ico"))


@cache_control(public=True, max_age=86400)
def robots_txt(request):
    lines = ["User-agent: *", "Allow: /"]
    if search_indexing_enabled():
        lines.append(f"Sitemap: {build_canonical_url('/sitemap.xml')}")
    content = "\n".join([*lines, "", ""])
    return HttpResponse(content, content_type="text/plain; charset=utf-8")


@cache_control(public=True, max_age=86400)
def public_sitemap(request, **kwargs):
    response = sitemap(request, sitemaps=sitemaps, **kwargs)
    if search_indexing_enabled():
        response.headers.pop("X-Robots-Tag", None)
    else:
        response["X-Robots-Tag"] = NOINDEX_ROBOTS_POLICY
    return response
