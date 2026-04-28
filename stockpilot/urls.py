"""Tenant URLs — served on tenant subdomains (e.g. acme.localhost)."""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from apps.vision import views as vision_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("capture/", include("apps.vision.urls")),
    path("manifest.webmanifest", vision_views.manifest, name="manifest"),
    path("sw.js", vision_views.service_worker, name="service_worker"),
    path("accounts/", include("django.contrib.auth.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
