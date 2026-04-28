from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import Product, Supplier


@admin.register(Supplier)
class SupplierAdmin(ModelAdmin):
    list_display = ("name", "lead_time_days", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "contact_email")


@admin.register(Product)
class ProductAdmin(ModelAdmin):
    list_display = (
        "sku",
        "name",
        "unit",
        "default_supplier",
        "reorder_point",
        "reorder_quantity",
        "is_active",
    )
    list_filter = ("is_active", "unit")
    search_fields = ("sku", "name")
    autocomplete_fields = ("default_supplier",)
