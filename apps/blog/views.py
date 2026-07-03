from django.http import Http404
from django.views.generic import TemplateView

from apps.blog import services


class BlogView(TemplateView):
    template_name = "blog/blog_posts.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["blog_posts"] = services.get_blog_posts()
        return context


class BlogPostView(TemplateView):
    template_name = "blog/blog_post.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        try:
            context["blog_post"] = services.get_blog_post(self.kwargs["slug"])
        except services.BlogPostNotFound as exc:
            raise Http404("Blog post not found") from exc
        return context
