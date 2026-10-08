# Phase 2 — Cash engine, scenarios and uncertainty

Status: specification, to be implemented in four steps (2.0, 2A, 2B, 2C).
Owner: Daniele. Implementation: Claude Code. Date: 2026-10-01.
Decisions taken: Monte Carlo uncertainty (A), seasonal run-rate for future sales (B),
on-time / expected / stress scenarios (C), CFO overrides supported in the engine now (D).

## 0. Principles

- The engine is **deterministic Python**. No LLM anywhere in this phase.
- The engine connects as **`hm_analyst`** and reads only `hm.*`. It must never read `eval.*`.
  Only the backtest script (2C) connects as `hm_evaluator`.
- **No look-ahead**: the engine uses only data dated on or before the as-of date
  (invoices issued, receipts, payments, balances ≤ as-of).
- Every number shown later in the demo must be traceable to a component of this engine.
- The payment-behaviour estimate is behind an interface (`PaymentBehaviourModel`), because
  Phase 3 will replace the simple version used here.

## 1. Time grid

- As-of date: Monday 2026-09-28 (from `hm.datasets.as_of_date`).
- 13 weeks, Monday to Sunday. Week k (1..13) = [as_of + 7(k−1), as_of + 7k − 1].
- Opening balance of week 1 = bank closing balance on as_of − 1.
- Week k closing balance = opening + receipts_k − payments_k. Week k+1 opening = week k closing.

## 2. Components

### Receipts

**R1 — Open receivables** (invoices issued ≤ as-of, not fully paid).
- Amount = outstanding gross amount (after partial payments).
- Not-yet-overdue invoices: expected receipt date = due_date + expected_delay(customer).
- Already-overdue invoices (d days late): expected receipt date =
  as_of + conditional_remaining_delay(customer, d), where
  conditional_remaining_delay = mean of (past_delay − d) for the customer's paid invoices
  in the last 12 months whose total delay exceeded d; falls back to the segment pool when
  fewer than 5 such customer observations exist; minimum 1 day. Documented as an assumption.
- Receipts falling after week 13 are reported as "beyond horizon", not dropped silently.

**R2 — Future sales not yet invoiced** (decision B).
- Per segment, forecast weekly invoicing (net) for each horizon week:
  `annual_avg_weekly_invoicing(segment) × seasonal_factor(segment, week)`
  where `seasonal_factor` = 4-week centred average of invoicing in the same calendar weeks of
  last year ÷ annual average weekly invoicing, capped to [0.6, 1.4].
- Gross amount = net × 1.17 (VAT).
- Each forecast invoice gets the segment's payment terms and the segment's expected delay;
  only receipts falling inside the horizon count.

### Payments

**P1 — Open payables** (supplier invoices received ≤ as-of, unpaid): paid on the due date
(company policy, parameter `pay_suppliers_on_due_date = true`).

**P2 — Future purchases not yet invoiced**: forecast net sales × (1 − gross margin), invoiced in
the same week, with the supplier term mix (35% at 60 days, 35% at 45, 30% at 30); gross × 1.17.

**P3 — Known commitments**. Large planned purchases (e.g. the winter stock in S2, €1.11m including VAT, the
€1.1m bill in S4) must be visible to the engine at the as-of date, because the CFO knows about
them. **Check first** whether they exist in `hm.ap_invoices` at as-of. If not, add a table
`hm.planned_payments` (dataset_id, payment_id, counterparty_code, due_date, amount_gross,
category, note), populate it from the generator, and include it in the engine.

**P4 — Recurring outflows** from `hm.recurring_outflows`: net payroll (last working day),
payroll social and withholding (15th of next month), rent (1st), other opex (5th),
corporate tax advances (10 Dec).

**P5 — VAT**: monthly net VAT paid on the 15th of the following month =
output VAT on invoices issued in the month − input VAT on purchases of the month.
September uses actual invoices; October and November use actual + forecast invoices.

