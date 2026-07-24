from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cached_property, lru_cache

import frontmatter

from apps.pages.blog import list_blog_posts
from apps.pages.content import (
    CONTENT_SECTIONS,
    get_content_section_dir,
    get_section_page_url,
)

MIN_PUBLIC_CONTENT_QUERY_LENGTH = 2
MAX_PUBLIC_CONTENT_QUERY_LENGTH = 100
PUBLIC_CONTENT_RESULTS_PER_SECTION = 5
PUBLIC_CONTENT_SECTION_ORDER = (*CONTENT_SECTIONS, "blog")
PUBLIC_CONTENT_SECTION_LABELS = {
    **{section: config["label"] for section, config in CONTENT_SECTIONS.items()},
    "blog": "Blog",
}
SEARCH_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
MARKDOWN_NOISE_PATTERN = re.compile(r"[#*_>`~\[\](){|}]")
WHITESPACE_PATTERN = re.compile(r"\s+")


@dataclass(frozen=True)
class PublicContentSearchItem:
    section: str
    slug: str
    title: str
    description: str
    url: str
    keywords: str
    body: str

    @cached_property
    def normalized_fields(self) -> tuple[str, str, str, str]:
        return tuple(
            value.casefold()
            for value in (
                self.title,
                self.description,
                self.keywords,
                self.body,
            )
        )

    @cached_property
    def searchable_text(self) -> str:
        return " ".join(self.normalized_fields)


def normalize_public_content_query(query: str) -> str:
    return WHITESPACE_PATTERN.sub(" ", query).strip()[:MAX_PUBLIC_CONTENT_QUERY_LENGTH]


def _metadata_text(value) -> str:
    if isinstance(value, list | tuple | set):
        return " ".join(str(item) for item in value)
    return "" if value is None else str(value)


def _plain_markdown(value: str) -> str:
    return WHITESPACE_PATTERN.sub(" ", MARKDOWN_NOISE_PATTERN.sub(" ", value)).strip()


def _load_content_section_items(section: str):
    content_dir = get_content_section_dir(section).resolve()
    if not content_dir.exists():
        return []

    items = []
    for source_path in sorted(content_dir.glob("*.md")):
        try:
            with source_path.open(encoding="utf-8") as file:
                page = frontmatter.load(file)
        except Exception:
            continue

        slug = source_path.stem
        items.append(
            PublicContentSearchItem(
                section=section,
                slug=slug,
                title=str(page.get("title") or slug.replace("-", " ").title()),
                description=str(page.get("description") or ""),
                url=get_section_page_url(section, slug),
                keywords=_metadata_text(page.get("keywords")),
                body=_plain_markdown(page.content),
            )
        )
    return items


@lru_cache(maxsize=1)
def get_public_content_search_index() -> tuple[PublicContentSearchItem, ...]:
    items = [item for section in CONTENT_SECTIONS for item in _load_content_section_items(section)]
    items.extend(
        PublicContentSearchItem(
            section="blog",
            slug=post.slug,
            title=post.title,
            description=post.description,
            url=post.get_absolute_url(),
            keywords=" ".join((*post.keywords, *post.topics)),
            body=_plain_markdown(post.content),
        )
        for post in list_blog_posts(render_html=False)
    )
    return tuple(items)


def _search_score(item: PublicContentSearchItem, query: str, tokens: tuple[str, ...]) -> int:
    searchable_text = item.searchable_text

    if not all(token in searchable_text for token in tokens):
        return 0

    weighted_fields = (
        (item.normalized_fields[0], 100, 20),
        (item.normalized_fields[1], 50, 8),
        (item.normalized_fields[2], 30, 5),
        (item.normalized_fields[3], 15, 1),
    )
    phrase_score = sum(weight for text, weight, _token_weight in weighted_fields if query in text)
    token_score = sum(
        weight
        for text, _phrase_weight, weight in weighted_fields
        for token in tokens
        if token in text
    )
    return phrase_score + token_score


def search_public_content(query: str) -> list[dict]:
    normalized_query = normalize_public_content_query(query)
    if len(normalized_query) < MIN_PUBLIC_CONTENT_QUERY_LENGTH:
        return []

    query = normalized_query.casefold()
    tokens = tuple(SEARCH_TOKEN_PATTERN.findall(query))
    if not tokens:
        return []

    results_by_section = {section: [] for section in PUBLIC_CONTENT_SECTION_ORDER}
    for item in get_public_content_search_index():
        score = _search_score(item, query, tokens)
        if score:
            results_by_section[item.section].append((score, item))

    groups = []
    for section in PUBLIC_CONTENT_SECTION_ORDER:
        ranked_items = sorted(
            results_by_section[section],
            key=lambda result: (-result[0], result[1].title.casefold(), result[1].slug),
        )
        results = [item for _score, item in ranked_items[:PUBLIC_CONTENT_RESULTS_PER_SECTION]]
        if results:
            groups.append(
                {
                    "slug": section,
                    "label": PUBLIC_CONTENT_SECTION_LABELS[section],
                    "results": results,
                }
            )
    return groups


def build_public_content_search_context(query: str) -> dict:
    normalized_query = normalize_public_content_query(query)
    query_too_short = bool(normalized_query) and (
        len(normalized_query) < MIN_PUBLIC_CONTENT_QUERY_LENGTH
    )
    result_groups = (
        [] if not normalized_query or query_too_short else search_public_content(normalized_query)
    )
    return {
        "query": normalized_query,
        "query_too_short": query_too_short,
        "min_query_length": MIN_PUBLIC_CONTENT_QUERY_LENGTH,
        "result_groups": result_groups,
        "has_results": bool(result_groups),
    }
