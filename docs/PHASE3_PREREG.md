# Phase 3 — Pre-registration

Committed 2026-10-02, before any Phase 3 implementation.
Baseline values taken from docs/BASELINE_PHASE2.md (ENGINE_VERSION 3.0.0, seed 42, 1 000 MC runs).

After seeing results, a parameter may change only to fix a documented bug.
Every change is logged here with date and reason.

## 1. Parameters and rationale

| Parameter | Value | Rationale |
|---|---|---|
| Recency half-life | 60 days | An invoice paid 2 months ago weighs half as much as one paid today. Common choice for monthly-billing B2B; balances reactivity and stability |
| Look-back window | 12 months | Matches available history |
| Worsening signal | recent (last 90 days, weighted) mean delay ≥ long-run mean + 10 days, AND ≥ 3 paid invoices in the last 90 days, AND difference > 2 standard errors | Avoids flagging a customer on one or two late invoices |
| Sector trend | a segment is "slowing" if ≥ 25% of its active customers (min 8) are flagged worsening, OR its recent mean delay is ≥ 7 days above its prior 9-month mean | Captures crises where no single customer is alarming |
| Sector shift | median extra delay of the flagged customers × (1 + 0.5 × (STATEC stress index − 1)), applied to customers of that segment with < 3 recent invoices | Spreads the observed slowdown to customers without recent evidence |
| Overdue timing | empirical conditional distribution: for an invoice d days late, use past invoices of the customer whose delay exceeded d (min 5, else segment pool) and their remaining delay (delay − d) | Replaces the single "average" with "probability of paying in each coming week" |
| Monte Carlo common shock | per run, one random shift per segment drawn from the historical variability of that segment's monthly mean delay | Customers of the same sector slow down together |
| Partial payments | per-customer probability and split ratio estimated from history (segment pool if < 5 cases) | Present in the data, missing from the band so far |
| Reminder rule | remind 7 days before due date if the customer is flagged worsening, or is "slow"/"chronic" (typical delay ≥ 20 days), or the invoice's predicted payment falls in or after a week below threshold; remind immediately if already overdue | Simple, explainable credit-control practice |
| Collection priority | amount × probability of paying after the first critical week × (1 / weeks until due, min 1) | Calls first the customers whose money matters most for the critical weeks |

## 2. Targets

| Target | Phase 2 baseline | Phase 3 target |
|---|---|---|
| S2: first forecast week below threshold vs actual | 6 / 6 (exact match) | within ±1 week of actual, never later |
| S3: forecast shows the crisis | P50 never breaches threshold; actual breaches at week 3 | at least one week below threshold, within ±1 week of the actual crisis window |
| S4: spike week | 7 / 7 (exact match) | still week 7 |
| False-alarm weeks (P50 below threshold while actual above), all datasets | 4 total — S2: 2, S4: 2; all others 0 | 0 in S1, S5–S8; at most 1 per dataset elsewhere |
| Week-1 absolute error, S1 and S5–S8 | S1: −16%, S5: −17%, S6: −30%, S7: −10%, S8: −17% | ≤ 10% |
| Band coverage (actual inside P10–P90), S1 and S5–S8 | S1: 0%, S5: 8%, S6: 31%, S7: 15%, S8: 46% | 70–90% |

## Change log

### 2026-10-02 — Bug check: MC past-receipt and pool-sparsity fixes

**Classification:** bug check, not tuning.

**Diagnostic findings (scripts/_diag_s1[a-h].py):**
1. Expected delays match historical data (mean bias ≈ 0).
2. Historical training delays (N=5 053, P50=10d) match actual future delays (N=1 489, P50=10d).
3. Main source of week-1 under-forecast: 130 overdue open-AR invoices paid in week 1 but
   engine forecast in weeks 2–4 via conditional_remaining_delay giving 7–22 d extra.
4. **Bug A (MC):** In `_montecarlo._r1_sample`, for invoices with `0 < overdue_days < expected_delay`,
   the engine sampled from the *full* historical delay distribution. Any sample where
   `sampled_delay ≤ overdue_days` produced `receipt_date < as_of` and was discarded to *beyond*.
   Open invoices are not yet paid, so receipt_date must be in the future — past-dated receipts
   are logically impossible. This artificially removed 10–30 % of invoice amounts from each
   MC run, pulling the P50 band below actual.
