"""rowset URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from django.urls import include, path

from apps.api.views import api_not_found, api_v1_redirect
from apps.pages.seo import public_sitemap, robots_txt
from apps.pages.views import AccountSignupByPasskeyView, AccountSignupView

urlpatterns = [
    path("admin/", admin.site.urls),
    # Override allauth signup with custom views.
    path(
        "accounts/signup/passkey/",
        AccountSignupByPasskeyView.as_view(),
        name="account_signup_by_passkey",
    ),
    path("accounts/signup/", AccountSignupView.as_view(), name="account_signup"),
    path("accounts/", include("allauth.urls")),
    path("anymail/", include("anymail.urls")),
    path("robots.txt", robots_txt, name="robots_txt"),
    path("api/v1", api_v1_redirect, name="api_v1_redirect_root"),
    path("api/v1/", api_v1_redirect, name="api_v1_redirect_root_slash"),
    path("api/v1/<path:unmatched>", api_v1_redirect, name="api_v1_redirect"),
    path("api/", include("apps.api.urls")),
    path("api/<path:unmatched>", api_not_found, name="api_not_found"),
    path("", include("apps.datasets.urls")),
    path("", include("apps.pages.urls")),
    path("", include("apps.core.urls")),
    path(
        "sitemap.xml",
        public_sitemap,
        name="django.contrib.sitemaps.views.sitemap",
    ),
]

handler500 = "apps.core.views.server_error"
