"""Public-schema URLs — served on the apex / public domain (e.g. localhost)."""

from django.contrib import admin
from django.urls import path

urlpatterns = [
    # Public schema admin: manage Organizations, Domains, Memberships, Users.
    path("admin/", admin.site.urls),
]
