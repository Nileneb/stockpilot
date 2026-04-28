"""Manager base class for org-scoped models.

Models inheriting `OrgScopedModel` get an `organization` FK and a default
manager that auto-filters by the active org from thread-local state. The
active org is set by `ActiveOrganizationMiddleware` during a request, and
can be set manually via `set_active_organization()` outside request scope
(tests, management commands).

`all_objects` is the escape hatch — bypasses scoping entirely. Use it for
admin / superuser cross-tenant queries and for fixtures in tests.
"""

from __future__ import annotations

import threading

from django.db import models

_thread_locals = threading.local()


def set_active_organization(org) -> None:
    _thread_locals.active_organization = org


def get_active_organization():
    return getattr(_thread_locals, "active_organization", None)


def clear_active_organization() -> None:
    if hasattr(_thread_locals, "active_organization"):
        del _thread_locals.active_organization


class OrgScopedQuerySet(models.QuerySet):
    def for_organization(self, organization):
        return self.filter(organization=organization)


class OrgScopedManager(models.Manager.from_queryset(OrgScopedQuerySet)):
    """Default manager that auto-filters by the active organization.

    Falls back to all rows when no active org is set (e.g. management
    commands, superuser admin without org switch). Tests should use
    `set_active_organization()` to scope explicitly.
    """

    use_in_migrations = True

    def get_queryset(self) -> models.QuerySet:
        qs = super().get_queryset()
        active = get_active_organization()
        if active is not None:
            return qs.filter(organization=active)
        return qs


class AllObjectsManager(models.Manager.from_queryset(OrgScopedQuerySet)):
    """Escape hatch that bypasses scoping. Use for admin / cross-tenant queries."""

    use_in_migrations = True


class OrgScopedModel(models.Model):
    """Abstract base for any business model that belongs to an Organization."""

    organization = models.ForeignKey(
        "tenants.Organization",
        on_delete=models.CASCADE,
        related_name="+",
    )

    objects = OrgScopedManager()
    all_objects = AllObjectsManager()

    class Meta:
        abstract = True
