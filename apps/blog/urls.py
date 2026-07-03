from django.urls import path

from apps.blog import views

urlpatterns = [
    path("", views.blog_posts_view, name="blog_posts"),
    path("<slug:slug>", views.blog_post_view, name="blog_post"),
]
