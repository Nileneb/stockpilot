from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import Stock, StockMovement


@admin.register(Stock)
class StockAdmin(ModelAdmin):
    list_display = (
        "product",
        "organization",
        "quantity_on_hand",
        "last_counted_at",
        "updated_at",
    )
    list_filter = ("organization",)
    search_fields = ("product__sku", "product__name")
    autocomplete_fields = ("organization", "product")
    readonly_fields = ("updated_at",)


@admin.register(StockMovement)
class StockMovementAdmin(ModelAdmin):
    list_display = (
        "product",
        "organization",
        "quantity_delta",
        "kind",
        "performed_by",
        "created_at",
    )
    list_filter = ("kind", "organization")
    search_fields = ("product__sku", "product__name", "note")
    autocomplete_fields = ("organization", "product", "performed_by")
    readonly_fields = ("created_at",)
