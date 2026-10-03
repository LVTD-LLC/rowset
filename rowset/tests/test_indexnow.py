import json
from pathlib import Path
from urllib.error import HTTPError

import pytest
from django.test import override_settings
from django.urls import reverse

from scripts.submit_indexnow import (
    INDEXNOW_ENDPOINT,
    MAX_URLS_PER_REQUEST,
    IndexNowError,
    build_indexnow_payload,
    fetch_sitemap_urls,
    parse_name_status,
    public_paths_for_changes,
    submit_urls,
    verify_key_location,
)

_REPO_ROOT = Path(__file__).parents[2]


@override_settings(INDEXNOW_KEY="")
def test_indexnow_key_file_is_unavailable_when_not_configured(client):
    response = client.get(reverse("indexnow_key"))

    assert response.status_code == 404


@override_settings(
    INDEXNOW_KEY="rowset-indexnow-test-key",
    SITE_URL="https://rowset.app",
)
def test_indexnow_key_file_serves_the_configured_key_without_caching(client):
    response = client.get(reverse("indexnow_key"))

    assert response.status_code == 200
    assert response.content == b"rowset-indexnow-test-key"
    assert response.headers["Content-Type"] == "text/plain; charset=utf-8"
    assert set(response.headers["Cache-Control"].split(", ")) == {
        "max-age=0",
        "no-cache",
        "no-store",
        "must-revalidate",
    }
    assert "X-Robots-Tag" not in response.headers


def test_deploy_notifier_has_no_django_project_imports():
    source = (_REPO_ROOT / "scripts" / "submit_indexnow.py").read_text()

    assert "from rowset" not in source
    assert "import rowset" not in source


def test_parse_name_status_preserves_both_sides_of_renames():
    changes = parse_name_status(
        b"M\x00CHANGELOG.md\x00"
        b"D\x00apps/pages/content/docs/removed.md\x00"
        b"R100\x00apps/pages/content/vs/old.md\x00apps/pages/content/vs/new.md\x00"
    )

    assert changes == [
        ("M", ("CHANGELOG.md",)),
        ("D", ("apps/pages/content/docs/removed.md",)),
        (
            "R100",
            (
                "apps/pages/content/vs/old.md",
                "apps/pages/content/vs/new.md",
            ),
        ),
    ]


def test_public_paths_map_changed_deleted_and_renamed_content():
    paths, include_sitemap = public_paths_for_changes(
        [
            ("M", ("CHANGELOG.md",)),
            ("M", ("apps/pages/content/blog/new-post.md",)),
            ("D", ("apps/pages/content/docs/removed-guide.md",)),
            (
                "R100",
                (
                    "apps/pages/content/vs/old-comparison.md",
                    "apps/pages/content/vs/new-comparison.md",
                ),
            ),
            ("M", ("apps/pages/content/use-cases/index.md",)),
            ("M", ("apps/datasets/services.py",)),
        ]
    )

    assert paths == {
        "/blog",
        "/blog/new-post",
        "/changelog",
        "/docs/removed-guide",
        "/use-cases",
        "/vs/new-comparison",
        "/vs/old-comparison",
    }
    assert include_sitemap is False


@pytest.mark.parametrize(
    "changed_path",
    (
        "apps/pages/content/navigation.yaml",
        "apps/pages/seo.py",
        "frontend/templates/base_landing.html",
        "frontend/templates/components/site_footer.html",
        "frontend/templates/pages/landing-page.html",
        "rowset/sitemaps.py",
        "rowset/urls.py",
    ),
)
def test_global_public_changes_request_the_current_sitemap(changed_path):
    paths, include_sitemap = public_paths_for_changes([("M", (changed_path,))])

    assert paths == set()
    assert include_sitemap is True


def test_tests_and_private_app_changes_do_not_trigger_indexnow():
    paths, include_sitemap = public_paths_for_changes(
        [
            ("M", ("apps/pages/tests.py",)),
            ("M", ("frontend/templates/datasets/dataset_detail.html",)),
            ("M", ("rowset/tests/test_release_flow.py",)),
        ]
    )

    assert paths == set()
    assert include_sitemap is False


def test_build_indexnow_payload_uses_explicit_key_location_and_same_host_urls():
    payload = build_indexnow_payload(
        "https://rowset.lvtd.dev",
        "rowset-indexnow-test-key",
        [
            "https://rowset.lvtd.dev/docs/quickstart",
            "https://rowset.lvtd.dev/blog/new-post",
        ],
    )

    assert payload == {
        "host": "rowset.lvtd.dev",
        "key": "rowset-indexnow-test-key",
        "keyLocation": "https://rowset.lvtd.dev/indexnow-key.txt",
        "urlList": [
            "https://rowset.lvtd.dev/docs/quickstart",
            "https://rowset.lvtd.dev/blog/new-post",
        ],
    }


def test_build_indexnow_payload_rejects_urls_for_another_host():
    with pytest.raises(IndexNowError, match="does not belong to https://rowset.lvtd.dev"):
        build_indexnow_payload(
            "https://rowset.lvtd.dev",
            "rowset-indexnow-test-key",
            ["https://example.com/other"],
        )


def test_build_indexnow_payload_rejects_urls_with_another_scheme():
    with pytest.raises(IndexNowError, match="does not belong to https://rowset.lvtd.dev"):
        build_indexnow_payload(
            "https://rowset.lvtd.dev",
            "rowset-indexnow-test-key",
            ["http://rowset.lvtd.dev/other"],
        )


class _Response:
    def __init__(self, status=200, body=b""):
        self.status = status
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, size=-1):
        return self._body if size < 0 else self._body[:size]


