"""Schema-level isolation between tenants.

Two distinct tenants must have completely separate Product, Stock, etc.
data. We use TenantTestCase (one schema per class) plus a manual
schema_context for the second tenant.
"""

from decimal import Decimal

from django.test import TestCase
from django_tenants.test.cases import TenantTestCase
from django_tenants.utils import get_tenant_domain_model, get_tenant_model, schema_context


class TenantIsolationTests(TenantTestCase):
    """TenantTestCase auto-creates `self.tenant` and switches the connection
    to that tenant's schema for the duration of the test class."""

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.name = "Acme"
        return tenant

    @classmethod
    def setup_domain(cls, domain):
        domain.domain = "acme.test.local"
        return domain

    def test_product_created_in_one_tenant_invisible_in_another(self):
        from apps.catalog.models import Product, Supplier

        # Create in current tenant (acme)
        sup = Supplier.objects.create(name="Acme Supplier", lead_time_days=5)
        Product.objects.create(sku="A-1", name="Widget", default_supplier=sup)
        self.assertEqual(Product.objects.count(), 1)

        # Create a second tenant + domain in the public schema
        Tenant = get_tenant_model()
        Domain = get_tenant_domain_model()
        with schema_context("public"):
            other = Tenant(schema_name="other", name="Other Co")
            other.save()
            Domain.objects.create(
                domain="other.test.local", tenant=other, is_primary=True
            )

        # Inside the other tenant's schema → Product table is empty
        with schema_context("other"):
            self.assertEqual(Product.objects.count(), 0)

        # Back in acme: still our 1 product
        self.assertEqual(Product.objects.count(), 1)

    def test_stock_adjust_audits_movement_within_tenant(self):
        from apps.catalog.models import Product
        from apps.inventory.models import Stock, StockMovement

        product = Product.objects.create(sku="X", name="X Item", reorder_quantity=10)
        Stock.adjust(
            product=product,
            delta=Decimal("12"),
            kind=StockMovement.Kind.MANUAL_IN,
        )
        self.assertEqual(
            Stock.objects.get(product=product).quantity_on_hand,
            Decimal("12.000"),
        )
        self.assertEqual(
            StockMovement.objects.filter(product=product).count(),
            1,
        )
