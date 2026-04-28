from django.contrib import admin, messages
from unfold.admin import ModelAdmin

from .models import Detection, InventoryPhoto, ProductLabel
from .services import apply_to_stock, run_inference


@admin.register(InventoryPhoto)
class InventoryPhotoAdmin(ModelAdmin):
    list_display = (
        "id",
        "uploaded_by",
        "status",
        "created_at",
        "processed_at",
        "applied_at",
    )
    list_filter = ("status",)
    search_fields = ("uploaded_by__username",)
    readonly_fields = (
        "status",
        "error",
        "created_at",
        "processed_at",
        "applied_at",
    )
    autocomplete_fields = ("uploaded_by",)
    actions = ("action_run_inference", "action_apply_to_stock")

    def save_model(self, request, obj, form, change):
        if not change and obj.uploaded_by_id is None:
            obj.uploaded_by = request.user
        super().save_model(request, obj, form, change)

    @admin.action(description="Run inference on selected photos")
    def action_run_inference(self, request, queryset):
        ok, fail = 0, 0
        for photo in queryset:
            try:
                run_inference(photo)
                ok += 1
            except Exception as exc:  # noqa: BLE001
                self.message_user(
                    request,
                    f"Photo {photo.pk}: {exc}",
                    level=messages.ERROR,
                )
                fail += 1
        self.message_user(
            request,
            f"Inference complete — {ok} ok, {fail} failed",
            level=messages.SUCCESS if fail == 0 else messages.WARNING,
        )

    @admin.action(description="Apply detections to stock")
    def action_apply_to_stock(self, request, queryset):
        for photo in queryset:
            try:
                report = apply_to_stock(photo, performed_by=request.user)
            except ValueError as exc:
                self.message_user(
                    request,
                    f"Photo {photo.pk}: {exc}",
                    level=messages.ERROR,
                )
                continue
            matched = sum(1 for r in report.values() if r["matched"])
            unmatched = sum(1 for r in report.values() if not r["matched"])
            self.message_user(
                request,
                f"Photo {photo.pk}: {matched} labels applied, "
                f"{unmatched} unmatched",
                level=messages.SUCCESS if unmatched == 0 else messages.WARNING,
            )


@admin.register(Detection)
class DetectionAdmin(ModelAdmin):
    list_display = ("photo", "label", "confidence", "created_at")
    list_filter = ("label",)
    search_fields = ("label",)
    autocomplete_fields = ("photo",)
    readonly_fields = ("created_at",)


@admin.register(ProductLabel)
class ProductLabelAdmin(ModelAdmin):
    list_display = ("label", "product", "multiplier")
    search_fields = ("label", "product__sku", "product__name")
    autocomplete_fields = ("product",)
