# Headroom Monitor — Progress report, Phases 2 and 3

Date: 5 October 2026 · Author: Daniele · Engine tag: `phase3-frozen-r1` (commit 69a17a3, metadata fix 5fd4c5)
Specs: `docs/PHASE2_SPEC.md`, `docs/PHASE3_SPEC.md` · Pre-registration and deviation log: `docs/PHASE3_PREREG.md`

---

## 1. Where we are, in one paragraph

The cash engine is built, tested (201 automated tests) and frozen. It produces a 13-week cash forecast for the fictional company DemoCo, with three lines (on time / expected / stress), an uncertainty band, a profit-to-cash bridge, a list of every assumption, CFO overrides, per-customer payment behaviour, a collection list and sector alerts. It was then tested **once** on two datasets it had never seen. **Headline result: on unseen data, the cash shortfall caused by a slowing large customer was flagged one week before it happened (forecast week 6, actual week 7).** A sector crisis was detected as an alert but its severity was strongly underestimated. All results, including failures, are reproducible from a single command and are reported below without tuning.

---

## 2. Phase 2 — Cash engine, scenarios and uncertainty

### What was built

| Block | What it does |
|---|---|
| Time grid | 13 weeks, Monday–Sunday, from as-of 2026-09-28; opening + receipts − payments = closing |
| R1 open receivables | Each unpaid invoice gets an expected receipt date (due date + customer delay) |
| R2 future sales | Seasonal run-rate per segment, gross of 17% VAT, paid with segment terms and delay |
| P1–P5 payments | Open payables on due date; future purchases; known commitments (large bills); payroll, rent, opex, tax; monthly net VAT |
| Scenario lines | `on_time` (everybody pays on due date), `expected`, `stress` (shocks from `config/stress.yaml`) |
| Uncertainty | Monte Carlo, 1,000 seeded runs; display line = P50; band P10–P90; probability of falling below threshold |
| Profit vs cash | Monthly bridge from accrual profit to cash change, reconciled to the cent, with one template sentence per month |
| Assumptions | Every assumption listed with value, source (history / config / public data / CFO override) and affected component |
| CFO overrides | Insert-only table `hm.assumption_overrides`; superseding restores previous values; audited |
| Outputs | `hm.forecast_runs/lines`, `data/demo/<id>/forecast.json`, illustrative S2 dataset, review charts, `accuracy_summary.csv` |

The engine is deterministic Python, contains no LLM, connects as `hm_analyst` and cannot read the hidden future (`eval.*`, verified by test).

### Problems found during Phase 2 and fixed

- P2 future purchases were truncated to the horizon; P5 VAT was computed on inconsistent coverage → fixed.
- The generator's hidden future was missing about €2m of supplier payments → fixed in the generator, check added (future payments within ±10% of run-rate).
- S2 and S4 were too harsh; S4 had been contaminated with a customer drift → S4 restored to a pure timing spike.
- A check had been made "informational" to pass → reverted; rule added to `CLAUDE.md`: never loosen or bypass a check.
- `on_time` was inflated by overdue invoices; the week-1 overdue rule moved all overdue receipts to week 2 → fixed.
- The deterministic expected line sat above the Monte Carlo band → all lines now displayed as P50 of the same Monte Carlo machinery.
- Tests that rewrote committed files and order-dependent tests → fixed.

### Phase 2 baseline (frozen in `docs/BASELINE_PHASE2.md`, 2 October)

| Measure | Phase 2 baseline |
|---|---|
| S2 first week below threshold, forecast / actual | 6 / 6 |
| S3 sector crisis shown | never (actual: week 3) |
| S4 spike week | 7 / 7 |
| False-alarm weeks | 4 (S2: 2, S4: 2) |
| Week-1 error S1 / S5 / S6 / S7 / S8 | −16% / −17% / −30% / −10% / −17% |
| Band coverage S1 / S5 / S6 / S7 / S8 | 0% / 8% / 31% / 15% / 46% |

---

## 3. Phase 3 — Customer behaviour, collections and honest validation

### What was built

