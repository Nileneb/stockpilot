from django.contrib import admin, messages
from unfold.admin import ModelAdmin

from .models import PurchaseOrder, PurchaseOrderItem
from .services import generate_draft_orders, mark_received, submit_order


class PurchaseOrderItemInline(admin.TabularInline):
    model = PurchaseOrderItem
    extra = 0
    fields = ("product", "quantity", "received_quantity", "notes")
    autocomplete_fields = ("product",)
    readonly_fields = ("received_quantity",)


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(ModelAdmin):
    list_display = (
        "reference",
        "organization",
        "supplier",
        "status",
        "created_at",
        "submitted_at",
        "received_at",
    )
    list_filter = ("status", "organization", "supplier")
    search_fields = ("reference", "supplier__name", "notes")
    autocomplete_fields = ("organization", "supplier", "created_by")
    readonly_fields = ("reference", "created_at", "submitted_at", "received_at")
    inlines = (PurchaseOrderItemInline,)
    actions = ("action_generate_drafts", "action_submit", "action_mark_received")

    @admin.action(description="Generate draft orders for active organization")
    def action_generate_drafts(self, request, queryset):
        org = getattr(request, "organization", None)
        if org is None:
            self.message_user(
                request,
                "No active organization on the request",
                level=messages.ERROR,
            )
            return
        report = generate_draft_orders(org, created_by=request.user)
        msg = f"Created {len(report.created)} draft order(s)"
        if report.skipped_no_supplier:
            msg += (
                f"; skipped {len(report.skipped_no_supplier)} product(s) without "
                "default supplier"
            )
        self.message_user(request, msg, level=messages.SUCCESS)

    @admin.action(description="Submit selected orders (send email)")
    def action_submit(self, request, queryset):
        ok, fail = 0, 0
        for order in queryset:
            try:
                submit_order(order)
                ok += 1
            except ValueError as exc:
                self.message_user(
                    request,
                    f"{order.reference}: {exc}",
                    level=messages.ERROR,
                )
                fail += 1
        self.message_user(
            request,
            f"{ok} submitted, {fail} skipped",
            level=messages.SUCCESS if fail == 0 else messages.WARNING,
        )

    @admin.action(description="Mark selected orders as received")
    def action_mark_received(self, request, queryset):
        ok, fail = 0, 0
        for order in queryset:
            try:
                mark_received(order, performed_by=request.user)
                ok += 1
            except ValueError as exc:
                self.message_user(
                    request,
                    f"{order.reference}: {exc}",
                    level=messages.ERROR,
                )
                fail += 1
        self.message_user(
            request,
            f"{ok} received, {fail} skipped",
            level=messages.SUCCESS if fail == 0 else messages.WARNING,
        )


@admin.register(PurchaseOrderItem)
class PurchaseOrderItemAdmin(ModelAdmin):
    list_display = (
        "order",
        "product",
        "quantity",
        "received_quantity",
        "organization",
    )
    list_filter = ("organization",)
    search_fields = ("product__sku", "product__name", "order__reference")
    autocomplete_fields = ("organization", "order", "product")
