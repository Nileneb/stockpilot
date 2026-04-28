"""MembershipAccessMiddleware — enforces that a logged-in user accessing a
tenant subdomain has a Membership in that Organization.

Runs after AuthenticationMiddleware (so request.user is populated) and after
TenantMainMiddleware (so request.tenant is set). Skips:
- Anonymous users (let them through to /admin/login/)
- Public schema (no tenant restriction applies)
- Superusers (cross-tenant support access)
"""

from __future__ import annotations

from django.http import HttpResponseForbidden
from django.utils.deprecation import MiddlewareMixin

from .models import Membership


class MembershipAccessMiddleware(MiddlewareMixin):
    def process_request(self, request):
        tenant = getattr(request, "tenant", None)
        if tenant is None or tenant.schema_name == "public":
            return None
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return None
        if user.is_superuser:
            return None
        if not Membership.objects.filter(user=user, organization=tenant).exists():
            return HttpResponseForbidden(
                "You are not a member of this organization."
            )
        return None
