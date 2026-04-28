# Slice 2 — Foto-Capture (Computer Vision)

**Date:** 2026-04-28

## Goal

User lädt Foto vom Lager hoch, System erkennt Objekte mit YOLO, schlägt Bestandskorrektur vor, User bestätigt → Stock + Audit-Log werden upgedatet.

## Architektur

```
upload (admin)
    ↓
InventoryPhoto (status: uploaded)
    ↓
admin action "Run inference"
    ↓
InferenceBackend.detect(image_path) → list[DetectionResult]
    ↓
Detection rows persisted, photo.status = processed
    ↓
admin action "Apply to stock"
    ↓
group detections by label, look up ProductLabel mapping per org,
    call Stock.adjust(kind=PHOTO_COUNT, is_count=True, delta=count*multiplier)
    photo.status = applied
```

**Inference-Backend ist abstrakt.** Default = `StubBackend` (deterministische Fake-Detections, keine ML-Deps). `UltralyticsBackend` (echtes YOLO26) lazy-importiert ultralytics — wer es nutzen will, installiert `requirements-ml.txt`. Auswahl via Setting `VISION_INFERENCE_BACKEND`.

Begründung: Tests, CI und Erst-Boot funktionieren ohne 2 GB Torch. Real-Modell ist Opt-In.

## Datenmodell

```
InventoryPhoto (org-scoped)
  - image (ImageField → media/photos/<org_id>/...)
  - uploaded_by (FK → User)
  - status: uploaded|processing|processed|applied|failed
  - error: str (für failed)
  - created_at

Detection (org-scoped)
  - photo (FK)
  - label (str — z. B. "bottle", "can")
  - confidence (decimal 0..1)
  - bbox_x, bbox_y, bbox_w, bbox_h (decimal, normalized 0..1, nullable)
  - created_at

ProductLabel (org-scoped) — Mapping yolo_label → Product
  - label (str)  -- the model's class name
  - product (FK)
  - multiplier (decimal, default 1) -- 1 detection of "pack" might = 6 units of product
  - unique(organization, label)
```

## Out of scope

- Custom-Training pro Tenant (kommt später)
- Async-Inference via Celery (später; MVP ist synchron im Admin)
- Bbox-Visualisierung im Admin (text-only Detection-Liste reicht)

## Tests

- StubBackend liefert deterministische Detections für eine Test-Datei
- Apply-to-stock erzeugt korrekte StockMovements unter Multiplier-Anwendung
- Cross-Tenant: ProductLabel von Org A wird in Photo von Org B nicht gematcht
- Photo ohne Mapping → wird übersprungen, keine StockMovement erzeugt
