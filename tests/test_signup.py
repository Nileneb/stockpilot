"""Self-service signup tests.

Three layers:
- Pure validators (`validate_subdomain_slug`)
- Provisioning service (creates User+Org+Domain+Membership atomically)
- View (form rendering, POST happy path, rate limit)
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db.utils import IntegrityError
from django.test import Client, TestCase, override_settings

from apps.tenants.models import Domain, Membership, Organization
from apps.tenants.validators import RESERVED_SUBDOMAINS, validate_subdomain_slug


# --- Pure validator tests --------------------------------------------------

class SlugValidatorTests(TestCase):
    def test_accepts_valid_slug(self):
        for ok in ("acme", "ac-me", "a1b2c3", "supercorp", "a" + "b" * 28 + "c"):
            validate_subdomain_slug(ok)  # must not raise

    def test_rejects_too_short(self):
        for bad in ("", "a", "ab"):
            with self.assertRaises(ValidationError):
                validate_subdomain_slug(bad)

    def test_rejects_too_long(self):
        with self.assertRaises(ValidationError):
            validate_subdomain_slug("a" * 31)

    def test_rejects_uppercase(self):
        with self.assertRaises(ValidationError):
            validate_subdomain_slug("Acme")

    def test_rejects_leading_or_trailing_dash(self):
        for bad in ("-acme", "acme-", "-acme-"):
            with self.assertRaises(ValidationError):
                validate_subdomain_slug(bad)

    def test_rejects_underscore(self):
        with self.assertRaises(ValidationError):
            validate_subdomain_slug("ac_me")

    def test_rejects_reserved(self):
        for reserved in ("admin", "www", "api", "support"):
            assert reserved in RESERVED_SUBDOMAINS
            with self.assertRaises(ValidationError):
                validate_subdomain_slug(reserved)

    def test_rejects_punycode_prefix(self):
        # xn-- is the IDN punycode prefix; allowing it lets a tenant register
        # a homograph-phishing subdomain.
        for bad in ("xn--abc", "xn--example", "xn--80akhbyknj4f"):
            with self.assertRaises(ValidationError):
                validate_subdomain_slug(bad)

    def test_non_string_rejected(self):
        with self.assertRaises(ValidationError):
            validate_subdomain_slug(None)  # type: ignore[arg-type]


# --- Service-level tests ---------------------------------------------------

@override_settings(SIGNUP_DOMAIN_SUFFIX="localhost")
class ProvisionOrganizationTests(TestCase):
    """Public-schema service tests. No TenantTestCase needed because the
    service writes only to public-schema models (User, Organization,
    Domain, Membership)."""

    def test_creates_user_org_domain_membership_atomically(self):
        from apps.tenants import services

        user, org = services.provision_organization(
            company_name="Acme Inc",
            slug="acme",
            email="Owner@Acme.Test",  # mixed case → must normalize to lowercase
            password="SuperSecret123!",
        )

        User = get_user_model()
        # Email normalized to lowercase in both username and email fields.
        self.assertEqual(user.username, "owner@acme.test")
        self.assertEqual(user.email, "owner@acme.test")
        self.assertEqual(User.objects.filter(email="owner@acme.test").count(), 1)
        # Three-tier invariant: signup never grants platform-admin access.
        # If this regresses, the user's hard requirement is violated.
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertEqual(Organization.objects.filter(slug="acme").count(), 1)
        self.assertEqual(
            Domain.objects.filter(domain="acme.localhost").count(), 1
        )
        self.assertEqual(
            Membership.objects.filter(
                user=user, organization=org, role=Membership.Role.OWNER
            ).count(),
            1,
        )

    def test_rolls_back_when_domain_creation_fails(self):
        """If Domain.objects.create fails (e.g. uniqueness conflict), no
        orphan User or Org rows should remain.

        KNOWN GAP: Organization.save() with auto_create_schema=True creates
        a Postgres schema in a post_save signal that is NOT covered by
        transaction rollback. The schema named after the failed slug stays
        in Postgres until manual DROP SCHEMA. Spec line ~105 documents
        this — slug uniqueness is checked in the form before reaching the
        service, so this is an edge case in practice.
        """
        from apps.tenants import services

        # Pre-claim the domain (but leave slug "taken" free so the
        # Organization create succeeds and the failure point is the
        # subsequent Domain create).
        existing = Organization.objects.create(name="Squatter", slug="squat")
        Domain.objects.create(
            domain="taken.localhost", tenant=existing, is_primary=True
        )

        User = get_user_model()
        before_users = User.objects.count()
        before_orgs = Organization.objects.count()

        with self.assertRaises(IntegrityError):
            services.provision_organization(
                company_name="Conflicting",
                slug="taken",  # will collide on Domain.objects.create
                email="x@y.test",
                password="SuperSecret123!",
            )

        # No orphan User or Organization rows beyond the pre-existing ones.
        self.assertEqual(User.objects.count(), before_users)
        self.assertEqual(Organization.objects.count(), before_orgs)


# --- View / form tests -----------------------------------------------------

@override_settings(SIGNUP_DOMAIN_SUFFIX="localhost")
class SignupViewTests(TestCase):
    """View tests that hit the public-schema URLconf via the test client.

    django-tenants routes by Domain row, not by ROOT_URLCONF override —
    so we register `testserver` as a Domain pointing at the public org.
    """

    @classmethod
    def setUpTestData(cls):
        pub, _ = Organization.objects.get_or_create(
            schema_name="public", defaults={"name": "Public"}
        )
        Domain.objects.get_or_create(
            domain="testserver",
            defaults={"tenant": pub, "is_primary": True},
        )

    def setUp(self):
        cache.clear()
        self.client = Client()

    def test_landing_renders(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Organisation anlegen")

    def test_signup_form_get(self):
        resp = self.client.get("/signup/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Subdomain")

    def test_signup_post_happy_path(self):
        resp = self.client.post(
            "/signup/",
            {
                "company_name": "Acme Inc",
                "slug": "acme",
                "email": "owner@acme.test",
                "password": "SuperSecret123!",
            },
        )
        # Redirects to subdomain admin
        self.assertEqual(resp.status_code, 302)
        self.assertIn("acme.localhost", resp["Location"])
        # Verify provisioning happened
        self.assertTrue(Organization.objects.filter(slug="acme").exists())

    def test_signup_post_reserved_slug(self):
        resp = self.client.post(
            "/signup/",
            {
                "company_name": "Reserved Test",
                "slug": "admin",  # in RESERVED_SUBDOMAINS
                "email": "x@y.test",
                "password": "SuperSecret123!",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "reserved")
        self.assertFalse(Organization.objects.filter(slug="admin").exists())

    def test_signup_post_taken_slug(self):
        Organization.objects.create(name="Existing", slug="existing")
        resp = self.client.post(
            "/signup/",
            {
                "company_name": "Other Co",
                "slug": "existing",
                "email": "x@y.test",
                "password": "SuperSecret123!",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "vergeben")

    def test_signup_post_weak_password(self):
        resp = self.client.post(
            "/signup/",
            {
                "company_name": "Weak Co",
                "slug": "weak",
                "email": "x@y.test",
                "password": "password",  # too common
            },
        )
        self.assertEqual(resp.status_code, 200)
        # Form rejects via CommonPasswordValidator + the error must surface
        # to the user, not just be silently swallowed.
        self.assertIn("password", resp.context["form"].errors)
        self.assertFalse(Organization.objects.filter(slug="weak").exists())

    def test_signup_rate_limit(self):
        for i in range(3):
            resp = self.client.post(
                "/signup/",
                {
                    "company_name": f"Co {i}",
                    "slug": f"co{i}",
                    "email": f"o{i}@a.test",
                    "password": "SuperSecret123!",
                },
            )
            # First 3 may succeed (302) or fail validation (200), both count
            self.assertIn(resp.status_code, (200, 302))

        # 4th attempt from same IP must hit rate limit
        resp = self.client.post(
            "/signup/",
            {
                "company_name": "Throttled Co",
                "slug": "throttled",
                "email": "t@a.test",
                "password": "SuperSecret123!",
            },
        )
        self.assertEqual(resp.status_code, 429)
