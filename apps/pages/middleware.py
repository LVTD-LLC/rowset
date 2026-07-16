from apps.pages.search import NOINDEX_ROBOTS_POLICY, search_indexing_enabled


class SearchEngineIndexingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if not search_indexing_enabled():
            response.headers.setdefault("X-Robots-Tag", NOINDEX_ROBOTS_POLICY)
        return response
