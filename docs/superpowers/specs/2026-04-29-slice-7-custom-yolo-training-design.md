# Slice 7 — Custom YOLO Training per Tenant

**Date:** 2026-04-29
**Status:** Approved (autonomous mode — user approved high-level defaults inline)

## Goal

Jeder Tenant kann eigene Training-Datensätze hochladen, Fine-Tuning-Jobs starten und das resultierende Modell für seine eigene Inferenz aktivieren. Generisches COCO-trainiertes YOLO11n bleibt als Fallback.

## Stack-Entscheidungen

| Frage | Entscheidung | Begründung |
|---|---|---|
| Async-Worker | **Celery + Redis** | Training dauert 10–30 min, gehört nicht in einen Request. Redis kommt sowieso in Slice 8. |
| Training-Compute | **CPU (für jetzt)** | `torch+cpu` ist installiert. CUDA-Torch ist 2 GB Install. GPU-Upgrade-Pfad ist dokumentiert, nicht erzwungen. |
| Annotation-UX | **In-Browser-Annotator + AI-Suggestions, ZIP als Admin-Fallback** | SaaS für SMB-Endkunden — externe Tools sind nicht zumutbar. Auto-Suggest reduziert Klick-Aufwand drastisch. |
| Auto-Suggest (primär) | **YOLO11x via existierendem UltralyticsBackend** | Kennt 80 COCO-Klassen (bottle, cup, bowl, book, …) — deckt einen Großteil typischer Lager-Items mit sinnvollen Labels ab. Kein neuer Stack. |
| Auto-Suggest (sekundär) | **SAM 2 (sam2_t.pt, "tiny")** | Findet alle Objekte, auch unbekannte. Output Masken → Bbox-Konvertierung. Liefert grau dargestellte "unbenannte" Vorschläge unterhalb der YOLO-Boxes. |
| Modell-Aktivierung | **Eine aktive YoloModel pro Tenant** (`is_active=True`-Flag) | Linear, kein A/B-Testing. Aktivieren = Flag auf neuem Modell setzen, alte abschalten. |
| Dataset-Mutation | **Frozen-on-train** | Sobald ein TrainingJob startet, ist das Dataset eingefroren. Neue Bilder → neues Dataset. |

## Datenmodell (TENANT_APP — pro Tenant-Schema)

```
Dataset
  - name (str)
  - description (text)
  - status: draft | frozen
  - frozen_at (datetime, nullable)
  - created_at, updated_at
  - created_by (FK User)

TrainingImage
  - dataset (FK)
  - image (ImageField → media/training/<schema>/<dataset_id>/images/)
  - annotations (JSONField)
      list of {class_name: str, x_center: float, y_center: float, width: float, height: float}
      Coords normalized to [0,1]. These are the user-confirmed final labels.
  - auto_suggestions (JSONField)
      Cached AI proposals from YOLO11x + SAM 2:
      [{label: str | null, confidence: float, source: "yolo"|"sam",
        x_center, y_center, width, height}]
  - suggestions_status: pending | running | done | failed
  - suggestions_error (text, blank)

TrainingJob
  - dataset (FK)
  - status: pending | running | completed | failed | cancelled
  - epochs (int, default 50)
  - batch_size (int, default 4)
  - image_size (int, default 640)
  - base_model (str, default "yolo11n.pt" — or path to a previous YoloModel)
  - started_at, finished_at (datetime, nullable)
  - logs (text, last ~10 KB of training output)
  - error (text)
  - output_model (FK → YoloModel, nullable, set on success)
  - celery_task_id (str, nullable — for cancellation)
  - created_by (FK User)
  - created_at

YoloModel
  - name (str)
  - version (auto-incremented per tenant)
  - file (FileField → media/models/<schema>/<id>.pt)
  - source_job (FK TrainingJob, nullable — null for uploaded models)
  - is_active (bool, exactly one True per tenant enforced via signal/save())
  - metrics (JSONField) — mAP50, mAP50-95, precision, recall from validation set
  - class_names (JSONField) — list of class label strings the model knows
  - created_at
```

## Services (apps/training/services.py)

