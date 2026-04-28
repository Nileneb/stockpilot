from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import Product, Supplier


@admin.register(Supplier)
class SupplierAdmin(ModelAdmin):
    list_display = ("name", "organization", "lead_time_days", "is_active")
    list_filter = ("is_active", "organization")
    search_fields = ("name", "contact_email")
    autocomplete_fields = ("organization",)


@admin.register(Product)
class ProductAdmin(ModelAdmin):
    list_display = (
        "sku",
        "name",
        "organization",
        "unit",
        "default_supplier",
        "reorder_point",
        "reorder_quantity",
        "is_active",
    )
    list_filter = ("is_active", "unit", "organization")
    search_fields = ("sku", "name")
    autocomplete_fields = ("organization", "default_supplier")