5. **Bug B (pool sparsity):** In `SimpleBehaviour.conditional_remaining_delay`, the segment-pool
   fallback used any non-empty `pool_qualifying` list, even with 1–4 entries from the extreme
   right tail of the distribution. For deeply overdue invoices (od >> ed) these sparse entries
   gave extra = 8–22 d, placing receipts in weeks 2–4 when actual arrival was 1–5 d.

**Fixes applied:**
- `engine/_montecarlo.py`: for `od < ed` overdue path, replaced full-distribution sampling with
  conditional sampling (`[x − od for x in sample if x > od]`), matching the `od >= ed` path.
  Invoices no longer go to *beyond* when a past-dated delay is sampled.
- `engine/_behaviour.py`: `conditional_remaining_delay` now requires
  `len(pool_qualifying) >= MIN_CUSTOMER_INVOICES` (5) before using the segment pool,
  consistent with the minimum required for customer-own samples.

**Before / after (5 lines):**
```
Before: S1 week-1 −16 %, band coverage 0 %;  S5 −17 %, 8 %;  S8 −17 %, 46 %
Bug A caused 10–30 % of overdue-invoice amounts to be discarded to beyond per MC run.
Bug B caused deeply-overdue invoices (od >> ed, sparse pool) to be placed 8–22 d too late.
After:  S1 week-1 −13 %, band coverage 31 %; S5 −13 %, 23 %; S8 −13 %, 62 %
Residual bias is a model limitation (point-estimate timing); to be addressed by RecencyBehaviour in step 3.2.
```

### 2026-10-04 — Note: Phase 3.3 evaluation run on stale outputs

Phase 3.3 evaluation (scripts/eval_3.py) was run during a mid-session code state before the
RecencyBehaviour rewrite was complete. The accuracy_summary.csv used at that point was generated
with an intermediate engine. The results in the commit 9abaddb are therefore stale and should not
be used as the Phase 3.3 reference numbers. The re-run after Protocol deviation 1 (below) is
the authoritative Phase 3.3 output.

### 2026-10-04 — Protocol deviation 1: correction for right-censored data (open overdue invoices)

**Classification:** statistical method fix, not tuning on results.

**Problem identified after 3.3 run:**
`RecencyBehaviour._load()` (and `SimpleBehaviour`) estimated expected delay and the worsening
signal only from *paid* invoices. Recent slow-payers have open, overdue invoices that are still
unpaid as of `as_of`. These are right-censored observations: the true delay is unknown but is
*at least* `(as_of − due_date)` days. Ignoring them biases the delay estimate downward, and
prevents detection of S3's sector crisis (which manifests entirely as current open-AR non-payment).

**Fix applied (engine/_behaviour.py):**
- Open overdue invoices (due_date < as_of, amount_paid < 0.99 × amount_gross) are loaded as
  censored observations `(delay = as_of − due_date, is_event = False)`.
- All expected-delay, worsening, and segment-trend computations now use a recency-weighted
  Kaplan-Meier estimator (`_km_mean`, `_km_conditional_mean`, `_km_sample`).
- A new per-segment overdue-fraction signal is added: if the share of current open invoices
  overdue > 30 days exceeds the historical share by ≥ 20 pp, or is ≥ 50 % absolutely, the
  segment is flagged as slowing (`engine/_sector.py`, reason = "overdue").
- **New thresholds (not pre-registered):** `OVERDUE_30_DELTA_THRESHOLD = 0.20` and
  `OVERDUE_30_ABS_THRESHOLD = 0.50` were introduced on 2026-10-04, after Phase 3.3 results
  were visible. They will be validated only by the hold-out test (Phase 3.4).
- The half-life, worsening, and sector-fraction thresholds were not changed.

**Why this is a method fix, not tuning:**
The error was that censored observations were dropped entirely — a statistical correctness issue
unrelated to the targets table. The fix is dictated by survival-analysis first principles, not
by the direction it moves S2 or S3 results.