- **Recency-weighted payment behaviour** (half-life 60 days) with a "worsening" flag per customer.
- **Right-censoring correction** (Kaplan-Meier): unpaid overdue invoices count as "at least this late", instead of being ignored.
- **Sector trend detector** linked to the STATEC bankruptcy stress index; sector alerts in `forecast.json`.
- **Conditional timing** for overdue invoices ("given it is already 20 days late, when will it be paid?").
- **Monte Carlo** with a common shock per segment and partial payments.
- **Per-invoice predictions**: predicted payment date (P50) and range, remind-by date, reason, priority.
- **Customer ledger export** `customers.json` and **collection list** `collections.json` (for the CFO interface).
- **Month-end payment runs**: customers who always pay on the last day of the month are forecast that way.

### Method: pre-registration, deviations, hold-out

Parameters and targets were written in `docs/PHASE3_PREREG.md` **before** implementation. Every later change is logged with date and reason. The final test was run once on two datasets generated only after the engine was frozen (seed 4242), with parameters drawn at random.

### Deviation log (summary; full text in `docs/PHASE3_PREREG.md`)

| # | What | Why | Status |
|---|---|---|---|
| D1 | Kaplan-Meier correction for right-censored invoices | Ignoring unpaid overdue invoices biases delays downward | Method fix. New overdue-share thresholds (0.20 / 0.50) were introduced **after** seeing results: declared as not pre-registered |
| D2 | Sector shift when a segment is flagged but no customer is | Spec defect: shift was undefined (= 0) | Decided before seeing its effect |
| D3 | Month-end payment runs | Found by diagnostics: public entities pay 100% on the last calendar day | Rule revised **after** seeing results (v1 → v2); v2 sends all overdue month-end-payer invoices to the current month-end, while history shows ~78% |

### Bugs found and fixed (no change to model logic)

| Bug | Effect | Fix |
|---|---|---|
| Evaluation 3.3 run on stale outputs | Wrong table | One command `scripts/run_all.py` regenerates everything |
| Bias diagnostic SQL | Impossible "−77 days" means | Per-invoice diagnostic |
| STATEC segment mapping | Every sector got stress index 1.0 (public data never used) | Explicit segment → NACE map; test |
| STATEC definition | 2024 / mean(2019–23) instead of agreed 2025 / mean(2020–24) | Construction = 164 / 141.4 = 1.16; test |
| Row order from the database | Small run-to-run differences | `ORDER BY` in all loaders |
| Python hash ordering across processes | W1 error ±1–5 pp, coverage ±8 pp between runs | Sorted iterations, per-customer seeded RNG; cross-process test |
| Wall-clock timestamp in outputs | Files differ at each run | Timestamp = as-of date |
| Hold-out script | Crashed, CSV written separately | Fixed; re-run end-to-end; `git diff` empty after re-run |

### Diagnostics of the week-1 error (what was tested and ruled out)

| Hypothesis | Result |
|---|---|
| New customers borrow segment behaviour | Ruled out (all overdue invoices use own history) |
| Kaplan-Meier tail | Ruled out (residual mass ≤ 1.6%) |
| Date arithmetic bug | Ruled out (6 invoices checked by hand) |
| Quarter-end effect | Ruled out (no such rule; effect present inside history) |
| Construction holiday contamination | Explains ≤ 3 of 12 pp |
| **Month-end payment runs (public entities)** | **Confirmed**: gap at a month-end week closes from −12 pp to about −1 pp |

### Results on the 8 development datasets (`phase3-frozen-r1`)

| Target (pre-registered) | Phase 2 | Phase 3 | Met? |
|---|---|---|---|
| S2 first week below threshold within ±1 week, never later | 6 / 6 | 6 / 6 | Yes |
| S3 forecast shows the crisis | never (actual W3) | never (actual W3); sector alert fires, shift 6.9 days | **No** |
| S4 spike week | 7 | 7 | Yes |
| False alarms: 0 in S1, S5–S8 | 0 | 0 | Yes |
| False alarms: ≤ 1 per dataset elsewhere | S2: 2, S4: 2 | S2: 2, S4: 2 | **No** |
| Week-1 error ≤ 10% (S1, S5–S8) | −16 / −17 / −30 / −10 / −17% | −3.1 / −8.8 / −15.1 / +1.7 / −6.0% | 4 of 5 (S6 no) |
| Band coverage 70–90% (S1, S5–S8) | 0 / 8 / 31 / 15 / 46% | 46 / 46 / 54 / 38 / 62% | **No** (improved) |