```python
def create_dataset_from_zip(zip_file, name, created_by) -> Dataset:
    """Extracts a YOLO-format ZIP (images/, labels/, optional data.yaml).

    Validates structure, creates Dataset (status=draft), creates one
    TrainingImage per image+matching .txt label, returns the Dataset.
    Class names are read from data.yaml if present; otherwise inferred
    from the .txt labels (class indices).
    """

def freeze_dataset(dataset) -> None:
    """Marks dataset as frozen (no further image edits allowed)."""

def start_training_job(
    dataset, *, epochs=50, batch_size=4, image_size=640,
    base_model="yolo11n.pt", created_by=None
) -> TrainingJob:
    """Freezes dataset if needed, creates TrainingJob (status=pending),
    dispatches the celery task `train_yolo.delay(job.id, schema_name)`.
    Returns the persisted job (caller can poll status)."""

def activate_model(yolo_model) -> None:
    """Atomically: sets is_active=False on all other tenant models,
    sets True on this one. Re-loads UltralyticsBackend cache on next
    inference call."""
```

## Celery Task (apps/training/tasks.py)

```python
@shared_task(bind=True)
def train_yolo(self, job_id: int, schema_name: str):
    """1. tenant_context(schema_name): switch to tenant schema.
       2. Mark job running, save celery_task_id.
       3. Build /tmp/<job_id>/data.yaml + images/ + labels/ from
          TrainingImage rows (80/20 train/val split).
       4. ultralytics.YOLO(base_model).train(
              data=yaml_path, epochs=..., imgsz=..., batch=...,
              project=/tmp/<job_id>, name="run", exist_ok=True
          )
       5. On success:
          - Copy <run_dir>/weights/best.pt → media/models/<schema>/<id>.pt
          - Read results.csv for final metrics
          - Create YoloModel(source_job=job, file=path, metrics=...)
          - Update job.output_model, status=completed, finished_at
       6. On failure: log to job.error, status=failed
       7. Always: capture last ~10 KB of stdout to job.logs
    """
```

