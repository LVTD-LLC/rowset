from django.http import Http404, HttpResponse

from apps.pages.blog import BlogPost
from apps.pages.content import load_content_page

MARKDOWN_CONTENT_TYPE = "text/markdown; charset=utf-8"

PUBLIC_PAGE_MARKDOWN = {
    "index": "",
    "pricing": "",
}


def markdown_path_for(path: str) -> str:
    if path == "/":
        return "/index.md"
    return f"{path.rstrip('/')}.md"


def markdown_response(content: str) -> HttpResponse:
    return HttpResponse(f"{content.rstrip()}\n", content_type=MARKDOWN_CONTENT_TYPE)


def render_public_page_markdown(page_slug: str) -> str:
    try:
        return PUBLIC_PAGE_MARKDOWN[page_slug]
    except KeyError as exc:
        raise Http404("Public page not found") from exc


def render_content_markdown(section_slug: str, page_slug: str) -> str:
    _, rendered_markdown = load_content_page(section_slug, page_slug)
    return rendered_markdown


def render_blog_markdown(post: BlogPost) -> str:
    return f"# {post.title}\n\n{post.description}\n\n{post.content}"
