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

# 5. Ersten Tenant + Domain anlegen
.venv/bin/python manage.py shell -c "
from apps.tenants.models import Organization, Domain
acme = Organization.objects.create(schema_name='acme', name='Acme')
Domain.objects.create(domain='acme.localhost', tenant=acme, is_primary=True)
"

# 6. Server starten
.venv/bin/python manage.py runserver
```

Aufrufen:
- `http://localhost:8000/admin/` → Public-Admin: Organizations, Domains, Memberships, Users
- `http://acme.localhost:8000/admin/` → Acme-Tenant-Admin: Products, Suppliers, Stock, Photos, Forecasts, Orders
- `http://acme.localhost:8000/capture/` → Mobile-PWA-Capture für Acme

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
└── orders/    # PurchaseOrder, PurchaseOrderItem + email-based supplier workflow

stockpilot/
├── settings/{base,dev}.py
├── urls.py        # tenant URLs (acme.localhost:8000/admin/, /capture/)
└── urls_public.py # public-schema URLs (localhost:8000/admin/)
```

## Specs

Per-Slice-Designs in `docs/superpowers/specs/`:

1. `2026-04-28-stockpilot-design.md` — Foundation
2. `2026-04-28-slice-2-vision-design.md` — Foto-Capture mit YOLO
3. `2026-04-28-slice-3-forecast-design.md` — Verbrauchs-Forecasting
4. `2026-04-28-slice-4-orders-design.md` — Bestellautomatik
5. `2026-04-28-slice-5-pwa-capture-design.md` — Mobile/PWA
6. `2026-04-28-slice-6-saas-isolation-design.md` — django-tenants Schema-Isolation