Other week-1 errors: S2 +5.3%, S3 +36.1%, S4 −3.0%.

### Hold-out results (run once, never tuned)

Random draws (seed 4242): H1 — customer CUST_181 (2nd largest) drifts to +49 days from 5 months before as-of; inventory bill €968,595 net in week 5. H2 — specialised installers (F43) slow by +40.8 days over 3 months; 3 small customers go bankrupt.

| Measure | H1 (large customer drift) | H2 (sector slowdown) |
|---|---|---|
| First week below threshold, forecast / actual | **W6 / W7** | none / none |
| False-alarm weeks | 3 | 0 |
| Error week 1 / 4 / 13 | +23.0% / +16.7% / +1.4% | +37.4% / +59.8% / +88.7% |
| Band coverage | 61.5% | 23.1% |
| Customer flagged worsening | No (CUST_181: +9.7 days vs 10-day threshold) | n/a |
| Sector alert | n/a | Yes: specialised installers, shift 8.0 days |

### How to read these results

- **Strength:** the core promise of the case, spotting a cash shortage before it happens, held on unseen data (one week of lead time in H1; exact week in S2).
- **Limitation 1 — sector crises:** the alert fires on the right segment, but the engine applies a moderate slowdown (6.9–8 days) while the real one is a cliff (≈41 days plus bankruptcies). The CFO must judge severity; Phase 4 will show an automatic stress scenario when a sector alert fires.
- **Limitation 2 — false alarms:** early warnings tend to persist for 2–3 weeks when cash is close to the threshold. Conservative, but noisy.
- **Limitation 3 — week 1 on new data is optimistic** (+23% / +37%), most likely because rule D3 assumes 100% month-end payment where history shows ~78%.
- **Limitation 4 — the band is too narrow** (coverage 23–62% vs 70–90% target): the engine is more certain than it should be.

---

## 3b. Post-freeze generator corrections (6 October 2026)

Two generator fixes were applied after the phase3-frozen-r1 tag. The engine and all forecast metrics are unchanged; only data/demo outputs were regenerated.

1. **COGS matched to sales** (gross margin 30%): purchases are now tied to the sales run-rate rather than a fixed annual budget. Only the profit line of the profit-to-cash bridge changes; all cash data and forecast closing balances are identical to phase3-frozen-r1.
2. **S7 determinism fix**: S7 partial-payment customers were selected from a Python set, whose iteration order depends on PYTHONHASHSEED. Fixed with `sorted()`; S7 regenerated. Accuracy impact: W1 +1.70% → +0.58%, W4 −4.70% → −2.64%, W13 +16.90% → +7.34%. Band coverage 38.5%, false-alarm count 0, and first week below threshold none/none are unchanged. All other datasets and both hold-outs are byte-for-byte identical. Cross-process determinism confirmed by test `test_s7_deterministic_across_pythonhashseed`. Logged in `docs/PHASE3_PREREG.md`.

## 3c. Known test failure

`tests/test_generator.py::test_acceptance_check_passes[S2_big_customer]` fails with the frozen Phase 3 engine. The acceptance check was written against the Phase 2 engine, where the `on_time` scenario stayed above the safety threshold in all 13 weeks (min balance ≈ €698k). With the frozen Phase 3 engine, the `on_time` closing balance in week 12 is €482,817 — below the safety threshold of €509,538 — so the check correctly fires. The test and the check are not changed; the failure is declared and expected.

## 4. Next steps

1. **Phase 4 — CFO decision card:** warning with cause in plain words, actions (collection list with recalculated impact, payment timing, credit line), automatic stress scenario on sector alerts, explicit CFO approval.
2. **Phase 5 — v2 candidates (only if time and credits allow), validated on new hold-outs H3/H4 with a new seed:** month-end rule as a probability estimated from history; alarm based on probability of breach; sector shift estimated from overdue invoices. v1 results stay in the proposal.
3. **Phase 6–7:** static demo and proposal rewrite with these numbers.

## 5. How to reproduce

```
git checkout phase3-frozen-r1
python scripts/run_all.py        # 8 development datasets, charts, accuracy_summary.csv
python scripts/run_holdout.py    # H1, H2, holdout_accuracy.csv
python -m pytest -q              # 201 tests
```
