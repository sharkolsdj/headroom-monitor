# Demo Data Format — `data/demo/<dataset_id>/forecast.json`

Each dataset produced by Phase 2C has a `forecast.json` file under `data/demo/<dataset_id>/`.
The web front-end and the backtest script both read this format.

---

## Top-level fields

| Field | Type | Description |
|-------|------|-------------|
| `dataset_id` | string | Synthetic dataset identifier, e.g. `S2_big_customer` |
| `as_of` | ISO date | Engine as-of date (always `2026-09-28` for the demo) |
| `engine_version` | string | Engine release, e.g. `2C.0` |
| `generated_at` | ISO datetime (UTC) | When the file was produced |
| `threshold` | number | Safety threshold (€) — 4 × weekly fixed costs |
| `opening_balance` | number | Cash balance at start of week 1 (€) |
| `scenarios` | object | Three scenario results — see below |
| `mc_band` | object \| null | Monte Carlo P10/P50/P90 per week — see below |
| `bridge` | array \| null | Profit-vs-cash bridge (S2 only in demo) |
| `assumptions` | array \| null | Assumptions list (S2 only in demo) |
| `applied_overrides` | array | CFO overrides active at as-of |

---

## `scenarios.<name>`

Each of `expected`, `on_time`, `stress` has:

| Field | Type | Description |
|-------|------|-------------|
| `weeks` | array[Week] | 13 weekly rows |
| `beyond_horizon_count` | integer | Open AR items falling after week 13 |
| `applied_overrides_count` | integer | Number of active CFO overrides |

### Week object

| Field | Type | Description |
|-------|------|-------------|
| `week` | integer | 1–13 |
| `week_start` | ISO date | Monday |
| `week_end` | ISO date | Sunday |
| `opening` | number | Opening cash balance (€) |
| `receipts` | number | Total receipts in the week (€) |
| `payments` | number | Total payments in the week (€) |
| `closing` | number | Closing cash balance (€) |
| `receipts_by_source` | object | Receipts broken down by component (`R1`, `R2`) |
| `payments_by_source` | object | Payments broken down by component (`P1`, `P2`, `P4`, `P5`) |

Component codes:

| Code | Meaning |
|------|---------|
| R1 | Receipts from open receivables at as-of |
| R2 | Receipts from future sales not yet invoiced |
| P1 | Payments on open payables at as-of |
| P2 | Payments on future purchases not yet invoiced |
| P4 | Recurring outflows (payroll, rent, opex, tax) |
| P5 | VAT net settlement |

---

## `mc_band`

Keys are week numbers (as strings, `"1"`–`"13"`):

| Field | Type | Description |
|-------|------|-------------|
| `p10` | number | 10th-percentile closing balance over 1,000 MC runs (€) |
| `p50` | number | Median closing balance (€) — used as the displayed expected line |
| `p90` | number | 90th-percentile closing balance (€) |
| `p_below_threshold` | number | Share of runs where closing < threshold (0–1) |

---

## `bridge` (profit-vs-cash, monthly)

Array of bridge rows covering the last 3 closed months and the forecast months:

| Field | Type | Description |
|-------|------|-------------|
| `month` | ISO date | First day of the month |
| `type` | `"historical"` \| `"forecast"` | |
| `profit` | number | Accrual profit after tax (€) |
| `depreciation` | number | Depreciation add-back (€) |
| `delta_ar` | number | Change in outstanding AR — positive = more invoiced than collected (€) |
| `delta_ap` | number | Change in outstanding AP — positive = more purchased than paid (€) |
| `vat_paid` | number | VAT net settlement paid to tax authority (€, positive = outflow) |
| `tax_paid` | number | Corporate tax advance paid (€, positive = outflow) |
| `inventory_other` | number | Residual timing items (€) |
| `cash_change` | number | Actual or forecast change in bank balance (€) |
| `reconciliation_error` | number | Should be 0.00 for historical; always 0.00 for forecast |
| `sentence` | string | Plain-English one-sentence summary for CFO review |

Reconciliation identity: `cash_change = profit + depreciation − delta_ar + delta_ap − vat_paid − tax_paid − inventory_other`

---

## `assumptions`

Array of assumption records:

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique identifier, e.g. `delay_CUST_001` |
| `description` | string | Human-readable description |
| `value` | any | The assumption value (number, string, or list) |
| `source` | string | `history`, `config`, `public_data`, or `cfo_override` |
| `affects` | string | Which component(s) this assumption affects |
