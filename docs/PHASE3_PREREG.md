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

*(empty — no changes since pre-registration)*
