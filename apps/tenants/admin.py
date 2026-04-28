from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import Domain, Membership, Organization


@admin.register(Organization)
class OrganizationAdmin(ModelAdmin):
    list_display = ("name", "slug", "schema_name", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name", "slug", "schema_name")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Domain)
class DomainAdmin(ModelAdmin):
    list_display = ("domain", "tenant", "is_primary")
    list_filter = ("is_primary",)
    search_fields = ("domain",)
    autocomplete_fields = ("tenant",)


@admin.register(Membership)
class MembershipAdmin(ModelAdmin):
    list_display = ("user", "organization", "role", "created_at")
    list_filter = ("role", "organization")
    search_fields = ("user__username", "user__email", "organization__name")
    autocomplete_fields = ("user", "organization")