def test_fetch_sitemap_urls_follows_same_host_sitemap_indexes():
    documents = {
        "https://rowset.lvtd.dev/sitemap.xml": b"""
            <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
              <sitemap><loc>https://rowset.lvtd.dev/sitemap-pages.xml</loc></sitemap>
              <sitemap><loc>https://rowset.lvtd.dev/sitemap-blog.xml</loc></sitemap>
            </sitemapindex>
        """,
        "https://rowset.lvtd.dev/sitemap-pages.xml": b"""
            <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
              <url><loc>https://rowset.lvtd.dev/docs/quickstart</loc></url>
            </urlset>
        """,
        "https://rowset.lvtd.dev/sitemap-blog.xml": b"""
            <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
              <url><loc>https://rowset.lvtd.dev/blog/new-post</loc></url>
            </urlset>
        """,
    }

    def urlopen(request, timeout):
        assert timeout == 20
        return _Response(body=documents[request.full_url])

    assert set(fetch_sitemap_urls("https://rowset.lvtd.dev", urlopen=urlopen)) == {
        "https://rowset.lvtd.dev/blog/new-post",
        "https://rowset.lvtd.dev/docs/quickstart",
    }


def test_fetch_sitemap_urls_honors_configurable_document_limit():
    document = b"""
        <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <sitemap><loc>https://rowset.lvtd.dev/sitemap-pages.xml</loc></sitemap>
        </sitemapindex>
    """

    def urlopen(_request, timeout):
        assert timeout == 20
        return _Response(body=document)

    with pytest.raises(IndexNowError, match="configured document limit of 1"):
        fetch_sitemap_urls(
            "https://rowset.lvtd.dev",
            max_documents=1,
            urlopen=urlopen,
        )


def test_fetch_sitemap_urls_rejects_doctype_declarations():
    document = b"""<!DOCTYPE sitemap [<!ENTITY x "expanded">]>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <url><loc>https://rowset.lvtd.dev/&x;</loc></url>
        </urlset>
    """

    def urlopen(_request, timeout):
        assert timeout == 20
        return _Response(body=document)

    with pytest.raises(IndexNowError, match="unsafe XML declarations"):
        fetch_sitemap_urls("https://rowset.lvtd.dev", urlopen=urlopen)


def test_verify_key_location_retries_a_transient_not_found():
    responses = [
        HTTPError(
            "https://rowset.lvtd.dev/indexnow-key.txt",
            404,
            "Not Found",
            {},
            None,
        ),
        _Response(body=b"rowset-indexnow-test-key"),
    ]
    delays = []

    def urlopen(_request, timeout):
        assert timeout == 20
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    verify_key_location(
        "https://rowset.lvtd.dev",
        "rowset-indexnow-test-key",
        attempts=2,
        jitter=lambda: 0,
        sleep=delays.append,
        urlopen=urlopen,
    )

    assert delays == [5]


def test_submit_urls_batches_requests_at_the_protocol_limit():
    requests = []

    def urlopen(request, timeout):
        requests.append((request, timeout))
        return _Response(status=202)

    urls = [f"https://rowset.lvtd.dev/docs/page-{index}" for index in range(10001)]
    submitted = submit_urls(
        "https://rowset.lvtd.dev",
        "rowset-indexnow-test-key",
        urls,
        urlopen=urlopen,
    )

    assert submitted == 10001
    assert len(requests) == 2
    first_payload = json.loads(requests[0][0].data)
    second_payload = json.loads(requests[1][0].data)
    assert len(first_payload["urlList"]) == MAX_URLS_PER_REQUEST
    assert len(second_payload["urlList"]) == 1
    assert all(timeout == 20 for _, timeout in requests)


def test_submit_urls_surfaces_indexnow_http_errors_without_exposing_the_key():
    def urlopen(request, timeout):
        raise HTTPError(request.full_url, 429, "Too Many Requests", {}, None)

    with pytest.raises(IndexNowError) as exc_info:
        submit_urls(
            "https://rowset.lvtd.dev",
            "rowset-indexnow-test-key",
            ["https://rowset.lvtd.dev/docs/quickstart"],
            urlopen=urlopen,
        )

    assert "HTTP 429" in str(exc_info.value)
    assert "rowset-indexnow-test-key" not in str(exc_info.value)


def test_submit_urls_retries_transient_http_errors():
    responses = [
        HTTPError(INDEXNOW_ENDPOINT, 503, "Unavailable", {}, None),
        _Response(status=200),
    ]
    delays = []

    def urlopen(request, timeout):
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    submitted = submit_urls(
        "https://rowset.lvtd.dev",
        "rowset-indexnow-test-key",
        ["https://rowset.lvtd.dev/docs/quickstart"],
        attempts=2,
        jitter=lambda: 0,
        sleep=delays.append,
        urlopen=urlopen,
    )

    assert submitted == 1
    assert delays == [5]


def test_submit_urls_uses_exponential_backoff_with_jitter():
    responses = [
        HTTPError(INDEXNOW_ENDPOINT, 503, "Unavailable", {}, None),
        HTTPError(INDEXNOW_ENDPOINT, 503, "Unavailable", {}, None),
        HTTPError(INDEXNOW_ENDPOINT, 503, "Unavailable", {}, None),
        _Response(status=200),
    ]
    delays = []

    def urlopen(_request, timeout):
        assert timeout == 20
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    submit_urls(
        "https://rowset.lvtd.dev",
        "rowset-indexnow-test-key",
        ["https://rowset.lvtd.dev/docs/quickstart"],
        attempts=4,
        jitter=lambda: 0.25,
        sleep=delays.append,
        urlopen=urlopen,
    )

    assert delays == [5.25, 10.25, 20.25]
