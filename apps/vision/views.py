"""Mobile capture views for Slice 5."""

from __future__ import annotations

from collections import Counter

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import (
    Http404,
    HttpRequest,
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseRedirect,
    JsonResponse,
)
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_safe

from .models import Detection, InventoryPhoto, ProductLabel
from .services import apply_to_stock, run_inference


def _require_org(request: HttpRequest):
    org = getattr(request, "organization", None)
    if org is None:
        raise Http404("No active organization for this user")
    return org


@login_required
@require_http_methods(["GET", "POST"])
def capture(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        org = _require_org(request)
        image = request.FILES.get("image")
        if image is None:
            return HttpResponseBadRequest("Missing image upload")
        photo = InventoryPhoto.all_objects.create(
            organization=org,
            uploaded_by=request.user,
            image=image,
        )
        try:
            run_inference(photo)
        except Exception as exc:  # noqa: BLE001
            messages.error(request, f"Inference failed: {exc}")
        return HttpResponseRedirect(reverse("vision:photo_detail", args=[photo.id]))

    return render(request, "vision/capture.html")


@login_required
@require_safe
def photo_list(request: HttpRequest) -> HttpResponse:
    org = _require_org(request)
    photos = InventoryPhoto.all_objects.filter(organization=org).order_by("-created_at")[:50]
    return render(request, "vision/photo_list.html", {"photos": photos})


@login_required
@require_safe
def photo_detail(request: HttpRequest, photo_id: int) -> HttpResponse:
    org = _require_org(request)
    photo = get_object_or_404(
        InventoryPhoto.all_objects, pk=photo_id, organization=org
    )
    detections = Detection.all_objects.filter(photo=photo).order_by("label")
    counts = Counter(d.label for d in detections)
    mappings = {
        pl.label: pl
        for pl in ProductLabel.all_objects.filter(organization=org)
    }
    rows = [
        {
            "label": label,
            "count": count,
            "matched": label in mappings,
            "product": mappings[label].product if label in mappings else None,
            "multiplier": (
                mappings[label].multiplier if label in mappings else None
            ),
        }
        for label, count in sorted(counts.items())
    ]
    return render(
        request,
        "vision/photo_detail.html",
        {"photo": photo, "rows": rows, "any_matched": any(r["matched"] for r in rows)},
    )


@login_required
@require_http_methods(["POST"])
def photo_apply(request: HttpRequest, photo_id: int) -> HttpResponse:
    org = _require_org(request)
    photo = get_object_or_404(
        InventoryPhoto.all_objects, pk=photo_id, organization=org
    )
    try:
        report = apply_to_stock(photo, performed_by=request.user)
    except ValueError as exc:
        messages.error(request, str(exc))
        return HttpResponseRedirect(
            reverse("vision:photo_detail", args=[photo.id])
        )
    matched = sum(1 for r in report.values() if r["matched"])
    unmatched = sum(1 for r in report.values() if not r["matched"])
    messages.success(
        request,
        f"Applied {matched} label(s) to stock"
        + (f", {unmatched} unmapped skipped" if unmatched else ""),
    )
    return HttpResponseRedirect(reverse("vision:photo_list"))


@require_safe
def manifest(request: HttpRequest) -> JsonResponse:
    return JsonResponse(
        {
            "name": "Stockpilot Capture",
            "short_name": "Stockpilot",
            "start_url": "/capture/",
            "scope": "/capture/",
            "display": "standalone",
            "background_color": "#0f172a",
            "theme_color": "#2563eb",
            "icons": [
                {
                    "src": "/static/vision/icon.svg",
                    "sizes": "512x512",
                    "type": "image/svg+xml",
                    "purpose": "any maskable",
                }
            ],
        }
    )


@require_safe
def service_worker(request: HttpRequest) -> HttpResponse:
    body = """
const CACHE = "stockpilot-shell-v1";
const SHELL = ["/capture/", "/capture/list/"];
self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).catch(() => {}));
});
self.addEventListener("activate", (e) => self.clients.claim());
self.addEventListener("fetch", (e) => {
  if (e.request.method !== "GET") return;
  e.respondWith(
    fetch(e.request).catch(() => caches.match(e.request))
  );
});
""".strip()
    return HttpResponse(body, content_type="application/javascript")