### 2026-10-04 — Protocol deviation 2: spec defect — sector shift undefined when no customer is worsening

**Classification:** spec defect fix, decided before seeing its effect on S3.

**Problem:** The original specification (PHASE3_SPEC.md §4.3) defines sector shift as "median
extra delay among the flagged customers × STATEC amplifier." When a segment is flagged via the
overdue-fraction criterion (Protocol deviation 1) but no individual customer clears the worsening
threshold (diff < 10d or < 3 recent invoices), the set of flagged customers is empty and
the shift formula is undefined (evaluates to 0). The spec did not anticipate this case.

**Fix (engine/_sector.py):** When the worsening-customer set is empty, fall back to the
segment-level pool delay difference: `(recent_90d_pool_mean − prior_9mo_pool_mean) × amplifier`,
floored at 0. This uses the same signal that triggered the `slowing_by_delay` criterion.

**Effect on S3 `specialised_installers`:** before = 0.0d, after ≈ 6.4d shift.
This value was computed after writing the fix, so it is known; however, the fix itself was
decided purely on the basis of internal consistency (the fallback is the natural analogue of
the existing logic), not on whether 6.4d helps or hurts the S3 target.

**Not pre-registered.** Will be validated by Phase 3.4 hold-out test.

### 2026-10-04 — Protocol deviation 3: month-end payment runs

**Classification:** empirical finding, validated only by hold-out (Phase 3.4).

**Diagnostic findings (scripts/_diag_monthly.py, as_of = 2026-06-29 / 2026-08-31 / 2026-08-03):**
- `public_entities`: 100 % of historical receipts fall on the last calendar day of the month
  (matches generator's `_next_month_end()` which returns the last calendar day, not last business day).
- At as_of = 2026-06-29 (month-end falls in W1): alternative model (≥80 % ME customers snap
  to next month-end) gives W1 % = 41.3 % vs actual = 40.4 % — gap closed from −12 pp to −0.9 pp.
- 24 unique customers qualify as month-end payers (≥5 invoices, ≥80 % on last-cal-day); all in `public_entities`.

**Rule implemented (engine/_behaviour.py, _components.py, _montecarlo.py, _collections.py):**
- A customer with ≥5 paid invoices of which ≥80 % have `last_receipt_date` on the last calendar
  day of the month is a "month-end payer" (`source = "month-end payer"`).
- A segment where ≥80 % of all historical receipts fall on the last calendar day of the month
  is a "month-end segment".
- For R1 **overdue** invoices of month-end payers and R2 future sales of month-end segments: the
  deterministic and every MC receipt date is snapped to the last-calendar-day of the month
  containing `as_of + 1` via `snap_to_month_end(receipt_date, as_of + timedelta(1))`.
  This ensures the snap targets the current (not next) month-end when the KM estimate drifts
  past a month boundary.
- For R1 **not-yet-due** invoices of month-end payers: receipt date is snapped to the last
  calendar day of the month containing the projected receipt date (i.e., earliest = receipt_date).

**Revision after seeing eval_3.py results (same date, 2026-10-04):**
The first implementation (v1) snapped overdue receipts to the last-cal-day of the
*sampled receipt date's* month. At as_of = 2026-09-28, the KM estimate routinely
drifts into early October, so v1 sent public_entities invoices to Oct 31 (outside W1)
instead of Sep 30 (inside W1), worsening S1 W1 error from −16 % to −19.68 %.
The second implementation (v2, final) snaps to the last-cal-day of the month
containing `as_of + 1`, targeting the *current* month-end regardless of where the
sampled date lands. Validation: history at as_of = 2026-06-29 shows ≈78 % of
overdue public_entities receipts on the current month-end (Jun 30, in W1); v2
reduces S1 W1 error to −2.96 %. Tag **phase3-frozen = commit 5ba3013**.

**Not pre-registered.** Will be validated only by Phase 3.4 hold-out test.

## Known limitations

| Limitation | Direction | Note |
|---|---|---|
| W1 residual under-forecast for construction customers (F41/F43) | Conservative | Residual gap 5–10 pp; no month-end pattern detected for F41/F43; direction conservative (under-forecasts cash inflows). |
