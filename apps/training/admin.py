from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import Dataset, TrainingImage, TrainingJob, YoloModel


@admin.register(Dataset)
class DatasetAdmin(ModelAdmin):
    list_display = ("name", "status", "image_count", "created_at", "frozen_at")
    list_filter = ("status",)
    search_fields = ("name", "description")
    readonly_fields = ("frozen_at", "created_at", "updated_at")

    @admin.display(description="Images")
    def image_count(self, obj):
        return obj.images.count()


@admin.register(TrainingImage)
class TrainingImageAdmin(ModelAdmin):
    list_display = ("id", "dataset", "annotation_count", "suggestions_status", "created_at")
    list_filter = ("suggestions_status", "dataset")
    search_fields = ("dataset__name",)
    readonly_fields = (
        "auto_suggestions",
        "suggestions_status",
        "suggestions_error",
        "created_at",
        "updated_at",
    )
    autocomplete_fields = ("dataset", "uploaded_by")

    @admin.display(description="# Annotations")
    def annotation_count(self, obj):
        return len(obj.annotations or [])


@admin.register(TrainingJob)
class TrainingJobAdmin(ModelAdmin):
    list_display = ("id", "dataset", "status", "epochs", "started_at", "finished_at")
    list_filter = ("status",)
    search_fields = ("dataset__name", "celery_task_id", "error")
    readonly_fields = (
        "celery_task_id",
        "started_at",
        "finished_at",
        "logs",
        "error",
        "output_model",
        "created_at",
    )
    autocomplete_fields = ("dataset", "created_by")


@admin.register(YoloModel)
class YoloModelAdmin(ModelAdmin):
    list_display = ("name", "version", "is_active", "source_job", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name",)
    readonly_fields = ("created_at", "metrics", "class_names", "source_job")
    actions = ("action_activate",)

    @admin.action(description="Activate selected model")
    def action_activate(self, request, queryset):
        if queryset.count() != 1:
            self.message_user(request, "Select exactly one model to activate.", level="error")
            return
        model = queryset.first()
        model.activate()
        self.message_user(request, f"Activated {model.name}", level="success")