Tenant context inside the worker is set via `django_tenants.utils.tenant_context()` using the `schema_name` passed as a Celery argument (must be a primitive — Tenant model isn't pickle-safe).

## Inference-Backend-Update

`apps.vision.inference.UltralyticsBackend._load`:

```python
def _load(self):
    if self._model is None:
        # Per-tenant active model wins; fall back to project default
        try:
            from apps.training.models import YoloModel
            active = YoloModel.objects.filter(is_active=True).first()
            model_path = active.file.path if active else settings.VISION_YOLO_MODEL
        except Exception:
            model_path = settings.VISION_YOLO_MODEL
        self._model = ultralytics.YOLO(model_path)
    return self._model
```

The `try/except` covers the public schema (no `training` tables) — falls back to default. Within a tenant request, `YoloModel.objects` queries the tenant's schema.

## Admin (apps/training/admin.py)

- `DatasetAdmin` — list view, action "Upload ZIP" linking to a custom view; "Freeze" action
- `TrainingImageAdmin` — read-only mostly, separate from dataset for inspection
- `TrainingJobAdmin` — action "Start training" creates+queues; status-coloured chips; show logs in detail view
- `YoloModelAdmin` — action "Activate" (atomic toggle); show metrics; download .pt

## In-Browser-Annotation-UI

`/training/` ist die SaaS-Frontend-Strecke parallel zu `/capture/`:

| Route | Zweck |
|---|---|
| `GET /training/` | Dataset-Liste, "New Dataset"-Button |
| `GET /training/dataset/<id>/` | Dataset-Detail: Bilder-Galerie, Status, "Add Image", "Freeze + Train" |
| `POST /training/dataset/<id>/images/` | Bild hochladen → erzeugt TrainingImage, kicked Celery-Task `generate_suggestions` |
| `GET /training/image/<id>/` | **Annotation-Editor** (Canvas-basiert) |
| `GET /training/image/<id>/suggestions/` | JSON: aktueller Stand `auto_suggestions` (UI-Polling während pending/running) |
| `POST /training/image/<id>/annotations/` | JSON: User-bestätigte Annotations speichern |
| `POST /training/dataset/<id>/upload-zip/` | Admin-Fallback: kompletter YOLO-ZIP |

**Annotation-Editor (HTML5 Canvas + Vanilla JS):**
- Bild als Hintergrund, Canvas overlay
- Bestehende Annotations: solide farbige Boxes mit Label
- YOLO-Suggestions: blau gestrichelt, Label angezeigt → Klick "Accept" promoted zu Annotation
- SAM-Suggestions: grau gestrichelt, kein Label → User muss Label tippen, dann "Accept"
- Tools: New box (drag), Resize (corner-handles), Move (drag center), Delete (Backspace), Undo/Redo
- Class-Picker (Dropdown rechts mit existierenden Tenant-Klassen + "Add new")
- Touch-Support für Mobile (passives Pointer-Events-API)
- Auto-Save alle 10s + on-Save-Button

## Endpoints (Admin)

```
POST /admin/training/dataset/upload-zip/   — multipart, ZIP file + name
GET  /admin/training/job/<id>/logs/        — streamed log tail (HTML, auto-refresh)
```

## Infrastructure changes

### `docker-compose.yml`

Add Redis service:
```yaml
redis:
  image: redis:7-alpine
  ports: ["127.0.0.1:6379:6379"]
  healthcheck:
    test: ["CMD", "redis-cli", "ping"]
```

Add Celery worker (manual `celery -A stockpilot worker -l info` in dev; service later in Slice 8).

### `stockpilot/settings/base.py`

```python
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://127.0.0.1:6379/0")
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "redis://127.0.0.1:6379/1")
CELERY_TASK_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TIMEZONE = TIME_ZONE
```

### `stockpilot/celery.py` (new)

Standard Celery-Django boilerplate.

### `requirements.txt`

```
celery
redis
PyYAML  # for data.yaml parsing
```

SAM 2 lädt sich on first use auto via Ultralytics (`from ultralytics import SAM; SAM("sam2_t.pt")`), keine extra dep.

## Tests

- **Pure-logic** (no Celery, no torch):
  - `test_create_dataset_from_zip_valid_yolo_structure`
  - `test_create_dataset_from_zip_rejects_missing_labels`
  - `test_freeze_dataset_idempotent`
  - `test_activate_model_deactivates_others`
  - `test_annotation_save_endpoint_validates_normalized_coords`
  - `test_suggestion_merge_dedupes_overlapping_yolo_and_sam` (IoU-based)
- **Service-level** (mocked Celery via `CELERY_TASK_ALWAYS_EAGER=True`):
  - `test_start_training_job_freezes_dataset`
  - `test_start_training_job_dispatches_task`
  - `test_generate_suggestions_persists_yolo_results` (with stubbed backend)
- **Integration** (`@pytest.mark.integration`, opt-in):
  - `test_train_yolo_end_to_end` — synthetic dataset, 1 epoch
  - `test_generate_suggestions_with_real_yolo_and_sam` — synthetic image
- **Inference fallback**:
  - `test_ultralytics_backend_uses_active_model_when_present` (mock query)
  - `test_ultralytics_backend_falls_back_to_default`

## GPU upgrade path (documented, not done)

`README.md` gets a "GPU training" section:

```bash
# To enable CUDA training (~10× faster on RTX 3060):
.venv/bin/pip uninstall torch torchvision
.venv/bin/pip install --extra-index-url https://download.pytorch.org/whl/cu121 torch torchvision
# Verify: python -c "import torch; print(torch.cuda.is_available())"
```

The Celery worker auto-uses GPU if available (Ultralytics auto-detects `cuda`).

## Out of scope

- In-browser annotation UI (use LabelImg / CVAT / Label Studio externally)
- Hyperparameter sweeps / Optuna integration
- Active learning loops (re-train on misclassified production photos)
- Model A/B testing or shadow inference
- Model export to ONNX/TFLite for mobile
- Per-tenant resource quotas (one tenant's training won't preempt another's; Celery serializes by default)
- AGPL / commercial licensing of Ultralytics (separate concern)

## Erfolgskriterien

- [ ] User uploads YOLO-ZIP, Dataset is created, status=draft
- [ ] "Start training" creates a TrainingJob, status moves pending → running → completed (or failed)
- [ ] On success a YoloModel is created with a non-zero `file` and metrics JSON populated
- [ ] "Activate" makes the new model the one Inference uses on next photo
- [ ] Photo upload via `/capture/` uses the activated custom model (assertable via Detection labels)
- [ ] Cross-tenant: tenant A's model is never loaded for tenant B
- [ ] All non-integration tests green; one opt-in integration test runs end-to-end on the test dataset

## Build-Reihenfolge

1. Add Redis to docker-compose, install celery+redis+pyyaml
2. Create `apps/training` app skeleton + four models
3. Implement services (zip-import, freeze, start-job, activate)
4. Implement Celery task (with stub-able backend hook for tests)
5. Implement admin (dataset, image, job, model)
6. Update vision/inference.py to query active YoloModel
7. Wire stockpilot/celery.py + settings
8. Tests (pure-logic + service-level + 1 integration)
9. README updates: setup, GPU upgrade path, ZIP format expectations