## 3. Payment behaviour (simple version for Phase 2)

`PaymentBehaviourModel` interface:

- `expected_delay(customer) -> float` (days after due date)
- `delay_sample(customer) -> list[float]` (empirical delays, used by Monte Carlo)
- `source(customer) -> "customer" | "segment"` (for transparency)

Phase 2 implementation (`SimpleBehaviour`):

- Delays of the customer's invoices paid in the last 12 months (receipt date − due date).
- If fewer than 5 paid invoices: use the segment's pooled delays (source = "segment").
- Expected delay = mean of the sample.

## 4. Scenarios and uncertainty

### Scenario lines (decision C)

| Scenario | Rule | Purpose |
|---|---|---|
| `on_time` | Not-yet-due invoices paid on the due date (delay 0); already-overdue invoices use the same conditional remaining delay as `expected`. The gap between `on_time` and `expected` measures only **future** payment delays. | "If everybody paid on time from now" |
| `expected` | Each customer pays with its expected delay | The realistic forecast |
| `stress` | `expected` + shocks from `config/stress.yaml` | CFO stress test |

Stress shocks (list, combinable):

- `customer_delay`: code, extra_days
- `segment_delay`: segment, extra_days
- `customer_default`: code (open and future receivables of that customer are never paid)

Default stress for every dataset: largest customer +30 days. Stress definitions are inputs,
not hard-coded.

### Uncertainty band (decision A)

- Monte Carlo, N = 1,000 runs, seeded (reproducible).
- In each run: every open and future invoice draws its delay from `delay_sample(customer)`
  (bootstrap); weekly future invoicing is multiplied by a log-normal noise whose sigma is
  estimated from the history residuals of weekly invoicing around the seasonal forecast.
- Output per week: P10, P50, P90 of the closing balance, and
  `p_below_threshold` = share of runs below the safety threshold.
- The band is shown around the `expected` line. The band must contain the `expected` line
  in most weeks; report the weeks where it does not.

## 5. CFO overrides (decision D)

New table `hm.assumption_overrides` (migration 010):
`override_id, dataset_id, target_type (invoice | customer | planned_payment | parameter),
target_id, field (expected_date | amount | delay_days | value), new_value, reason, created_by,
created_at, active, supersedes`.

- Insert-only. To cancel or change an override, insert a new row that supersedes it.
  UPDATE and DELETE blocked by trigger (same pattern as `hm.parameters`). Audit trigger attached.
- INSERT granted to `hm_approver` (the CFO). `hm_analyst` can read.
- The engine applies all active overrides and lists them in the assumptions output.

## 6. Profit vs cash

Per month (the last 3 closed months and the months in the horizon):

| Line | Meaning |
|---|---|
| Profit (accrual) | Revenue − COGS − opex − depreciation − tax, from `month_closes` or computed |
| + Depreciation | Not a cash outflow |
| − Increase in receivables | Sold but not yet collected |
| + Increase in payables | Bought but not yet paid |
| − Inventory purchases | Stock paid but not yet sold (e.g. the S2 winter stock) |
| ± VAT and tax timing | Collected or paid in a different month |
| = Change in cash | Must equal the bank balance change |

The bridge must reconcile to the cent. Output also one plain sentence per month, generated by a
template (not an LLM), e.g. "Profit +€48k, cash −€210k: €180k not yet collected, €80k stock paid."

## 7. Assumptions output (transparency)

A list of every assumption used, each with `id`, `description`, `value`, `source`
(history / config / public data / CFO override) and `affects` (which component). Includes at
least: expected delay per customer (top 20) and per segment, seasonal factors, gross margin,
supplier term mix, safety threshold, VAT rate, stress shocks, overdue-invoice rule, active overrides.

## 8. Outputs

1. `hm.forecast_runs` (run_id, dataset_id, as_of, created_at, engine_version, params JSONB)
   and `hm.forecast_lines` (run_id, week_start, scenario, value, p10, p50, p90,
   p_below_threshold, components JSONB). Written as `hm_analyst`.
