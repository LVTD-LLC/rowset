from typing import Protocol, cast

from apps.blog.models import BlogPost


def _django_attr(model: object, name: str) -> object:
    return getattr(model, name)


class BlogPostManager(Protocol):
    def all(self) -> object: ...


def blog_post_objects() -> BlogPostManager:
    return cast(BlogPostManager, _django_attr(BlogPost, "objects"))
