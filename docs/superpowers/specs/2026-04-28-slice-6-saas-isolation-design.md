# Slice 6 — Echte SaaS-Isolation via django-tenants

**Date:** 2026-04-28
**Branch:** `feat/saas-isolation`

## Goal

Statt Row-Level-Scoping (eine DB, jede Zeile mit `organization_id` + Manager-Filter) bekommt jeder Tenant ein **eigenes Postgres-Schema**. Daten verschiedener Orgs sind auf DB-Ebene physisch getrennt — keine Möglichkeit, durch Bugs in Application-Code-Filtern Daten zu leaken.

## Architektur

- **Postgres only** (django-tenants ist Postgres-only). `docker-compose.yml` startet einen Postgres-Container für lokale Entwicklung.
- **Subdomain-Routing:** `acme.stockpilot.local` → Tenant "acme". Lokal: `*.localhost` (Chrome unterstützt das ohne `/etc/hosts`-Änderung).
- **Public Schema** enthält nur:
  - `tenants.Organization` (extends `TenantMixin`, hat `schema_name`-Feld)
  - `tenants.Domain` (extends `DomainMixin`)
  - `tenants.Membership` (User × Organization × Role — entscheidet, wer auf welche Subdomain darf)
  - `auth.User`, `sessions`, `contenttypes`, `admin` (LogEntry)
- **Tenant Schemas** enthalten:
  - `catalog` (Product, Supplier)
  - `inventory` (Stock, StockMovement)
  - `vision` (InventoryPhoto, Detection, ProductLabel)
  - `forecast` (ForecastSnapshot)
  - `orders` (PurchaseOrder, PurchaseOrderItem)

## Code-Änderungen

### 1. Settings (`stockpilot/settings/base.py`)

```python
SHARED_APPS = (
    "django_tenants",
    "apps.tenants",      # MUST be the tenant app, contains Organization
    "unfold", "unfold.contrib.filters", "unfold.contrib.forms",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
)
TENANT_APPS = (
    "apps.catalog", "apps.inventory", "apps.vision",
    "apps.forecast", "apps.orders",
)
INSTALLED_APPS = list(SHARED_APPS) + [a for a in TENANT_APPS if a not in SHARED_APPS]

DATABASES = {"default": {
    "ENGINE": "django_tenants.postgresql_backend",
    "NAME": os.environ.get("DB_NAME", "stockpilot"),
    "USER": os.environ.get("DB_USER", "stockpilot"),
    "PASSWORD": os.environ.get("DB_PASSWORD", "stockpilot"),
    "HOST": os.environ.get("DB_HOST", "localhost"),
    "PORT": os.environ.get("DB_PORT", "5432"),
}}
DATABASE_ROUTERS = ("django_tenants.routers.TenantSyncRouter",)

TENANT_MODEL = "tenants.Organization"
TENANT_DOMAIN_MODEL = "tenants.Domain"

PUBLIC_SCHEMA_URLCONF = "stockpilot.urls_public"  # admin lives here
ROOT_URLCONF = "stockpilot.urls"                  # tenant URLs (capture/, etc.)

MIDDLEWARE = [
    "django_tenants.middleware.main.TenantMainMiddleware",  # MUST be first
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.tenants.middleware.MembershipAccessMiddleware",  # 403 if non-member
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
```

### 2. `apps/tenants/models.py`

`Organization` extends `TenantMixin` (gives `schema_name` field). New `Domain` extends `DomainMixin`. `Membership` stays — but no longer needs to enforce row scoping.

### 3. Drop `OrgScopedModel`-Pattern aus allen Business-Apps

`apps/catalog`, `apps/inventory`, `apps/vision`, `apps/forecast`, `apps/orders`:
- Remove `from apps.tenants.managers import OrgScopedModel`
- Models inherit `models.Model` again
- Remove `organization` ForeignKey field
- Adjust `unique_together` / `UniqueConstraint` to drop the `organization` member
- `Stock.adjust`, `compute_forecast`, `generate_draft_orders` etc. lose their `organization=...` arguments — the tenant context is implicit per request

### 4. Drop `apps/tenants/managers.py` (the thread-local active-org machinery), drop the old `ActiveOrganizationMiddleware`

Replaced by django-tenants' `TenantMainMiddleware` (subdomain → schema).

### 5. URLs split

- `stockpilot/urls_public.py` — admin only (this serves `app.localhost:8000/admin/` for global admin?)
  - Actually for cleanliness: admin lives on each tenant. Public schema has a "tenant chooser" landing page.
- `stockpilot/urls.py` — `/admin/` + `/capture/` + manifest + sw — tenant-scoped

### 6. Membership access middleware

After `AuthenticationMiddleware`. If `request.tenant.schema_name != "public"` and user is authenticated: require `Membership.objects.filter(user=request.user, organization=request.tenant).exists()` (or superuser). Else 403.

### 7. Migrations

Old `0001_initial.py` from each app are **deleted** and regenerated. Catalog/Inventory/Vision/Forecast/Orders no longer have `organization` FK.

Apply with:
```
python manage.py migrate_schemas --shared    # public schema
python manage.py migrate_schemas             # all tenants (none yet on first boot)
```

### 8. Tests

- Old tests heavily use `OrgScopedModel`, `set_active_organization`, etc. — all that goes away.
- New tests use `django_tenants.test.cases.TenantTestCase` (auto-creates a tenant per class) or `FastTenantTestCase` (reuses tenant across class).
- Custom fixtures need to set up Org A + Domain A and Org B + Domain B for cross-tenant tests.

## Dev-Setup

```bash
docker compose up -d postgres
.venv/bin/pip install -r requirements.txt
.venv/bin/python manage.py migrate_schemas --shared
.venv/bin/python manage.py shell -c "
from apps.tenants.models import Organization, Domain
acme, _ = Organization.objects.get_or_create(
    schema_name='acme', defaults={'name': 'Acme'})
Domain.objects.get_or_create(
    domain='acme.localhost', tenant=acme, is_primary=True)
"
.venv/bin/python manage.py runserver
# → http://acme.localhost:8000/admin/
```

## Out of scope

- Migration tooling that moves existing row-level-scoped data into per-tenant schemas (kein Datenbestand vorhanden)
- Custom Postgres-Auth-Setup (Docker-Container ist nur dev, in Produktion managed Postgres)
- Domain-Verifizierung / SSL pro Tenant (kommt mit eigenem Reverse-Proxy in Produktion)
