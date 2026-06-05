from django.urls import path

from apps.mcp_server import views

urlpatterns = [
    path("authorize/", views.authorize, name="mcp_oauth_authorize"),
]
