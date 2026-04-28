"""Order generation, submission, receipt."""

from decimal import Decimal

import pytest
from django.core import mail

from apps.catalog.models import Product, Supplier
from apps.forecast.services import compute_forecast
from apps.inventory.models import Stock, StockMovement
from apps.orders.models import PurchaseOrder, PurchaseOrderItem
from apps.orders.services import (
    generate_draft_orders,
    mark_received,
    submit_order,
)
from apps.tenants.managers import (
    clear_active_organization,
    set_active_organization,
)


@pytest.fixture(autouse=True)
def _no_active_org():
    clear_active_organization()
    yield
    clear_active_organization()


@pytest.fixture
def supplier_with_email(org_a):
    return Supplier.all_objects.create(
        organization=org_a,
        name="Acme Supplies",
        contact_email="orders@acme.test",
        lead_time_days=5,
    )


@pytest.fixture
def low_stock_product(org_a, supplier_with_email):
    p = Product.all_objects.create(
        organization=org_a,
        sku="LOW-1",
        name="Low Stock Item",
        default_supplier=supplier_with_email,
        reorder_point=10,
        reorder_quantity=20,
    )
    return p


@pytest.fixture
def orphan_product(org_a):
    """Needs reorder but has no default_supplier."""
    return Product.all_objects.create(
        organization=org_a,
        sku="ORPH-1",
        name="Orphan",
        default_supplier=None,
        reorder_point=5,
        reorder_quantity=10,
    )


# ---- generate_draft_orders ----


def test_generate_draft_creates_one_po_per_supplier(
    org_a, low_stock_product, supplier_with_email
):
    report = generate_draft_orders(org_a)
    assert len(report.created) == 1
    po = report.created[0]
    assert po.supplier == supplier_with_email
    assert po.status == PurchaseOrder.Status.DRAFT
    assert po.organization == org_a
    assert po.items.count() == 1
    item = po.items.first()
    assert item.product == low_stock_product
    # Quantity falls back to product.reorder_quantity (no forecast yet)
    assert item.quantity == Decimal("20.000")


def test_generate_draft_uses_forecast_suggestion_when_available(
    org_a, low_stock_product
):
    # Seed enough stock + consumption so the forecast suggests > reorder_quantity
    Stock.adjust(
        product=low_stock_product,
        delta=Decimal("100"),
        kind=StockMovement.Kind.MANUAL_IN,
    )
    # consumption history that drives suggested qty above 20
    for _ in range(5):
        Stock.adjust(
            product=low_stock_product,
            delta=Decimal("-15"),
            kind=StockMovement.Kind.CONSUMPTION,
        )
    snap = compute_forecast(low_stock_product, lookback_days=14)
    assert snap.suggested_reorder_quantity > Decimal("20")

    # Now generate — needs current stock to be at or below reorder_point=10
    Stock.adjust(
        product=low_stock_product,
        delta=Decimal("-100"),  # drives below
        kind=StockMovement.Kind.CONSUMPTION,
    )
    report = generate_draft_orders(org_a)
    po = report.created[0]
    item = po.items.first()
    assert item.quantity == snap.suggested_reorder_quantity


def test_generate_draft_skips_products_without_supplier(
    org_a, low_stock_product, orphan_product
):
    report = generate_draft_orders(org_a)
    assert orphan_product in report.skipped_no_supplier
    # Only one PO created (for the supplier-having product)
    assert len(report.created) == 1
    assert all(item.product != orphan_product for item in report.created[0].items.all())


def test_generate_draft_does_not_duplicate_existing_draft(
    org_a, low_stock_product, supplier_with_email
):
    generate_draft_orders(org_a)
    # second call — existing draft should be honored, no new PO
    report = generate_draft_orders(org_a)
    assert report.created == []
    assert (
        PurchaseOrder.all_objects.filter(
            organization=org_a, supplier=supplier_with_email
        ).count()
        == 1
    )


# ---- submit_order ----


def test_submit_order_sends_email_and_updates_status(
    org_a, low_stock_product, supplier_with_email
):
    mail.outbox.clear()
    report = generate_draft_orders(org_a)
    po = report.created[0]

    sent = submit_order(po)
    po.refresh_from_db()

    assert sent == 1
    assert po.status == PurchaseOrder.Status.SUBMITTED
    assert po.submitted_at is not None
    assert len(mail.outbox) == 1
    msg = mail.outbox[0]
    assert "orders@acme.test" in msg.to
    assert po.reference in msg.subject
    assert low_stock_product.sku in msg.body


def test_submit_order_rejects_non_draft(org_a, low_stock_product):
    report = generate_draft_orders(org_a)
    po = report.created[0]
    submit_order(po)
    po.refresh_from_db()
    with pytest.raises(ValueError):
        submit_order(po)


def test_submit_order_with_no_supplier_email_does_not_send(org_a):
    """Supplier without contact_email — order is still submitted but no mail."""
    sup = Supplier.all_objects.create(
        organization=org_a,
        name="No-Email Supplier",
        contact_email="",
        lead_time_days=3,
    )
    p = Product.all_objects.create(
        organization=org_a,
        sku="NE-1",
        name="No Email Product",
        default_supplier=sup,
        reorder_point=5,
        reorder_quantity=10,
    )
    report = generate_draft_orders(org_a)
    po = next(p for p in report.created if p.supplier == sup)
    mail.outbox.clear()
    sent = submit_order(po)
    assert sent == 0
    po.refresh_from_db()
    assert po.status == PurchaseOrder.Status.SUBMITTED
    assert len(mail.outbox) == 0


# ---- mark_received ----


def test_mark_received_books_stock_and_logs_movements(
    org_a, low_stock_product
):
    report = generate_draft_orders(org_a)
    po = report.created[0]
    submit_order(po)
    po.refresh_from_db()
    starting_stock = Stock.all_objects.filter(
        product=low_stock_product
    ).first()
    starting_qty = (
        starting_stock.quantity_on_hand if starting_stock else Decimal("0")
    )

    movements = mark_received(po)
    po.refresh_from_db()

    assert po.status == PurchaseOrder.Status.RECEIVED
    assert po.received_at is not None
    assert len(movements) == 1
    item = po.items.first()
    assert item.received_quantity == item.quantity

    stock = Stock.all_objects.get(product=low_stock_product)
    assert stock.quantity_on_hand == starting_qty + item.quantity
    last_movement = StockMovement.all_objects.filter(
        product=low_stock_product
    ).order_by("-created_at").first()
    assert last_movement.kind == StockMovement.Kind.ORDER_RECEIVED
    assert po.reference in last_movement.note


def test_mark_received_with_quantity_override(org_a, low_stock_product):
    report = generate_draft_orders(org_a)
    po = report.created[0]
    submit_order(po)
    po.refresh_from_db()
    item = po.items.first()

    mark_received(po, quantity_overrides={item.id: Decimal("5")})
    item.refresh_from_db()
    assert item.received_quantity == Decimal("5.000")


def test_mark_received_rejects_draft(org_a, low_stock_product):
    report = generate_draft_orders(org_a)
    po = report.created[0]
    with pytest.raises(ValueError):
        mark_received(po)


def test_orders_are_org_scoped(org_a, org_b, low_stock_product):
    generate_draft_orders(org_a)
    set_active_organization(org_a)
    assert PurchaseOrder.objects.count() == 1
    set_active_organization(org_b)
    assert PurchaseOrder.objects.count() == 0
