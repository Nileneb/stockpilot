# Stockpilot — Design Spec

**Date:** 2026-04-28
**Owner:** Benedikt Linn
**Status:** Approved (autonomous mode — user delegated decisions)

## Goal

Multi-tenant Einkauf-/Logistikhelfer für KMU. Foto-basierte Bestandserfassung, ML-gestützte Verbrauchsprognose, automatische Bestellvorschläge. Jedes Unternehmen kann eigene Produkte und Lieferanten pflegen, eigene Bestände führen, eigene Bestellworkflows fahren.

## Stack-Entscheidungen

- **Backend:** Django 5.x + Django REST Framework
- **Admin/CRUD:** Django Admin mit Unfold-Theme (Filament-Äquivalent — auto-generated CRUD aus Models)
- **DB:** PostgreSQL (Produktion) / SQLite (Dev-Boot, später migriert)
- **Async/ML:** Celery + Redis für Inferenz- und Forecast-Tasks
- **CV:** Ultralytics YOLO26 (PyTorch) — Custom-Training pro Tenant via Fine-Tuning später
- **Forecast:** statsforecast (klassische TS-Modelle, leichtgewichtig) für Slice 3
- **Multi-Tenancy:** Row-Level Scoping via `Organization` FK auf allen Business-Models (Upgrade-Pfad zu django-tenants schema-isoliert in Slice 5+)
- **Tests:** pytest-django

Begründung: Django + Unfold liefert das gleiche "Models definieren → Admin steht" wie Filament bei Laravel. ML lebt im selben Repo (statt zwei Codebases wie Laravel + MayringCoder).

## Scope-Decomposition

Das Gesamtprojekt zerfällt in 5 unabhängige Slices, jede mit eigenem Spec/Plan/Implementation-Zyklus:

| # | Slice | Inhalt | Status |
|---|-------|--------|--------|
| 1 | **Foundation** | Multi-Tenant-Modell, Produkt/Lieferanten/Bestand-CRUD, Unfold-Admin, Auth | **dieses Spec** |
| 2 | **Foto-Capture** | Upload-Endpunkt, YOLO-Inferenz, manuelle Korrektur-UI, Stock-Update | später |
| 3 | **Forecasting** | Verbrauchs-Zeitreihe, Reorder-Point, Prognose | später |
| 4 | **Bestellautomatik** | Order-Generierung, Lieferanten-Mail/EDI, Approval-Workflow | später |
| 5 | **Mobile/PWA Capture** | Optimierte Capture-UX, Offline-Sync | später |

Dieses Spec deckt **nur Slice 1** im Detail ab.

---

## Slice 1 — Foundation (in scope today)

### Datenmodell

```
Organization (Tenant)
  - id, name, slug, created_at
  - is_active

Membership (User ↔ Organization)
  - user (FK → auth.User)
  - organization (FK → Organization)
  - role: enum [owner, manager, staff]
  - created_at
  - unique(user, organization)

Supplier (org-scoped)
  - organization (FK)
  - name, contact_email, contact_phone
  - lead_time_days (int) — wie lange dauert die Lieferung typischerweise
  - notes

Product (org-scoped)
  - organization (FK)
  - sku (unique per org)
  - name, description
  - unit (enum: piece, kg, l, pack)
  - default_supplier (FK → Supplier, nullable)
  - reorder_point (int) — Trigger-Schwelle für späteren Bestellvorschlag
  - reorder_quantity (int) — Standard-Nachbestellmenge
  - is_active

Stock (org-scoped, eine Zeile pro Produkt × Standort — Standort später, MVP: ein Default-Lager)
  - organization (FK)
  - product (FK)
  - quantity_on_hand (decimal)
  - last_counted_at
  - unique(organization, product)

StockMovement (org-scoped, Audit-Log)
  - organization (FK)
  - product (FK)
  - quantity_delta (decimal, signed)
  - kind: enum [count_correction, manual_in, manual_out, photo_count, order_received, consumption]
  - performed_by (FK → User)
  - note
  - created_at
```

Alle Business-Models haben `organization` FK + Custom-Manager `OrgScopedManager`, der per Default nach aktivem Tenant filtert. Aktiver Tenant kommt aus Middleware (`request.organization`) — gewählt via Subdomain in Prod, via Session-Switcher im Dev/Admin.

### Architektur

```
stockpilot/
├── manage.py
├── pyproject.toml          # Poetry / pip-tools
├── stockpilot/             # Project package
│   ├── settings/
│   │   ├── base.py
│   │   ├── dev.py          # SQLite, DEBUG
│   │   └── prod.py         # Postgres, secrets via env
│   ├── urls.py
│   ├── celery.py           # Stub für Slice 2+
│   └── wsgi.py
├── apps/
│   ├── tenants/            # Organization, Membership, Middleware
│   ├── catalog/            # Product, Supplier
│   └── inventory/          # Stock, StockMovement
├── tests/
└── docs/
```

Eigene Apps statt Mega-App. Jede App hat `models.py`, `admin.py`, `tests.py`. URL-Routing wird in Slice 2+ mit DRF nachgerüstet — Slice 1 ist nur Admin-getrieben.

### Auth

- Django built-in `auth.User`
- Login via Admin (`/admin/login`)
- Custom `Membership`-Model entscheidet, welche Orgs der User sehen darf
- Superuser hat Cross-Tenant-Zugriff (Support-Use-Case)
- Org-Switcher im Admin-Header (Unfold custom action)

### Tenant-Resolution-Strategie

MVP: Org-ID in der Session (`request.session['active_org_id']`). Middleware hängt `request.organization` an. Manager-Layer filtert automatisch.

Begründung: Subdomain-Routing braucht DNS-Setup, lohnt sich erst bei echten Kunden. Session reicht für Slice 1–4.

### Out of scope für Slice 1

- Foto-Upload, YOLO, irgendein ML-Code
- Forecasting
- Bestell-Workflow / Lieferanten-API
- Frontend außerhalb von Django Admin
- Mehrere Lager/Standorte pro Org (kommt mit Slice 4)
- 2FA / SSO
- Subdomain-basiertes Tenant-Routing
- Schema-isolierte Multi-Tenancy (django-tenants)

### Testing

- pytest-django
- Smoke-Test pro App: kann Model angelegt werden, kann Admin geladen werden
- Tenant-Scoping-Test: User von Org A darf Stock von Org B nicht im Manager-Default sehen
- Membership-Test: User ohne Membership → kein Zugriff

### Erfolgskriterien Slice 1

- [ ] `python manage.py runserver` startet ohne Fehler
- [ ] `/admin/` zeigt Unfold-styled Admin
- [ ] Zwei Orgs anlegbar, jede mit eigenen Produkten/Lieferanten/Bestand
- [ ] Org-Switcher funktioniert
- [ ] User von Org A sieht in Admin nur Org-A-Daten (außer Superuser)
- [ ] StockMovement loggt jede Quantity-Änderung
- [ ] Alle Tests grün

### Nicht-Ziele

- Performance-Tuning, Caching
- Production-Deploy
- I18n (English-Strings im Code, deutsche User-Strings später)

## Build-Reihenfolge

1. venv + Dependencies (Django, Unfold, pytest-django)
2. `django-admin startproject stockpilot` + Settings-Split
3. App `tenants` — Organization, Membership, Middleware
4. App `catalog` — Product, Supplier
5. App `inventory` — Stock, StockMovement
6. Admin-Registrierung mit Unfold
7. Migrations + Superuser + manueller Smoke-Test
8. Pytest-Tests für Tenant-Scoping
9. Initial Commit
