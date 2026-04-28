"""Order generation, submission, receipt — within a tenant schema."""

from decimal import Decimal

from django.core import mail
from django_tenants.test.cases import TenantTestCase

from apps.catalog.models import Product, Supplier
from apps.inventory.models import Stock, StockMovement
from apps.orders.models import PurchaseOrder
from apps.orders.services import (
    generate_draft_orders,
    mark_received,
    submit_order,
)


class OrderLifecycleTests(TenantTestCase):
    @classmethod
    def setup_tenant(cls, tenant):
        tenant.name = "Acme"
        return tenant

    @classmethod
    def setup_domain(cls, domain):
        domain.domain = "acme.test.local"
        return domain

    def setUp(self):
        self.supplier = Supplier.objects.create(
            name="Acme Supplies",
            contact_email="orders@acme.test",
            lead_time_days=5,
        )
        self.product = Product.objects.create(
            sku="LOW-1",
            name="Low Stock Item",
            default_supplier=self.supplier,
            reorder_point=10,
            reorder_quantity=20,
        )

    def test_generate_draft_creates_one_po_per_supplier(self):
        report = generate_draft_orders()
        self.assertEqual(len(report.created), 1)
        po = report.created[0]
        self.assertEqual(po.supplier, self.supplier)
        self.assertEqual(po.status, PurchaseOrder.Status.DRAFT)
        self.assertEqual(po.items.count(), 1)
        self.assertEqual(po.items.first().quantity, Decimal("20.000"))

    def test_submit_sends_email_and_updates_status(self):
        mail.outbox.clear()
        po = generate_draft_orders().created[0]
        sent = submit_order(po)
        po.refresh_from_db()

        self.assertEqual(sent, 1)
        self.assertEqual(po.status, PurchaseOrder.Status.SUBMITTED)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("orders@acme.test", mail.outbox[0].to)
        self.assertIn(po.reference, mail.outbox[0].subject)

    def test_mark_received_books_stock(self):
        po = generate_draft_orders().created[0]
        submit_order(po)
        po.refresh_from_db()

        starting = Stock.objects.filter(product=self.product).first()
        starting_qty = starting.quantity_on_hand if starting else Decimal("0")

        movements = mark_received(po)
        po.refresh_from_db()

        self.assertEqual(po.status, PurchaseOrder.Status.RECEIVED)
        self.assertEqual(len(movements), 1)
        self.assertEqual(
            Stock.objects.get(product=self.product).quantity_on_hand,
            starting_qty + po.items.first().quantity,
        )
        self.assertEqual(
            movements[0].kind,
            StockMovement.Kind.ORDER_RECEIVED,
        )
