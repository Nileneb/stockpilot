# Slice 8 — Self-Service Signup + Subdomain Auto-Provisioning

**Status:** approved (auto-mode brainstorm condensed inline)
**Branch:** `feat/slice-8-signup`
**Parent:** `8436c20` (Slice 7 squash on main)

## Why

Bisher muss eine neue Organisation per `manage.py shell` angelegt werden:
`Organization.objects.create(...)` + `Domain.objects.create(...)` +
`Membership.objects.create(role=OWNER)`. Das ist Demo-Skript, keine SaaS.
Slice 8 ersetzt das durch ein öffentliches Signup-Formular auf der
Apex-Domain.

## Rollen-Hierarchie (vom User explizit gefordert)

Drei klar abgegrenzte Tiers, kein Vermischen:

| Tier | Wer | Repräsentation | Berechtigung |
|------|-----|----------------|--------------|
| **Platform-Admin** | Benedikt selbst | `User.is_superuser=True` | Public-Schema-Admin: alle Orgs sehen, deaktivieren, deletieren |
| **Company / Organization** | Tenant-Entität | `tenants.Organization` Row + Postgres-Schema | — (keine Login-Identität, ist ein Container) |
| **User / Employee** | Mitarbeiter einer Org | `User` mit `Membership` zu genau einer (oder mehr) Orgs | Tenant-Subdomain-Zugriff per Membership-Rolle (`OWNER`/`MANAGER`/`STAFF`) |

Slice 8 erschafft beim Signup **immer**: einen `User` + eine `Organization` +
eine `Domain` + eine `Membership(role=OWNER)`. Platform-Admin ist explizit
nicht über Signup erstellbar — nur via `manage.py createsuperuser`.

## Flow

```
Anonymer Besucher auf https://stockpilot.app/
  → "Jetzt Organisation anlegen" Button
  → /signup/ Form: company-name, subdomain-slug, email, password
  → POST /signup/
      ↓ validate slug (regex, reserved-list, uniqueness)
      ↓ validate email (uniqueness in shared User table)
      ↓ services.provision_organization(...)  [atomic]
        - User.objects.create_user(email, password)
        - Organization.objects.create(name, slug)  [auto-creates schema]
        - Domain.objects.create(domain=f"{slug}.stockpilot.app", tenant=org, is_primary=True)
        - Membership.objects.create(user, organization, role=OWNER)
      ↓ login(request, user)
  → 302 → https://{slug}.stockpilot.app/admin/
```

## Validation rules

**Slug (Subdomain):**
- Regex: `^[a-z0-9][a-z0-9-]{1,28}[a-z0-9]$` (3–30 chars, kein Leading/Trailing Dash, lowercase only)
- Reserved-Names: `www`, `admin`, `api`, `app`, `auth`, `mail`, `support`, `help`, `status`, `docs`, `blog`, `signup`, `login`, `logout`, `dashboard`, `static`, `media`, `assets`, `stockpilot`, `public`, `localhost`, `test`, `staging`, `prod`, `production` — case-insensitive Match
- Reject `xn--`-Prefix (IDN/punycode — würde Homograph-Phishing-Subdomains erlauben)
- Uniqueness: `Organization.objects.filter(slug=…).exists()` muss False sein

**Email:** standard Django EmailField + `User.objects.filter(email=…).exists()` ⇒ Konflikt

**Password:** Django's `validate_password()` (min length, common-password-check)

**Company name:** non-empty, ≤120 chars, unique (existing constraint on Organization.name)

## Anti-Squatting

Lightweight v1 — kein dediziertes Rate-Limit-Framework:
- Cache-key `signup:{ip}` via Django's `default` cache backend
- Max 3 Signups / IP / Stunde, sonst 429
- Nicht überengineering; bei echtem Missbrauch später django-ratelimit ziehen

## Out of scope (für v1)

- E-Mail-Verifikation (Owner ist sofort eingeloggt; Email steht aber im DB-Feld bereit für späteren Verify-Flow)
- CAPTCHA (kann nachgezogen werden, falls Bot-Signups auftreten)
- Org-Mitarbeiter-Einladungs-Flow (Owner muss Memberships weiterhin per Tenant-Admin anlegen — separater Slice)
- Custom-Domain-Mapping (`acme.com` → Tenant) — Slice 9 (Production-Setup) Topic
- Self-Service-Org-Löschung
- Billing / Trial-Limits

## Architektur-Entscheidungen

**Wo lebt der Signup-Code?** Inside `apps.tenants` (nicht als eigene App):
- Signup ist Tenant-Management, kein eigener Bounded Context
- Hält Service+Form+View+URLs+Tests in einer App

**URL-Struktur (public schema):**
- `GET /` → minimal Landing-Page mit "Login" + "Signup neue Org" CTAs
- `GET /signup/` → Form
- `POST /signup/` → Provisioning + Redirect
- `GET /login/` → bleibt admin-Login (`/admin/login/`) — Apex-Login ist nicht Slice 8

**Provisioning-Atomarität:**
- `@transaction.atomic` wraps User+Org+Domain+Membership creation
- Wichtig: `auto_create_schema=True` läuft im post_save-Signal von Organization. Wenn das während der Transaktion failt, rollbackt alles (User+Org+Domain+Membership zurück, Schema bleibt allerdings in Postgres als hängendes Schema — django-tenants hat hier eine Lücke; für v1 akzeptiert)
- Tests: prüfen Rollback bei jedem fehlschlagenden Schritt (Slug-Konflikt, Email-Konflikt, etc.)

**Subdomain-Construction:**
- `settings.SIGNUP_DOMAIN_SUFFIX = "localhost"` in dev (so `acme.localhost` baut)
- Production: `"stockpilot.app"` über env-var
- Domain row: `f"{slug}.{SIGNUP_DOMAIN_SUFFIX}"`

## Erfolgskriterien

- [ ] Anonymer User füllt Form → User+Org+Domain+Membership atomar in DB
- [ ] Owner ist nach Signup eingeloggt + redirect auf Subdomain-Admin
- [ ] Reserved-Slug-Versuch ("admin") → Form-Fehler
- [ ] Slug-Konflikt → Form-Fehler, Transaction rollback (kein orphan User)
- [ ] Email-Konflikt → Form-Fehler, Transaction rollback
- [ ] 4. Signup von gleicher IP innerhalb 1h → 429
- [ ] Tests: pure-logic für Slug-Validierung, integration für Provisioning-Service, view-test für Form-Rendering + POST-Path

## Files (geplant)

```
apps/tenants/
├── forms.py        (NEW) SignupForm
├── services.py     (NEW) provision_organization()
├── validators.py   (NEW) validate_slug + RESERVED_SUBDOMAINS
├── views.py        (NEW) signup view, landing
├── urls.py         (NEW) public-only URL config
├── templates/tenants/
│   ├── landing.html
│   └── signup.html
└── tests.py        — covered by tests/test_signup.py

stockpilot/
├── urls_public.py  + path("", include("apps.tenants.urls"))
└── settings/base.py + SIGNUP_DOMAIN_SUFFIX

tests/
└── test_signup.py  — TestCase + TenantTestCase
```
