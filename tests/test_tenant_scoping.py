"""Verify OrgScopedManager filters by active organization."""

from decimal import Decimal

import pytest

from apps.catalog.models import Product, Supplier
from apps.inventory.models import Stock, StockMovement
from apps.tenants.managers import (
    clear_active_organization,
    set_active_organization,
)


@pytest.fixture(autouse=True)
def _reset_active_org():
    clear_active_organization()
    yield
    clear_active_organization()


def test_default_manager_filters_to_active_org(product_a, product_b):
    set_active_organization(product_a.organization)
    assert list(Product.objects.all()) == [product_a]

    set_active_organization(product_b.organization)
    assert list(Product.objects.all()) == [product_b]


def test_all_objects_bypasses_scope(product_a, product_b):
    set_active_organization(product_a.organization)
    assert Product.all_objects.count() == 2


def test_no_active_org_returns_all(product_a, product_b):
    # no org set — manager should not filter (admin / management commands)
    assert Product.objects.count() == 2


def test_supplier_scoping(supplier_a, supplier_b, org_a):
    set_active_organization(org_a)
    assert list(Supplier.objects.all()) == [supplier_a]


def test_unique_sku_is_per_org(org_a, org_b, supplier_a, supplier_b):
    Product.all_objects.create(
        organization=org_a, sku="X", name="X-A", default_supplier=supplier_a
    )
    # Same SKU in a different org must succeed
    Product.all_objects.create(
        organization=org_b, sku="X", name="X-B", default_supplier=supplier_b
    )
    assert Product.all_objects.count() == 2


def test_stock_adjust_creates_movement_and_updates_quantity(product_a):
    movement = Stock.adjust(
        product=product_a,
        delta=Decimal("12"),
        kind=StockMovement.Kind.MANUAL_IN,
        note="initial fill",
    )
    stock = Stock.all_objects.get(product=product_a)
    assert stock.quantity_on_hand == Decimal("12.000")
    assert movement.quantity_delta == Decimal("12")
    assert movement.kind == StockMovement.Kind.MANUAL_IN

    Stock.adjust(
        product=product_a,
        delta=Decimal("-3"),
        kind=StockMovement.Kind.CONSUMPTION,
    )
    stock.refresh_from_db()
    assert stock.quantity_on_hand == Decimal("9.000")
    assert StockMovement.all_objects.filter(product=product_a).count() == 2


def test_stock_count_sets_last_counted_at(product_a):
    Stock.adjust(
        product=product_a,
        delta=Decimal("5"),
        kind=StockMovement.Kind.PHOTO_COUNT,
        is_count=True,
    )
    stock = Stock.all_objects.get(product=product_a)
    assert stock.last_counted_at is not None
