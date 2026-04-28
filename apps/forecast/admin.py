from django.contrib import admin, messages
from unfold.admin import ModelAdmin

from .models import ForecastSnapshot
from .services import compute_forecast


@admin.register(ForecastSnapshot)
class ForecastSnapshotAdmin(ModelAdmin):
    list_display = (
        "product",
        "daily_consumption_rate",
        "current_stock",
        "days_until_stockout",
        "suggested_reorder_quantity",
        "created_at",
    )
    list_filter = ("method",)
    search_fields = ("product__sku", "product__name")
    autocomplete_fields = ("product",)
    readonly_fields = ("created_at",)


def register_product_action():
    from apps.catalog.admin import ProductAdmin

    @admin.action(description="Compute forecast")
    def action_compute_forecast(modeladmin, request, queryset):
        ok = 0
        for product in queryset:
            compute_forecast(product)
            ok += 1
        modeladmin.message_user(
            request,
            f"Forecast computed for {ok} product(s)",
            level=messages.SUCCESS,
        )

    existing = list(getattr(ProductAdmin, "actions", ()) or ())
    if action_compute_forecast not in existing:
        ProductAdmin.actions = (*existing, action_compute_forecast)


register_product_action()
