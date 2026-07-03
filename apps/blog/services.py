from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import frontmatter
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_slug
from django.urls import reverse

BLOG_POST_CONTENT_DIR = Path(settings.BASE_DIR) / "apps" / "blog" / "content"
PUBLISHED_STATUS = "published"
DRAFT_STATUS = "draft"
VALID_STATUSES = {DRAFT_STATUS, PUBLISHED_STATUS}


class BlogPostSourceError(ValueError):
    pass


class BlogPostNotFound(BlogPostSourceError):
    pass


@dataclass(frozen=True)
class BlogPost:
    path: Path
    title: str
    description: str
    slug: str
    content: str
    status: str
    image: str
    published_at: date | datetime | None
    updated_at: date | datetime | None

    def get_absolute_url(self):
        return reverse("blog_post", kwargs={"slug": self.slug})

    @property
    def lastmod(self):
        return self.modified_at

    @property
    def modified_at(self):
        return self.updated_at or self.published_at


def get_blog_posts(content_dir=None, *, strict=True):
    posts = load_blog_post_sources(content_dir, strict=strict)
    published_posts = [post for post in posts if post.status == PUBLISHED_STATUS]
    return sorted(
        published_posts,
        key=lambda post: post.published_at or date.min,
        reverse=True,
    )


def get_blog_post(slug, content_dir=None, *, strict=True):
    for post in get_blog_posts(content_dir, strict=strict):
        if post.slug == slug:
            return post
    raise BlogPostNotFound(f"Blog post {slug!r} was not found.")


def load_blog_post_sources(content_dir=None, *, strict=True):
    content_path = Path(content_dir or BLOG_POST_CONTENT_DIR)
    if not content_path.exists():
        return []

    posts = []
    for path in iter_blog_post_files(content_path):
        try:
            posts.append(load_blog_post_source(path, content_path))
        except BlogPostSourceError:
            if strict:
                raise

    return validate_source_slugs(posts, content_path, strict=strict)


def iter_blog_post_files(content_path):
    return sorted(
        path
        for path in content_path.rglob("*.md")
        if not any(part.startswith(("_", ".")) for part in path.relative_to(content_path).parts)
    )


def load_blog_post_source(path, content_path):
    try:
        with open(path, encoding="utf-8") as file:
            post = frontmatter.load(file)
    except Exception as exc:
        message = f"{path.relative_to(content_path)} could not be read: {exc}"
        raise BlogPostSourceError(message) from exc

    metadata = post.metadata
    content = post.content.strip()
    if not content:
        raise BlogPostSourceError(f"{path.relative_to(content_path)} must include Markdown content")

    title = required_string(metadata, "title", path, content_path)
    description = required_string(metadata, "description", path, content_path)
    slug = coerce_slug(required_string(metadata, "slug", path, content_path), path, content_path)
    status = coerce_status(
        required_string(metadata, "status", path, content_path), path, content_path
    )
    published_at = coerce_date(metadata.get("published_at"))
    if status == PUBLISHED_STATUS and not published_at:
        raise BlogPostSourceError(
            f"{path.relative_to(content_path)} must include published_at when status is published"
        )

    return BlogPost(
        path=path,
        title=title,
        description=description,
        slug=slug,
        content=content,
        status=status,
        image=optional_string(metadata, "image"),
        published_at=published_at,
        updated_at=coerce_date(metadata.get("updated_at")),
    )


def validate_source_slugs(posts, content_path, *, strict=True):
    seen = {}
    unique_posts = []
    for post in posts:
        if post.slug not in seen:
            seen[post.slug] = post.path
            unique_posts.append(post)
            continue

        if not strict:
            continue

        first_path = seen[post.slug].relative_to(content_path)
        second_path = post.path.relative_to(content_path)
        raise BlogPostSourceError(
            f"Duplicate blog post slug {post.slug!r} in {first_path} and {second_path}"
        )
    return unique_posts


def required_string(metadata, field_name, path, content_path):
    value = optional_string(metadata, field_name)
    if not value:
        raise BlogPostSourceError(f"{path.relative_to(content_path)} must include {field_name}")
    return value


def optional_string(metadata, field_name):
    value = metadata.get(field_name, "")
    if value is None:
        return ""
    return str(value).strip()


def coerce_slug(value, path, content_path):
    slug = str(value).strip()
    try:
        validate_slug(slug)
    except ValidationError as exc:
        raise BlogPostSourceError(
            f"{path.relative_to(content_path)} has invalid slug {slug!r}"
        ) from exc
    return slug


def coerce_status(value, path, content_path):
    status = str(value).strip()
    if status not in VALID_STATUSES:
        raise BlogPostSourceError(f"{path.relative_to(content_path)} has invalid status {status!r}")
    return status


def coerce_date(value):
    if isinstance(value, datetime | date):
        return value
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None

    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise BlogPostSourceError(f"Invalid blog post date {text!r}; use YYYY-MM-DD") from exc
