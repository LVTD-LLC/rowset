from dataclasses import dataclass
from pathlib import Path

import frontmatter
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_slug

from apps.blog.choices import BlogPostStatus
from apps.blog.models import BlogPost

BLOG_POST_CONTENT_DIR = Path(settings.BASE_DIR) / "apps" / "blog" / "content"


class BlogPostSourceError(ValueError):
    pass


@dataclass
class BlogPostSyncResult:
    scanned: int = 0
    created: int = 0
    updated: int = 0


@dataclass(frozen=True)
class BlogPostSource:
    path: Path
    title: str
    description: str
    slug: str
    tags: str
    content: str
    status: str
    icon: str
    image: str


def sync_blog_posts_from_markdown(content_dir=None):
    result = BlogPostSyncResult()

    for source in load_blog_post_sources(content_dir):
        result.scanned += 1
        post = BlogPost.objects.filter(slug=source.slug).order_by("id").first()
        defaults = {
            "title": source.title,
            "description": source.description,
            "tags": source.tags,
            "content": source.content,
            "status": source.status,
            "icon": source.icon,
            "image": source.image,
        }

        if post is None:
            BlogPost.objects.create(slug=source.slug, **defaults)
            result.created += 1
            continue

        changed_fields = [
            field_name
            for field_name, value in defaults.items()
            if current_post_value(post, field_name) != value
        ]
        if not changed_fields:
            continue

        for field_name in changed_fields:
            value = defaults[field_name]
            setattr(post, field_name, value)
        post.save(update_fields=[*changed_fields, "updated_at"])
        result.updated += 1

    return result


def current_post_value(post, field_name):
    value = getattr(post, field_name)
    if field_name in {"icon", "image"}:
        return value.name
    return value


def load_blog_post_sources(content_dir=None):
    content_path = Path(content_dir or BLOG_POST_CONTENT_DIR)
    if not content_path.exists():
        return []

    sources = [
        load_blog_post_source(path, content_path) for path in iter_blog_post_files(content_path)
    ]
    validate_unique_source_slugs(sources, content_path)
    return sources


def validate_unique_source_slugs(sources, content_path):
    seen = {}
    for source in sources:
        if source.slug not in seen:
            seen[source.slug] = source.path
            continue

        first_path = seen[source.slug].relative_to(content_path)
        second_path = source.path.relative_to(content_path)
        raise BlogPostSourceError(
            f"Duplicate blog post slug {source.slug!r} in {first_path} and {second_path}"
        )


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
    return BlogPostSource(
        path=path,
        title=title,
        description=optional_string(metadata, "description"),
        slug=coerce_slug(metadata.get("slug") or path.stem, path, content_path),
        tags=coerce_tags(metadata.get("tags", "")),
        content=content,
        status=coerce_status(metadata.get("status", BlogPostStatus.DRAFT), path, content_path),
        icon=optional_string(metadata, "icon"),
        image=optional_string(metadata, "image"),
    )


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


def coerce_tags(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple)):
        return ", ".join(str(tag).strip() for tag in value if str(tag).strip())
    return str(value).strip()


def coerce_status(value, path, content_path):
    status = str(value).strip().lower()
    valid_statuses = {choice.value for choice in BlogPostStatus}
    if status not in valid_statuses:
        choices = ", ".join(sorted(valid_statuses))
        raise BlogPostSourceError(
            f"{path.relative_to(content_path)} has invalid status {status!r}; use {choices}"
        )
    return status
