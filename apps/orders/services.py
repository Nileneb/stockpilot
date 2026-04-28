"""Order lifecycle services."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from django.core.mail import send_mail
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone

from apps.catalog.models import Product
from apps.forecast.models import ForecastSnapshot
from apps.inventory.models import Stock, StockMovement
from apps.tenants.models import Organization

from .models import PurchaseOrder, PurchaseOrderItem


@dataclass
class DraftReport:
    created: list[PurchaseOrder]
    skipped_no_supplier: list[Product]


def _suggested_quantity(product: Product) -> Decimal:
    """Use latest ForecastSnapshot.suggested_reorder_quantity if available,
    else product.reorder_quantity."""
    snap = (
        ForecastSnapshot.all_objects.filter(product=product)
        .order_by("-created_at")
        .first()
    )
    if snap is not None and snap.suggested_reorder_quantity > 0:
        return snap.suggested_reorder_quantity
    return Decimal(product.reorder_quantity)


def _current_stock(product: Product) -> Decimal:
    try:
        return Stock.all_objects.get(
            organization=product.organization, product=product
        ).quantity_on_hand
    except Stock.DoesNotExist:
        return Decimal("0")


@transaction.atomic
def generate_draft_orders(
    organization: Organization,
    *,
    created_by=None,
) -> DraftReport:
    """Group products needing reorder by supplier, create one draft PO per supplier.

    Skips products without `default_supplier` (returned in the report).
    Skips suppliers that already have an open draft for the same set of products
    (no duplicate work — caller can edit the existing draft instead).
    """
    needing = [
        p
        for p in Product.all_objects.filter(
            organization=organization, is_active=True
        ).select_related("default_supplier")
        if _current_stock(p) <= Decimal(p.reorder_point)
    ]

    by_supplier: dict = defaultdict(list)
    skipped: list[Product] = []
    for product in needing:
        if product.default_supplier_id is None:
            skipped.append(product)
            continue
        by_supplier[product.default_supplier].append(product)

    created: list[PurchaseOrder] = []
    for supplier, products in by_supplier.items():
        existing_draft = PurchaseOrder.all_objects.filter(
            organization=organization,
            supplier=supplier,
            status=PurchaseOrder.Status.DRAFT,
        ).first()
        if existing_draft is not None:
            continue

        po = PurchaseOrder.objects.create(
            organization=organization,
            supplier=supplier,
            created_by=created_by,
        )
        items = [
            PurchaseOrderItem(
                organization=organization,
                order=po,
                product=p,
                quantity=_suggested_quantity(p),
            )
            for p in products
        ]
        PurchaseOrderItem.objects.bulk_create(items)
        created.append(po)

    return DraftReport(created=created, skipped_no_supplier=skipped)


def submit_order(order: PurchaseOrder) -> int:
    """Send the order to the supplier via email and mark it submitted.

    Returns the number of emails actually sent (0 or 1). Raises ValueError
    if the order is not in draft status.
    """
    if order.status != PurchaseOrder.Status.DRAFT:
        raise ValueError(
            f"Cannot submit order in status={order.status}; must be draft"
        )

    # Set submitted_at first so the template can render the date
    order.submitted_at = timezone.now()
    order.save(update_fields=["submitted_at"])

    body = render_to_string(
        "orders/email_purchase_order.txt",
        {"order": order},
    )
    # Convention: first line is "Subject: ...", rest is body
    lines = body.splitlines()
    subject = lines[0].removeprefix("Subject:").strip()
    message = "\n".join(lines[1:]).lstrip()

    recipient = order.supplier.contact_email
    sent = 0
    if recipient:
        sent = send_mail(
            subject=subject,
            message=message,
            from_email=None,  # uses DEFAULT_FROM_EMAIL
            recipient_list=[recipient],
            fail_silently=False,
        )

    order.status = PurchaseOrder.Status.SUBMITTED
    order.save(update_fields=["status"])
    return sent


@transaction.atomic
def mark_received(
    order: PurchaseOrder,
    *,
    quantity_overrides: dict | None = None,
    performed_by=None,
) -> list[StockMovement]:
    """Book all line items into stock and mark the order received.

    `quantity_overrides`: {item_id: Decimal} — for partial deliveries; missing
    items default to the full ordered quantity.
    """
    if order.status not in (
        PurchaseOrder.Status.SUBMITTED,
        PurchaseOrder.Status.CONFIRMED,
    ):
        raise ValueError(
            f"Cannot receive order in status={order.status}; "
            "must be submitted or confirmed"
        )

    overrides = quantity_overrides or {}
    movements: list[StockMovement] = []
    for item in order.items.select_related("product").all():
        qty = Decimal(overrides.get(item.id, item.quantity))
        if qty <= 0:
            continue
        movement = Stock.adjust(
            product=item.product,
            delta=qty,
            kind=StockMovement.Kind.ORDER_RECEIVED,
            performed_by=performed_by,
            note=f"From PO {order.reference}",
        )
        item.received_quantity = qty
        item.save(update_fields=["received_quantity"])
        movements.append(movement)

    order.status = PurchaseOrder.Status.RECEIVED
    order.received_at = timezone.now()
    order.save(update_fields=["status", "received_at"])

    return movements
