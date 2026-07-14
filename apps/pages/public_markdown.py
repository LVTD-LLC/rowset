from urllib.parse import urlencode

from django.http import Http404, HttpResponse
from django.template import Context, Template

from apps.pages.blog import BlogPost
from rowset.utils import build_absolute_public_url

MARKDOWN_CONTENT_TYPE = "text/markdown; charset=utf-8"

CURATED_PUBLIC_PAGE_SOURCES: dict[str, str] = {
    "blog": "public/blog.md",
    "index": "public/index.md",
    "pricing": "public/pricing.md",
    "privacy-policy": "public/privacy-policy.md",
    "terms-of-service": "public/terms-of-service.md",
    "uses": "public/uses.md",
}


def markdown_path_for(path: str) -> str:
    if path == "/":
        return "/index.md"
    return f"{path.rstrip('/')}.md"


def build_public_markdown_url(path: str) -> str:
    return build_absolute_public_url(markdown_path_for(path))


def build_public_markdown_context(path: str) -> dict[str, str]:
    return {"markdown_url": build_public_markdown_url(path)}


def build_ai_reader_context(path: str) -> dict[str, str]:
    context = build_public_markdown_context(path)
    markdown_url = context["markdown_url"]
    prompt = f"Read this Rowset page and help me understand or use it: {markdown_url}"
    query = urlencode({"q": prompt})
    return {
        **context,
        "ai_reader_prompt": prompt,
        "claude_url": f"https://claude.ai/new?{query}",
        "chatgpt_url": f"https://chatgpt.com/?{query}",
    }


def markdown_response(content: str) -> HttpResponse:
    return HttpResponse(f"{content.rstrip()}\n", content_type=MARKDOWN_CONTENT_TYPE)


def render_public_page_markdown(page_slug: str) -> str:
    from apps.pages.content import get_content_root, get_content_template_context

    if page_slug not in CURATED_PUBLIC_PAGE_SOURCES:
        raise Http404("Public page not found")

    content_root = get_content_root().resolve()
    source_path = (content_root / CURATED_PUBLIC_PAGE_SOURCES[page_slug]).resolve()
    if not source_path.is_relative_to(content_root):
        raise Http404("Public page not found")

    try:
        source = source_path.read_text(encoding="utf-8")
        return Template(source).render(Context(get_content_template_context()))
    except Exception as exc:
        raise Http404("Public page not found") from exc


def render_content_markdown(section_slug: str, page_slug: str) -> str:
    from apps.pages.content import load_content_page

    _, rendered_markdown = load_content_page(section_slug, page_slug)
    return rendered_markdown


def render_blog_markdown(post: BlogPost) -> str:
    return f"# {post.title}\n\n{post.description}\n\n{post.content}"
