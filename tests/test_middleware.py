"""Verify ActiveOrganizationMiddleware resolves and scopes correctly."""

import pytest
from django.test import RequestFactory
from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.backends.db import SessionStore

from apps.tenants.managers import clear_active_organization, get_active_organization
from apps.tenants.middleware import (
    SESSION_KEY,
    ActiveOrganizationMiddleware,
)


@pytest.fixture(autouse=True)
def _reset_active_org():
    clear_active_organization()
    yield
    clear_active_organization()


def _build_request(user=None):
    rf = RequestFactory()
    request = rf.get("/admin/")
    request.user = user or AnonymousUser()
    request.session = SessionStore()
    return request


def _run_middleware(request):
    mw = ActiveOrganizationMiddleware(get_response=lambda r: None)
    mw.process_request(request)
    return mw


def test_anonymous_request_has_no_org():
    request = _build_request()
    _run_middleware(request)
    assert request.organization is None
    assert get_active_organization() is None


def test_user_with_membership_gets_default_org(user_a, org_a):
    request = _build_request(user_a)
    _run_middleware(request)
    assert request.organization == org_a
    assert request.session[SESSION_KEY] == org_a.pk


def test_user_without_membership_has_no_org(db, org_a):
    from django.contrib.auth import get_user_model

    user = get_user_model().objects.create_user("nomember", "n@x.test", "pw")
    request = _build_request(user)
    _run_middleware(request)
    assert request.organization is None


def test_user_cannot_switch_to_org_they_dont_belong_to(user_a, org_b):
    """Passing ?org=<other_org> for an org without membership must be rejected."""
    rf = RequestFactory()
    request = rf.get(f"/admin/?org={org_b.pk}")
    request.user = user_a
    request.session = SessionStore()
    _run_middleware(request)
    # Should fall back to user_a's actual membership, not org_b
    assert request.organization != org_b


def test_superuser_can_switch_to_any_active_org(db, org_a, org_b):
    from django.contrib.auth import get_user_model

    su = get_user_model().objects.create_superuser("root", "r@x.test", "pw")
    rf = RequestFactory()
    request = rf.get(f"/admin/?org={org_b.pk}")
    request.user = su
    request.session = SessionStore()
    _run_middleware(request)
    assert request.organization == org_b
