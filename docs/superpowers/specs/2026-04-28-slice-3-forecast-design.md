# Slice 3 — Verbrauchs-Forecasting

**Date:** 2026-04-28

## Goal

Aus StockMovement-Historie (kind=CONSUMPTION) eine tägliche Verbrauchsrate pro Produkt schätzen, daraus "Tage bis Stockout" und eine Bestellempfehlung ableiten.

## Methode

Für jedes Produkt:
1. StockMovement der letzten N Tage holen, kind=CONSUMPTION (negative deltas).
2. In Tages-Buckets aggregieren → Zeitreihe `[d_t, d_{t-1}, ..., d_0]` von Einheiten/Tag.
3. **Simple Exponential Smoothing** (α default 0.3) → glatter laufender Mittelwert als aktuelle Tagesrate.
4. Aus Tagesrate + aktuellem Stock + Lieferzeit (Supplier.lead_time_days) ableiten:
   - `days_until_stockout = stock / rate` (∞ wenn rate=0)
   - `suggested_reorder_quantity = max(product.reorder_quantity, ceil(rate * (lead_time + safety_days)))`

ES gewählt, weil: einfach, ohne externe Deps, robust gegen sparse Daten, exponentielle Gewichtung gibt jüngeren Werten mehr Gewicht (was bei wechselndem Verbrauch wichtig ist).

## Datenmodell

```
ForecastSnapshot (org-scoped)
  - product (FK)
  - lookback_days (int)
  - method (str)              -- "exp_smoothing"
  - alpha (decimal)
  - daily_consumption_rate (decimal, ≥0)
  - days_until_stockout (decimal, null = no consumption history)
  - suggested_reorder_quantity (decimal)
  - current_stock (decimal)   -- snapshot at compute time
  - created_at
```

## Service

```
compute_forecast(product, lookback_days=30, alpha=Decimal("0.3"), safety_days=2)
    → ForecastSnapshot
compute_all_forecasts(organization, **kwargs)
    → list[ForecastSnapshot]
products_needing_reorder(organization)
    → QuerySet[Product]   -- where stock ≤ reorder_point
```

## Admin

- `ForecastSnapshotAdmin`: list view sortiert nach `days_until_stockout` ASC, gefiltert auf neueste Snapshot pro Produkt.
- Action auf `ProductAdmin`: "Compute forecast" → ruft `compute_forecast` für selektierte Produkte.

## Tests

- ES math (small synthetic series, edge cases: empty, single value)
- compute_forecast: persistiert korrekte Werte für seeded movements
- compute_forecast mit 0 Verbrauch → days_until_stockout = None, rate = 0
- compute_forecast mit Stock=0 und positiver Rate → days_until_stockout = 0
- Cross-Tenant: Forecasts of Org A nicht sichtbar in Org B's Manager-Default

## Out of scope

- Saisonalität / Holt-Winters (für später wenn echte Daten vorliegen)
- Konfidenzintervalle
- Background-Job (Slice 6+)
