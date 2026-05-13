from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.shortcuts import redirect
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/login/", lambda request: redirect("orders:index"), name="account_login"),
    path("accounts/signup/", lambda request: redirect("orders:index"), name="account_signup"),
    path("accounts/", include("allauth.urls")),
    path("", include("orders.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