2. **Demo export**: `data/demo/<dataset_id>/forecast.json` with weeks, the three lines, the band,
   components per week, threshold, profit-vs-cash bridge, assumptions, overrides.
   Document the format in `docs/demo_data_format.md` (the future web page will read it).
3. **Small illustrative dataset** for S2 (`data/illustrative/S2/`), readable in one minute:
   opening balance; the 10 largest customers (code, segment, open receivables, typical delay);
   their open invoices due in the horizon (max ~25 rows); planned payments above €50k plus
   payroll, VAT, tax and rent; and a `README.md` with the same content as one-page tables.
4. **Review chart** `docs/img/S2_forecast.png` (matplotlib): on_time, expected with P10–P90 band,
   stress, threshold line. Also one per dataset in `docs/img/` for review.

## Steps

### 2.0 — Housekeeping
- Align `docs/PHASE1_SPEC.md` with what was built: section 1B (LUSTAT single source, no press
  figures, no manual fallback), section 2 (~6,000 invoices/year), S3 and S4 already updated.
- Commit `docs/PROGRESS_PHASE_0_1.md` if not yet committed.

### 2A — Deterministic engine
- Package `engine/`: time grid, components R1, R2, P1–P5, `SimpleBehaviour`, overrides,
  `expected` and `on_time` scenarios. Entry point `python -m engine.run --dataset S2` and `--all`.
- Migration 010: `hm.assumption_overrides` (+ `hm.planned_payments` if needed).
- **Hand-built test**: a tiny dataset `TEST_HAND` (opening €100,000; 3 customer invoices with
  known due dates and delays; 2 supplier invoices; one payroll; one VAT payment) with the
  expected weekly balances written by hand in the test, matched to the cent.
- Tests: weekly conservation (opening + receipts − payments = closing); no read access to
  `eval`; override moves an amount between weeks exactly and is audited; superseding an
  override restores the previous value; seasonal factors within caps.
- **Stop and report**: weekly table for S1 and S2 (expected vs on_time), plus whether the large
  commitments of S2/S4 are visible at as-of.

### 2B — Stress, uncertainty, profit vs cash, assumptions
- `stress` scenario with `config/stress.yaml`; Monte Carlo band; `p_below_threshold`.
- Profit-vs-cash bridge with reconciliation; template sentences.
- Assumptions list.
- Tests: Monte Carlo reproducible with seed; P10 ≤ P50 ≤ P90; bridge reconciles to the cent for
  every month and dataset; stress with `customer_default` removes exactly that customer's receipts.
- **Stop and report**: S2 chart, S2 profit-vs-cash table, first 15 assumptions.

### 2C — Outputs and first accuracy check
- Write `hm.forecast_runs/lines`, `data/demo/<id>/forecast.json`, `docs/demo_data_format.md`,
  the S2 illustrative dataset and the review charts.
- `tracker/backtest.py` (connects as `hm_evaluator`): for every dataset compare the `expected`
  line with the actual weekly balances in `eval`: error at weeks 1, 4 and 13 (€ and % of actual);
  band coverage (share of weeks where the actual falls inside P10–P90, target ~80%); first week
  below threshold forecast vs actual. Write `data/demo/accuracy_summary.csv`.
- **Do not tune the engine to pass S2.** Phase 2 uses a simple average delay and may react late
  to the drifting customer in S2: that is expected, and Phase 3 should improve it. Just report it.
- **Stop and report**: `accuracy_summary.csv` and all review charts.

## Definition of done

- [ ] 2.0 docs aligned
- [ ] 2A engine + hand-built test to the cent + tests green
- [ ] 2B stress, Monte Carlo, profit vs cash, assumptions + tests green
- [ ] 2C outputs, illustrative dataset, charts, accuracy summary
- [ ] Commit + push after each step
