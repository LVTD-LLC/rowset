from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import frontmatter
import markdown
from django.conf import settings
from django.http import Http404
from django.template import Context, Template
from django.urls import reverse

from apps.pages.content import CONTENT_MARKDOWN_EXTENSIONS, get_content_template_context

COMPARISON_SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")
COMPARISON_LOAD_ERRORS = (KeyError, TypeError, ValueError)


@dataclass(frozen=True)
class ComparisonPage:
    slug: str
    title: str
    description: str
    author: str
    published_at: date
    updated_at: date
    keywords: tuple[str, ...]
    faqs: tuple[tuple[str, str], ...]
    content: str
    html: str

    def get_absolute_url(self) -> str:
        return reverse("comparison_page", kwargs={"slug": self.slug})


def get_comparisons_dir() -> Path:
    return Path(settings.BASE_DIR) / "apps" / "pages" / "content" / "vs"


def _metadata_date(value, field_name: str) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid comparison {field_name}") from exc


def load_comparison_page(source_path: Path) -> ComparisonPage:
    comparisons_dir = get_comparisons_dir().resolve()
    source_path = source_path.resolve()
    if not source_path.is_relative_to(comparisons_dir):
        raise ValueError("Comparison page must live in the comparisons directory")

    post = frontmatter.load(source_path)
    slug = source_path.stem
    required = ("title", "description", "author", "published_at", "updated_at")
    if not COMPARISON_SLUG_PATTERN.fullmatch(slug) or any(
        not post.metadata.get(field) for field in required
    ):
        raise ValueError(f"Invalid comparison page: {source_path.name}")

    rendered_content = Template(post.content).render(Context(get_content_template_context()))
    faqs = tuple(
        (str(item["question"]), str(item["answer"])) for item in post.metadata.get("faqs", ())
    )
    return ComparisonPage(
        slug=slug,
        title=str(post["title"]),
        description=str(post["description"]),
        author=str(post["author"]),
        published_at=_metadata_date(post["published_at"], "published_at"),
        updated_at=_metadata_date(post["updated_at"], "updated_at"),
        keywords=tuple(str(keyword) for keyword in post.metadata.get("keywords", ())),
        faqs=faqs,
        content=rendered_content,
        html=markdown.markdown(rendered_content, extensions=CONTENT_MARKDOWN_EXTENSIONS),
    )


def list_comparison_pages() -> list[ComparisonPage]:
    comparisons_dir = get_comparisons_dir().resolve()
    if not comparisons_dir.exists():
        return []

    pages = []
    for source_path in sorted(comparisons_dir.glob("*.md")):
        try:
            pages.append(load_comparison_page(source_path))
        except COMPARISON_LOAD_ERRORS:
            continue
    return pages


def get_comparison_page(slug: str) -> ComparisonPage:
    if not COMPARISON_SLUG_PATTERN.fullmatch(slug):
        raise Http404("Comparison page not found")

    comparisons_dir = get_comparisons_dir().resolve()
    source_path = (comparisons_dir / f"{slug}.md").resolve()
    if not source_path.is_relative_to(comparisons_dir) or not source_path.exists():
        raise Http404("Comparison page not found")

    try:
        return load_comparison_page(source_path)
    except (KeyError, TypeError, ValueError) as exc:
        raise Http404("Comparison page not found") from exc


def render_comparison_markdown(page: ComparisonPage) -> str:
    updated = f"{page.updated_at.strftime('%B')} {page.updated_at.day}, {page.updated_at.year}"
    return f"# {page.title}\n\n{page.description}\n\nUpdated {updated}.\n\n{page.content}"
