"""Tenant-facing training views.

All of these live under `/training/...` on the tenant subdomain. The
TenantMainMiddleware + MembershipAccessMiddleware pair already gates
access; we only add `@login_required`.
"""

from __future__ import annotations

import json
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import (
    HttpRequest,
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseRedirect,
    JsonResponse,
)
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_safe

from . import services
from .models import Dataset, TrainingImage, TrainingJob, YoloModel

logger = logging.getLogger(__name__)


@login_required
@require_safe
def dataset_list(request: HttpRequest) -> HttpResponse:
    return render(
        request,
        "training/dataset_list.html",
        {"datasets": Dataset.objects.all()},
    )


@login_required
@require_http_methods(["GET", "POST"])
def dataset_new(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        action = request.POST.get("action", "create")
        if action == "create":
            ds = Dataset.objects.create(
                name=request.POST["name"].strip(),
                description=request.POST.get("description", "").strip(),
                created_by=request.user,
            )
            return HttpResponseRedirect(reverse("training:dataset_detail", args=[ds.id]))

        if action == "import_zip":
            zip_file = request.FILES.get("zip_file")
            if zip_file is None:
                return HttpResponseBadRequest("Missing zip_file")
            try:
                ds = services.create_dataset_from_zip(
                    zip_file.read(),
                    name=request.POST["name"].strip(),
                    created_by=request.user,
                )
            except Exception as exc:  # noqa: BLE001
                messages.error(request, f"Import failed: {exc}")
                return HttpResponseRedirect(reverse("training:dataset_new"))
            messages.success(
                request,
                f"Imported {ds.images.count()} image(s) from ZIP.",
            )
            return HttpResponseRedirect(reverse("training:dataset_detail", args=[ds.id]))

        return HttpResponseBadRequest("Unknown action")

    return render(request, "training/dataset_new.html")


@login_required
@require_http_methods(["GET", "POST"])
def dataset_detail(request: HttpRequest, dataset_id: int) -> HttpResponse:
    dataset = get_object_or_404(Dataset, pk=dataset_id)

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "add_image":
            image = request.FILES.get("image")
            if image is None:
                return HttpResponseBadRequest("Missing image")
            services.add_image(dataset, image_file=image, uploaded_by=request.user)
            messages.success(request, "Image uploaded; AI suggestions will appear shortly.")
            return HttpResponseRedirect(reverse("training:dataset_detail", args=[dataset.id]))

        if action == "start_training":
            try:
                job = services.start_training_job(
                    dataset,
                    epochs=int(request.POST.get("epochs", 50)),
                    batch_size=int(request.POST.get("batch_size", 4)),
                    image_size=int(request.POST.get("image_size", 640)),
                    created_by=request.user,
                )
            except ValueError as exc:
                messages.error(request, str(exc))
                return HttpResponseRedirect(reverse("training:dataset_detail", args=[dataset.id]))
            messages.success(request, f"Training job #{job.id} queued.")
            return HttpResponseRedirect(reverse("training:job_list"))

        return HttpResponseBadRequest("Unknown action")

    return render(request, "training/dataset_detail.html", {"dataset": dataset})


@login_required
@require_safe
def image_annotate(request: HttpRequest, image_id: int) -> HttpResponse:
    image = get_object_or_404(TrainingImage, pk=image_id)
    return render(request, "training/image_annotate.html", {"image": image})


@login_required
@require_http_methods(["GET", "POST"])
def image_annotations(request: HttpRequest, image_id: int) -> JsonResponse:
    image = get_object_or_404(TrainingImage, pk=image_id)

    if request.method == "GET":
        return JsonResponse({"annotations": image.annotations})

    if not image.dataset.is_editable:
        return JsonResponse({"error": "Dataset is frozen"}, status=400)

    try:
        body = json.loads(request.body or b"{}")
        services.save_annotations(image, body.get("annotations", []))
    except Exception as exc:  # noqa: BLE001
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse({"ok": True, "count": len(image.annotations)})


@login_required
@require_safe
def image_suggestions(request: HttpRequest, image_id: int) -> JsonResponse:
    image = get_object_or_404(TrainingImage, pk=image_id)
    return JsonResponse({
        "status": image.suggestions_status,
        "suggestions": image.auto_suggestions,
        "error": image.suggestions_error,
    })


@login_required
@require_safe
def job_list(request: HttpRequest) -> HttpResponse:
    jobs = TrainingJob.objects.select_related("dataset", "output_model").all()
    return render(request, "training/job_list.html", {"jobs": jobs})


@login_required
@require_safe
def model_list(request: HttpRequest) -> HttpResponse:
    models = YoloModel.objects.all()
    return render(request, "training/model_list.html", {"models": models})


@login_required
@require_http_methods(["POST"])
def model_activate(request: HttpRequest, model_id: int) -> HttpResponse:
    model = get_object_or_404(YoloModel, pk=model_id)
    services.activate_model(model)
    messages.success(request, f"Activated {model.name}")
    return HttpResponseRedirect(reverse("training:model_list"))
