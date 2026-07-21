from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from urllib.parse import urlsplit

import frontmatter
import markdown
from django.conf import settings
from django.templatetags.static import static
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from apps.pages.search import INDEX_ROBOTS_POLICY, build_canonical_url
from rowset.utils import build_absolute_public_url

BLOG_TITLE = "Rowset Blog"
BLOG_DESCRIPTION = "Notes on agent-managed datasets, MCP, and Rowset API workflows."
BLOG_DEFAULT_AUTHOR = "Rasul Kireev"
BLOG_MARKDOWN_EXTENSIONS = ["fenced_code", "tables"]
BLOG_SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")
BLOG_REQUIRED_FRONTMATTER = ("title", "description", "published_at")


class BlogPostNotFound(Exception):
    pass


class BlogPostValidationError(ValueError):
    pass


@dataclass(frozen=True)
class BlogPost:
    slug: str
    title: str
    seo_title: str
    description: str
    content: str
    html: str
    published_at: datetime
    updated_at: datetime
    author: str
    keywords: tuple[str, ...]
    topics: tuple[str, ...]
    image_url: str
    image_alt: str
    robots: str
    reading_time_minutes: int
    source_path: Path

    def get_absolute_url(self):
        return reverse("blog_post", kwargs={"slug": self.slug})

    @property
    def canonical_url(self) -> str:
        return build_canonical_url(self.get_absolute_url())

    @property
    def metadata_keywords(self) -> tuple[str, ...]:
        return self.keywords or self.topics


def get_blog_posts_dir() -> Path:
    default_posts_dir = settings.BASE_DIR / "apps" / "pages" / "content" / "blog"
    return Path(getattr(settings, "BLOG_POSTS_DIR", default_posts_dir))


def is_blog_slug(value: str) -> bool:
    return bool(BLOG_SLUG_PATTERN.fullmatch(value))


def default_blog_image_url() -> str:
    return build_absolute_public_url(static("vendors/images/rowset-social-card.png"))


