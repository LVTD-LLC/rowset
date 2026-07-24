import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_signed_out_site_chrome_opens_public_content_search(client):
    response = client.get(reverse("landing"))

    assert response.status_code == 200
    content = response.content.decode()
    search_url = reverse("public_content_search")

    assert f'href="{search_url}"' in content
    assert f'hx-get="{search_url}"' in content
    assert 'placeholder="Search docs, blog, and use cases"' in content


def test_public_content_search_returns_docs_blog_and_use_cases(client):
    response = client.get(reverse("public_content_search"), {"q": "personal CRM"})

    assert response.status_code == 200
    content = response.content.decode()

    assert "Search Rowset" in content
    assert "Docs" in content
    assert "Use cases" in content
    assert "Blog" in content
    assert "Agent-managed personal CRM" in content
    assert "AI Agent CRM: How to Build One with Structured Datasets" in content
    assert reverse("docs_page", kwargs={"slug": "datasets"}) in content


def test_public_content_search_htmx_response_is_the_results_fragment(client):
    response = client.get(
        reverse("public_content_search"),
        {"q": "personal CRM"},
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    content = response.content.decode()

    assert 'id="public-content-search-results"' in content
    assert "Agent-managed personal CRM" in content
    assert "<html" not in content.lower()
    assert "Search docs, blog, and use cases" not in content
    assert "HX-Request" in response.headers["Vary"]


def test_public_content_search_prompts_before_a_meaningful_query(client):
    response = client.get(
        reverse("public_content_search"),
        {"q": "a"},
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    content = response.content.decode()

    assert "Keep typing" in content
    assert "Search starts after 2 characters" in content
    assert "Agent-managed personal CRM" not in content


def test_public_content_search_matches_checked_in_markdown_body(client):
    response = client.get(
        reverse("public_content_search"),
        {"q": "public previews stay off"},
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    content = response.content.decode()

    assert "Start with your first agent dataset" in content
    assert reverse("docs_page", kwargs={"slug": "quickstart"}) in content


@pytest.mark.parametrize("as_htmx", (False, True))
def test_public_content_search_renders_no_matches_state(client, as_htmx):
    request_kwargs = {"HTTP_HX_REQUEST": "true"} if as_htmx else {}

    response = client.get(
        reverse("public_content_search"),
        {"q": "definitely-no-rowset-content-matches-this-query"},
        **request_kwargs,
    )

    assert response.status_code == 200
    assert "No matches" in response.content.decode()
    assert "HX-Request" in response.headers["Vary"]
