"""Middleware that resolves the active Organization for the request.

Resolution order:
1. `?org=<id>` query param (admin org-switcher writes the chosen org into the session,
   then redirects without the param).
2. `request.session['active_org_id']`.
3. First Membership of the authenticated user (lexicographic).
4. None (anonymous request, login screens, etc.).

The resolved org is attached as `request.organization` and also pushed into
thread-local state so that `OrgScopedManager` filters automatically.
"""

from __future__ import annotations

from django.utils.deprecation import MiddlewareMixin

from .managers import clear_active_organization, set_active_organization
from .models import Membership, Organization

SESSION_KEY = "active_org_id"


def _resolve_for_user(request) -> Organization | None:
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return None

    requested_id = request.GET.get("org") or request.session.get(SESSION_KEY)
    if requested_id:
        try:
            org = Organization.objects.get(pk=requested_id, is_active=True)
        except (Organization.DoesNotExist, ValueError, TypeError):
            org = None
        else:
            if user.is_superuser or Membership.objects.filter(
                user=user, organization=org
            ).exists():
                request.session[SESSION_KEY] = org.pk
                return org

    membership = (
        Membership.objects.select_related("organization")
        .filter(user=user, organization__is_active=True)
        .order_by("organization__name")
        .first()
    )
    if membership:
        request.session[SESSION_KEY] = membership.organization.pk
        return membership.organization

    if user.is_superuser:
        return Organization.objects.filter(is_active=True).order_by("name").first()

    return None


class ActiveOrganizationMiddleware(MiddlewareMixin):
    def process_request(self, request):
        org = _resolve_for_user(request)
        request.organization = org
        if org is not None:
            set_active_organization(org)
        else:
            clear_active_organization()

    def process_response(self, request, response):
        clear_active_organization()
        return response

    def process_exception(self, request, exception):
        clear_active_organization()
        return None
