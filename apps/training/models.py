from __future__ import annotations

from django.conf import settings
from django.db import connection, models, transaction


def _training_image_path(instance: "TrainingImage", filename: str) -> str:
    schema = getattr(connection, "schema_name", "public")
    return f"training/{schema}/{instance.dataset_id}/images/{filename}"


def _yolo_model_path(instance: "YoloModel", filename: str) -> str:
    schema = getattr(connection, "schema_name", "public")
    return f"models/{schema}/{filename}"


class Dataset(models.Model):
    """A collection of labeled images, sealed for training once frozen."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        FROZEN = "frozen", "Frozen"

    name = models.CharField(max_length=140)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.DRAFT)
    frozen_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="training_datasets",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"{self.name} ({self.status})"

    @property
    def is_editable(self) -> bool:
        return self.status == self.Status.DRAFT


class TrainingImage(models.Model):
    """One labeled image inside a Dataset."""

    class SuggestionsStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        DONE = "done", "Done"
        FAILED = "failed", "Failed"

    dataset = models.ForeignKey(
        Dataset,
        on_delete=models.CASCADE,
        related_name="images",
    )
    image = models.ImageField(upload_to=_training_image_path)

    # User-confirmed annotations (used for training).
    # Schema: [{"label": str, "x_center": 0..1, "y_center": 0..1,
    #           "width": 0..1, "height": 0..1}, ...]
    annotations = models.JSONField(default=list, blank=True)

    # AI-generated proposals (cached; the user picks/edits before saving as
    # annotations).
    # Schema: [{"label": str | null, "confidence": 0..1,
    #           "source": "yolo" | "sam",
    #           "x_center": 0..1, "y_center": 0..1,
    #           "width": 0..1, "height": 0..1}, ...]
    auto_suggestions = models.JSONField(default=list, blank=True)
    suggestions_status = models.CharField(
        max_length=8,
        choices=SuggestionsStatus.choices,
        default=SuggestionsStatus.PENDING,
    )
    suggestions_error = models.TextField(blank=True)

    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="training_images",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("created_at",)
        indexes = [models.Index(fields=("dataset", "created_at"))]

    def __str__(self) -> str:
        return f"Image {self.pk} ({self.dataset.name})"


class TrainingJob(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    dataset = models.ForeignKey(
        Dataset,
        on_delete=models.PROTECT,
        related_name="jobs",
    )
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
    )
    epochs = models.PositiveIntegerField(default=50)
    batch_size = models.PositiveIntegerField(default=4)
    image_size = models.PositiveIntegerField(default=640)
    base_model = models.CharField(
        max_length=200,
        default="yolo11n.pt",
        help_text="Either an Ultralytics short name or a path to a previous "
        "tenant model (.pt).",
    )
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    logs = models.TextField(blank=True)
    error = models.TextField(blank=True)
    output_model = models.ForeignKey(
        "YoloModel",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="produced_by",
    )
    celery_task_id = models.CharField(max_length=64, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="training_jobs",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=("status", "-created_at"))]

    def __str__(self) -> str:
        return f"Job #{self.pk} on {self.dataset.name} ({self.status})"


class YoloModel(models.Model):
    """A trained or uploaded YOLO weights file usable for inference."""

    name = models.CharField(max_length=140)
    version = models.PositiveIntegerField(default=1)
    file = models.FileField(upload_to=_yolo_model_path)
    source_job = models.ForeignKey(
        TrainingJob,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="produced_models",
    )
    is_active = models.BooleanField(default=False)
    metrics = models.JSONField(default=dict, blank=True)
    class_names = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            # At most one active model per tenant schema.
            models.UniqueConstraint(
                fields=("is_active",),
                condition=models.Q(is_active=True),
                name="unique_active_yolo_model_per_tenant",
            )
        ]

    def __str__(self) -> str:
        active = " *active*" if self.is_active else ""
        return f"{self.name} v{self.version}{active}"

    @transaction.atomic
    def activate(self) -> None:
        """Set this model active, deactivate all others atomically.

        `select_for_update` over the currently-active row(s) serializes
        concurrent activate() calls so they don't both clear+set and
        crash on the partial-unique-active constraint.
        """
        list(
            YoloModel.objects.select_for_update().filter(is_active=True)
        )
        YoloModel.objects.filter(is_active=True).exclude(pk=self.pk).update(
            is_active=False
        )
        if not self.is_active:
            self.is_active = True
            self.save(update_fields=["is_active"])
