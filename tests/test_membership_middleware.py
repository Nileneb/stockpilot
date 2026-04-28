"""MembershipAccessMiddleware enforces per-tenant access control."""

from django.contrib.auth import get_user_model
from django.test import RequestFactory
from django_tenants.test.cases import TenantTestCase

from apps.tenants.middleware import MembershipAccessMiddleware
from apps.tenants.models import Membership

User = get_user_model()


class MembershipAccessTests(TenantTestCase):
    @classmethod
    def setup_tenant(cls, tenant):
        tenant.name = "Acme"
        return tenant

    @classmethod
    def setup_domain(cls, domain):
        domain.domain = "acme.test.local"
        return domain

    def setUp(self):
        self.mw = MembershipAccessMiddleware(get_response=lambda r: None)
        self.rf = RequestFactory()

    def _make_request(self, user, tenant=None):
        request = self.rf.get("/")
        request.user = user
        request.tenant = tenant or self.tenant
        return request

    def test_anonymous_pass_through(self):
        from django.contrib.auth.models import AnonymousUser

        request = self._make_request(AnonymousUser())
        self.assertIsNone(self.mw.process_request(request))

    def test_member_allowed(self):
        user = User.objects.create_user("alice", "a@x.test", "pw")
        Membership.objects.create(user=user, organization=self.tenant)
        request = self._make_request(user)
        self.assertIsNone(self.mw.process_request(request))

    def test_non_member_forbidden(self):
        user = User.objects.create_user("bob", "b@x.test", "pw")
        request = self._make_request(user)
        response = self.mw.process_request(request)
        self.assertEqual(response.status_code, 403)

    def test_superuser_allowed_without_membership(self):
        su = User.objects.create_superuser("root", "r@x.test", "pw")
        request = self._make_request(su)
        self.assertIsNone(self.mw.process_request(request))
