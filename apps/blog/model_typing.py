from typing import Protocol, cast

from apps.blog.models import BlogPost


def _django_attr(model: object, name: str) -> object:
    try:
        return getattr(model, name)
    except AttributeError as exc:
        model_name = getattr(model, "__name__", type(model).__name__)
        raise AttributeError(
            f"{model_name} is missing expected Django attribute {name!r}."
        ) from exc


class BlogPostManager(Protocol):
    def all(self) -> object: ...


def blog_post_objects() -> BlogPostManager:
    return cast(BlogPostManager, _django_attr(BlogPost, "objects"))
