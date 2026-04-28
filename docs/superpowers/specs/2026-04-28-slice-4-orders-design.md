# Slice 4 — Bestellautomatik

**Date:** 2026-04-28

## Goal

Aus Reorder-Vorschlägen werden Lieferanten-spezifische Purchase Orders generiert, per Mail verschickt, und beim Wareneingang über `Stock.adjust(kind=ORDER_RECEIVED)` zurückgebucht.

## Datenmodell

```
PurchaseOrder (org-scoped)
  - supplier (FK)
  - status: draft | submitted | confirmed | received | cancelled
  - reference (str, unique-per-org — z.B. "PO-AB12CD34")
  - notes
  - created_by (FK User, nullable)
  - submitted_at, received_at (datetime, nullable)

PurchaseOrderItem (org-scoped)
  - order (FK PurchaseOrder, related_name="items")
  - product (FK Product)
  - quantity (decimal)
  - received_quantity (decimal, default 0) -- partial receive support
  - notes (str, optional)
```

## Workflow

```
generate_draft_orders(org)
  → Produkte mit stock ≤ reorder_point gruppiert nach default_supplier
  → ein PO mit Status=draft pro Supplier
  → Item.quantity = neueste ForecastSnapshot.suggested_reorder_quantity,
    oder fallback auf Product.reorder_quantity
  → Produkte ohne default_supplier werden übersprungen (im Report gemeldet)

submit_order(po)
  → Status muss draft sein
  → rendert Mail-Template, schickt an supplier.contact_email
  → status = submitted, submitted_at = now()

mark_received(po, qty_overrides={item_id: qty})
  → Status muss submitted oder confirmed sein
  → für jedes Item: Stock.adjust(
        delta=qty_overrides.get(item.id, item.quantity),
        kind=ORDER_RECEIVED)
  → received_quantity wird je Item aktualisiert
  → status = received, received_at = now()
```

## E-Mail

Console-Backend in Dev (`EMAIL_BACKEND = django.core.mail.backends.console.EmailBackend`).
Template: `apps/orders/templates/orders/email_purchase_order.txt`.

## Admin

- `PurchaseOrderAdmin` mit Inline für Items, Actions:
  - "Generate draft orders for org" (auf der ListView)
  - "Submit selected" — schickt Mail
  - "Mark as received" — bucht Stock zu
- `PurchaseOrderItemAdmin` separat (mit autocomplete für Product)

## Tests

- generate_draft_orders gruppiert nach Supplier korrekt
- Items nutzen Forecast-Suggestion wenn vorhanden, sonst reorder_quantity
- Produkte ohne Supplier werden übersprungen
- submit_order ändert Status, schickt Mail (django.core.mail.outbox check)
- submit_order mit falschem Status raises
- mark_received bucht ORDER_RECEIVED-Movements und aktualisiert Stock
- mark_received mit qty_override
- Cross-Tenant: PO Org A nicht in default-Manager von Org B sichtbar
- Reference unique-per-org

## Out of scope

- EDI / Lieferanten-API-Integration (Mail reicht für MVP)
- Approval-Workflow mit mehreren Genehmigern (status confirmed gibt es, wird aber manuell gesetzt)
- Teil-Lieferungen über mehrere mark_received-Aufrufe (received_quantity ist da, Logik in Slice 4.5)
- PDF-Anhang (später)
