# Stockpilot

Multi-tenant Einkauf-/Logistikhelfer mit Foto-basierter Bestandserfassung (YOLO),
Verbrauchs-Forecasting und Bestellautomatik. Django + Unfold-Admin.

## Branches

- **`main`** — Row-Level-Scoping (eine SQLite/Postgres-DB, alle Models org-scoped). Voll lauffähig, 59 Tests grün.
- **`feat/saas-isolation`** — django-tenants, schema-isolierte Multi-Tenancy. Postgres-only.

## Quickstart auf `feat/saas-isolation`

```bash
# 1. Postgres via Docker starten
docker compose up -d postgres

# 2. Python-Deps
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 3. Public-Schema migrieren (Tenant-Modelle, Auth, Sessions, Admin)
.venv/bin/python manage.py migrate_schemas --shared

# 4. Superuser im Public-Schema
.venv/bin/python manage.py createsuperuser

# 5. Apex-Domain → Public-Schema mappen (damit `localhost` die Landing/Signup-Page bedient)
.venv/bin/python manage.py shell -c "
from apps.tenants.models import Organization, Domain
pub, _ = Organization.objects.get_or_create(
    schema_name='public', defaults={'name': 'Public'}
)
Domain.objects.get_or_create(
    domain='localhost', defaults={'tenant': pub, 'is_primary': True}
)
"

# 6. Server starten
.venv/bin/python manage.py runserver
```

Tenants entstehen ab jetzt **per Self-Service-Signup** (Slice 8) — das obige
Shell-Skript ist nur für die public-Schema-Domain.

Aufrufen:
- `http://localhost:8000/` → Landing-Page
- `http://localhost:8000/signup/` → Self-Service-Signup → erzeugt Org + Domain + Owner + redirect auf Subdomain
- `http://localhost:8000/admin/` → Public-Admin: Organizations, Domains, Memberships, Users
- `http://<slug>.localhost:8000/admin/` → Tenant-Admin: Products, Suppliers, Stock, Photos, Forecasts, Orders, Training
- `http://<slug>.localhost:8000/capture/` → Mobile-PWA-Capture
- `http://<slug>.localhost:8000/training/` → Custom-YOLO-Training (Slice 7)

## Tests

Tests benötigen einen laufenden Postgres-Container (`docker compose up -d postgres`):

```bash
.venv/bin/python -m pytest -q
```

`TenantTestCase` legt für jede Test-Klasse automatisch ein Tenant-Schema an.

## Struktur

```
apps/
├── tenants/   # Organization (TenantMixin), Domain, Membership, MembershipAccessMiddleware
├── catalog/   # Product, Supplier — TENANT_APPS, isoliert pro Schema
├── inventory/ # Stock, StockMovement, Stock.adjust audit helper
├── vision/    # InventoryPhoto, Detection, ProductLabel + UltralyticsBackend (real YOLO)
├── forecast/  # ForecastSnapshot + simple_exponential_smoothing
├── orders/    # PurchaseOrder, PurchaseOrderItem + email-based supplier workflow
└── training/  # Dataset, TrainingImage, TrainingJob, YoloModel + browser annotator

stockpilot/
├── settings/{base,dev}.py
├── urls.py        # tenant URLs (acme.localhost:8000/admin/, /capture/, /training/)
├── urls_public.py # public-schema URLs (localhost:8000/admin/)
└── celery.py      # Celery app for ML jobs (broker: Redis)
```

## Custom YOLO Training (per Tenant)

Slice 7 fügt pro Tenant Fine-Tuning hinzu — Bilder hochladen, im Browser
annotieren (mit YOLO11x + SAM 2 als Vorschlag), Training starten,
Ergebnis-Model aktivieren.

```bash
# Redis als Celery-Broker starten
docker compose up -d redis postgres

# Worker in einem zweiten Terminal:
.venv/bin/celery -A stockpilot worker -l info -c 1

# Browser:
# http://acme.localhost:8000/training/
# 1) Dataset anlegen, Bilder hochladen
# 2) Auf jedem Bild: AI-Vorschläge übernehmen oder eigene Boxen ziehen
# 3) "Training starten" → Job läuft im Worker, neues Modell taucht unter
#    /training/models/ auf, "Aktivieren" klickt es scharf
# 4) /capture/ nutzt ab dann das aktive Tenant-Modell
```

GPU-Empfehlung: lokales Training mit YOLO11n auf der RTX 3060 läuft mit
`batch_size=4 imgsz=640 epochs=50` in ~10 min auf 100 Bildern. SAM 2
benötigt ~3 GB VRAM zusätzlich für die Auto-Suggest-Phase.

ZIP-Import (Power-User-Fallback): unter `/training/dataset/new/` → "ZIP
importieren" akzeptiert das Standard-YOLO-Layout (`images/`, `labels/`,
optional `data.yaml`).

## Specs

Per-Slice-Designs in `docs/superpowers/specs/`:

1. `2026-04-28-stockpilot-design.md` — Foundation
2. `2026-04-28-slice-2-vision-design.md` — Foto-Capture mit YOLO
3. `2026-04-28-slice-3-forecast-design.md` — Verbrauchs-Forecasting
4. `2026-04-28-slice-4-orders-design.md` — Bestellautomatik
5. `2026-04-28-slice-5-pwa-capture-design.md` — Mobile/PWA
6. `2026-04-28-slice-6-saas-isolation-design.md` — django-tenants Schema-Isolation
7. `2026-04-29-slice-7-custom-yolo-training-design.md` — Per-Tenant-YOLO-Training
8. `2026-04-29-slice-8-self-service-signup-design.md` — Self-Service-Signup + Subdomain-Auto-Provisioning
