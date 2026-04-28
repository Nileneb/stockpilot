from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import Stock, StockMovement


@admin.register(Stock)
class StockAdmin(ModelAdmin):
    list_display = (
        "product",
        "quantity_on_hand",
        "last_counted_at",
        "updated_at",
    )
    search_fields = ("product__sku", "product__name")
    autocomplete_fields = ("product",)
    readonly_fields = ("updated_at",)


@admin.register(StockMovement)
class StockMovementAdmin(ModelAdmin):
    list_display = (
        "product",
        "quantity_delta",
        "kind",
        "performed_by",
        "created_at",
    )
    list_filter = ("kind",)
    search_fields = ("product__sku", "product__name", "note")
    autocomplete_fields = ("product", "performed_by")
    readonly_fields = ("created_at",)
