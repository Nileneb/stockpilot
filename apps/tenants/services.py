"""Tenant provisioning services.

`provision_organization` is the public API: hand it the validated form
data, get back a (user, organization) tuple — atomically. Failure at any
step rolls back User+Org+Domain+Membership.

Note: django-tenants' `auto_create_schema=True` triggers schema creation
in Organization.save()'s post_save signal. If a later step in the
transaction fails, the schema itself isn't auto-dropped — it stays
hanging until manual cleanup. Acceptable for v1 since slug uniqueness
is checked *before* org creation; the only realistic rollback is a
race on the Domain insert (which is also rare given slug uniqueness).
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction

from .models import Domain, Membership, Organization

logger = logging.getLogger(__name__)


def _domain_for_slug(slug: str) -> str:
    suffix = getattr(settings, "SIGNUP_DOMAIN_SUFFIX", "localhost")
    return f"{slug}.{suffix}"


@transaction.atomic
def provision_organization(
    *,
    company_name: str,
    slug: str,
    email: str,
    password: str,
):
    """Create User + Organization + Domain + Membership in one transaction.

    Returns (user, organization). Caller is expected to log the user in.

    Email is normalized to lowercase so the `username` (= email) and the
    `email` field stay consistent with the form's case-insensitive
    uniqueness check.
    """
    User = get_user_model()

    email = email.lower().strip()
    user = User.objects.create_user(
        username=email,
        email=email,
        password=password,
    )

    org = Organization.objects.create(name=company_name, slug=slug)
    Domain.objects.create(
        domain=_domain_for_slug(slug),
        tenant=org,
        is_primary=True,
    )
    Membership.objects.create(
        user=user,
        organization=org,
        role=Membership.Role.OWNER,
    )

    logger.info(
        "provisioned organization slug=%s user=%s",
        slug, user.username,
    )
    return user, org
