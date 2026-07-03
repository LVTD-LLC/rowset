from django.http import Http404
from django.shortcuts import render

from apps.blog.services import (
    BLOG_DESCRIPTION,
    BLOG_TITLE,
    BlogPostNotFound,
    blog_index_schema,
    blog_index_url,
    blog_post_schema,
    default_blog_image_url,
    get_blog_post,
    json_ld,
    list_blog_posts,
)


def blog_posts_view(request):
    blog_posts = list_blog_posts()
    return render(
        request,
        "blog/blog_posts.html",
        {
            "blog_title": BLOG_TITLE,
            "blog_description": BLOG_DESCRIPTION,
            "blog_posts": blog_posts,
            "canonical_url": blog_index_url(),
            "og_image_url": default_blog_image_url(),
            "schema_json": json_ld(blog_index_schema(blog_posts)),
        },
    )


def blog_post_view(request, slug):
    try:
        blog_post = get_blog_post(slug)
    except BlogPostNotFound as exc:
        raise Http404("Blog post not found") from exc

    return render(
        request,
        "blog/blog_post.html",
        {
            "blog_post": blog_post,
            "canonical_url": blog_post.canonical_url,
            "schema_json": json_ld(blog_post_schema(blog_post)),
        },
    )
