from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import Membership, Organization


@admin.register(Organization)
class OrganizationAdmin(ModelAdmin):
    list_display = ("name", "slug", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Membership)
class MembershipAdmin(ModelAdmin):
    list_display = ("user", "organization", "role", "created_at")
    list_filter = ("role", "organization")
    search_fields = ("user__username", "user__email", "organization__name")
    autocomplete_fields = ("user", "organization")