def _coerce_string(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _ensure_aware_datetime(value: datetime) -> datetime:
    if timezone.is_naive(value):
        return timezone.make_aware(value, timezone.get_default_timezone())
    return value


def _coerce_datetime(value, field_name: str, source_path: Path) -> datetime:
    if isinstance(value, datetime):
        return _ensure_aware_datetime(value)
    if isinstance(value, date):
        return _ensure_aware_datetime(datetime.combine(value, time.min))
    if isinstance(value, str):
        parsed_datetime = parse_datetime(value)
        if parsed_datetime:
            return _ensure_aware_datetime(parsed_datetime)
        parsed_date = parse_date(value)
        if parsed_date:
            return _ensure_aware_datetime(datetime.combine(parsed_date, time.min))
    raise BlogPostValidationError(
        f"{source_path}: frontmatter field '{field_name}' must be a date or datetime."
    )


def _coerce_list(value) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        values = value.split(",")
    elif isinstance(value, list | tuple | set):
        values = value
    else:
        values = [value]
    return tuple(item for item in (_coerce_string(item) for item in values) if item)


def _absolute_public_url(value: str) -> str:
    url = _coerce_string(value)
    if not url:
        return default_blog_image_url()

    parsed = urlsplit(url)
    if parsed.scheme in {"http", "https"}:
        return url
    if url.startswith("/"):
        return build_absolute_public_url(url)
    return build_absolute_public_url(static(url))


def _reading_time_minutes(content: str) -> int:
    word_count = len(re.findall(r"\w+", content))
    return max(1, round(word_count / 220))


def _validate_source_path(source_path: Path, content_dir: Path) -> None:
    if not source_path.is_relative_to(content_dir):
        raise BlogPostNotFound
    if source_path.suffix != ".md" or not source_path.exists():
        raise BlogPostNotFound
    if not is_blog_slug(source_path.stem):
        raise BlogPostValidationError(
            f"{source_path}: filename must be a lowercase URL slug like 'agent-datasets.md'."
        )


def load_blog_post(source_path: Path, content_dir: Path | None = None) -> BlogPost:
    content_dir = (content_dir or get_blog_posts_dir()).resolve()
    source_path = source_path.resolve()
    _validate_source_path(source_path, content_dir)

    with source_path.open(encoding="utf-8") as file:
        post = frontmatter.load(file)

    missing_fields = [
        field for field in BLOG_REQUIRED_FRONTMATTER if not _coerce_string(post.get(field))
    ]
    if missing_fields:
        missing = ", ".join(missing_fields)
        raise BlogPostValidationError(f"{source_path}: missing required frontmatter: {missing}.")

    slug = source_path.stem
    published_at = _coerce_datetime(post.get("published_at"), "published_at", source_path)
    updated_at = (
        _coerce_datetime(post.get("updated_at"), "updated_at", source_path)
        if post.get("updated_at")
        else published_at
    )
    content = post.content.strip()

    return BlogPost(
        slug=slug,
        title=_coerce_string(post.get("title")),
        seo_title=(_coerce_string(post.get("seo_title")) or _coerce_string(post.get("title"))),
        description=_coerce_string(post.get("description")),
        content=content,
        html=markdown.markdown(content, extensions=BLOG_MARKDOWN_EXTENSIONS),
        published_at=published_at,
        updated_at=updated_at,
        author=_coerce_string(post.get("author")) or BLOG_DEFAULT_AUTHOR,
        keywords=_coerce_list(post.get("keywords")),
        topics=_coerce_list(post.get("topics")),
        image_url=_absolute_public_url(post.get("image")),
        image_alt=_coerce_string(post.get("image_alt")),
        robots=_coerce_string(post.get("robots")) or INDEX_ROBOTS_POLICY,
        reading_time_minutes=_reading_time_minutes(content),
        source_path=source_path,
    )


def list_blog_posts() -> list[BlogPost]:
    content_dir = get_blog_posts_dir().resolve()
    if not content_dir.exists():
        return []

    posts = []
    for path in content_dir.glob("*.md"):
        try:
            posts.append(load_blog_post(path, content_dir=content_dir))
        except BlogPostValidationError:
            # The pages.E002 system check reports invalid posts before deploy.
            pass
    return sorted(posts, key=lambda post: (post.published_at, post.slug), reverse=True)


def get_blog_post(slug: str) -> BlogPost:
    if not is_blog_slug(slug):
        raise BlogPostNotFound

    content_dir = get_blog_posts_dir().resolve()
    source_path = (content_dir / f"{slug}.md").resolve()
    return load_blog_post(source_path, content_dir=content_dir)


def iter_blog_post_validation_errors() -> list[BlogPostValidationError]:
    errors = []
    content_dir = get_blog_posts_dir().resolve()
    if not content_dir.exists():
        return errors

    for source_path in content_dir.glob("*.md"):
        try:
            load_blog_post(source_path, content_dir=content_dir)
        except BlogPostValidationError as exc:
            errors.append(exc)
    return errors


def blog_index_url() -> str:
    return build_canonical_url(reverse("blog_posts"))


def blog_post_schema(post: BlogPost) -> dict:
    schema = {
        "@context": "https://schema.org",
        "@type": "BlogPosting",
        "headline": post.title,
        "description": post.description,
        "image": post.image_url,
        "url": post.canonical_url,
        "datePublished": post.published_at.isoformat(),
        "dateModified": post.updated_at.isoformat(),
        "author": {"@type": "Person", "name": post.author},
        "publisher": {
            "@type": "Organization",
            "name": "Rowset",
            "logo": {"@type": "ImageObject", "url": default_blog_image_url()},
        },
        "articleBody": post.content,
        "mainEntityOfPage": {"@type": "WebPage", "@id": post.canonical_url},
    }
    keywords = post.metadata_keywords
    if keywords:
        schema["keywords"] = list(keywords)
    return schema


def blog_index_schema(posts: list[BlogPost]) -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "Blog",
        "name": BLOG_TITLE,
        "description": BLOG_DESCRIPTION,
        "url": blog_index_url(),
        "publisher": {
            "@type": "Organization",
            "name": "Rowset",
            "logo": {"@type": "ImageObject", "url": default_blog_image_url()},
        },
        "blogPost": [
            {
                "@type": "BlogPosting",
                "headline": post.title,
                "description": post.description,
                "url": post.canonical_url,
                "datePublished": post.published_at.isoformat(),
            }
            for post in posts
        ],
    }


def json_ld(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
