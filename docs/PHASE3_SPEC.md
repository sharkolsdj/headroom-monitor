# Phase 3 — Customer payment behaviour, collections and honest validation

Status: specification. Owner: Daniele. Implementation: Claude Code. Date: 2026-10-02.
Decisions: A = recency-weighted behaviour + "worsening" signal (full statistical model only as
fallback if the hold-out test fails); B = sector trend; C = conditional timing for overdue
invoices; D = honest uncertainty band; E = pre-registration + hold-out test.
New requirement: customer ledger view (accounts receivable) with predicted payment dates and
reminder suggestions.

## Working rules (to save effort and keep the exam fair)

- Keep responses short. No full-file dumps. Run the test suite once at the end of each step,
  in the foreground, with `pytest -q`. No background polling.
- Tests must never write files that are committed (use temporary directories).
- Section 1 (pre-registration) is fixed **before** implementation. After seeing results, a
  parameter may change only to fix a documented bug; every change is logged in
  `docs/PHASE3_PREREG.md` with date and reason.
- Never loosen a check or a target to make it pass: report instead.
- No LLM in this phase. All customer sentences come from templates.

## 1. Pre-registration (copy to `docs/PHASE3_PREREG.md` and commit before step 3.2)

### Parameters and rationale

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

### Targets (fill the "Phase 2 baseline" column with the re-baselined values of step 3.0)

| Target | Phase 2 baseline | Phase 3 target |
|---|---|---|
| S2: first forecast week below threshold vs actual | (3.0) | within ±1 week of actual, never later |
| S3: forecast shows the crisis | (3.0) | at least one week below threshold, within ±1 week of the actual crisis window |
| S4: spike week | (3.0) | still week 7 |
| False-alarm weeks (P50 below threshold while actual above), all datasets | (3.0) | 0 in S1, S5–S8; at most 1 per dataset elsewhere |
| Week-1 absolute error, S1 and S5–S8 | (3.0) | ≤ 10% |
| Band coverage (actual inside P10–P90), S1 and S5–S8 | (3.0) | 70–90% |

## 2. Steps

### 3.0 — Re-baseline and consistency (small)

1. Compute **all three lines with the same Monte Carlo machinery**:
   `on_time` (not-yet-due invoices delay 0; overdue invoices same conditional rule as expected),
   `expected`, and `stress` (expected + shocks). Display the P50 of each; the band only around expected.
   Today on_time and stress are deterministic while expected is P50, which produces impossible
   charts (S3 week 1: on_time below expected; S3 later weeks: stress above expected).
2. Recompute `accuracy_summary.csv` using the displayed (P50) lines, and add per dataset:
   first forecast week below threshold, first actual week below threshold, false-alarm weeks.
3. Save the result as `docs/BASELINE_PHASE2.md` (frozen table) and fill the baseline column of
   the targets table.
4. Fix tests that rewrite committed data files.
5. Regenerate charts. **Stop and report**: the baseline table only.

### 3.1 — Pre-registration
Copy section 1 into `docs/PHASE3_PREREG.md` with the baseline values; commit. Do not implement yet.

### 3.2 — Behaviour model and collections data

- `RecencyBehaviour` (implements `PaymentBehaviourModel`): weighted delay samples, typical delay
  (weighted median), recent delay (last 90 days), worsening flag, source tag
  ("customer" / "segment" / "segment trend").
- Sector trend detector linked to the STATEC stress index.
- Conditional overdue timing used in both the deterministic components and the Monte Carlo.
- Monte Carlo: segment common shock and partial payments.
- **Per open invoice**: predicted payment date (P50), date range (P10–P90), remind-by date,
  reason code, priority score.
- **Per customer** export `data/demo/<id>/customers.json`: code, segment, total owed, overdue
  amount, paid invoices (date, amount, days late), open invoices (due date, days to due or days
  overdue, predicted payment date and range, remind-by), typical delay, recent delay, trend
  (stable / worsening / improving), one template sentence, priority rank.
  Example sentence: "Usually pays 12 days late; in the last 3 months 38 days late: worsening."
- **Collection list** per dataset `data/demo/<id>/collections.json`: customers to contact,
  ordered by priority, with amount at stake in the critical weeks and remind-by date.
- **Sector alerts** in `forecast.json`: e.g. "23 of 58 construction customers are paying later
  than usual; STATEC construction bankruptcies +16% vs 5-year average."
- Document the new files in `docs/demo_data_format.md`.
- Tests: weights and half-life; worsening flag fires on a constructed drifting customer and not
  on a stable noisy one; sector trend fires on a constructed cohort; conditional timing on a
  hand-built case; priority ordering; Monte Carlo reproducible.

### 3.3 — Evaluation (one run)
Run all 8 datasets, print the targets table (baseline vs Phase 3) and the list of customers
flagged worsening in S2 and of segments flagged in S3. **Stop and report.** Do not tune after
this point except documented bug fixes.

### 3.4 — Freeze and hold-out test
1. Tag the commit `phase3-frozen`.
2. Generate two **hold-out datasets** never seen during development, with seed 4242 and
   parameters drawn at random within these ranges (draw recorded in `eval.scenario_truth`):
   - `H1_drift`: one customer among the top 5 by revenue (random) drifts by +30 to +70 days,
     starting 2 to 5 months before as-of; one inventory bill of €0.7–1.1m net in weeks 5–8.
   - `H2_sector`: one segment among F41 / F43 / L68 (random) slows by +20 to +50 days over the
     last 3 months; 1 to 3 small customers of that segment go bankrupt in the horizon.
   Keep company-level constraints (as-of balance €1.2m, profit range, top-20 share).
3. Run the frozen engine once on H1 and H2 and report the same metrics. These numbers go into
   the proposal whatever they are.

## Definition of done
- [ ] 3.0 baseline frozen, charts consistent
- [ ] 3.1 pre-registration committed before implementation
- [ ] 3.2 behaviour model, collections data, customer export, tests green
- [ ] 3.3 targets table reported
- [ ] 3.4 frozen tag, hold-out results reported
