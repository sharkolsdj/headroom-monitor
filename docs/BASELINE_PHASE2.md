# Phase 2 Baseline (frozen 2026-10-02, ENGINE_VERSION 3.0.0)

All lines are P50 of the Monte Carlo run (1 000 iterations, seed 42).
Band = P10–P90 around expected only. False-alarm = week where P50 < threshold but actual ≥ threshold.

## Accuracy summary

| Dataset | W1 err € | W1 % | W4 % | W13 % | Band cov % | Thresh fcst / act | False alarms |
|---|---|---|---|---|---|---|---|
| S1_normal | -224 750 | -15.9 | -11.9 | +8.8 | 0.0 | — / — | 0 |
| S2_big_customer | -47 113 | -3.4 | +3.8 | +179.7 | 61.5 | **6 / 6** | 2 |
| S3_sector_crisis | +548 518 | +44.6 | +258.9 | +216.0 | 0.0 | — / **3** | 0 |
| S4_outflow_spike | -224 750 | -15.9 | -8.5 | -30.0 | 0.0 | **7 / 7** | 2 |
| S5_seasonality | -231 665 | -16.9 | -12.5 | +0.6 | 7.7 | — / — | 0 |
| S6_new_customer | -485 454 | -30.1 | -3.0 | +27.9 | 30.8 | — / — | 0 |
| S7_partial_payments | -120 753 | -9.6 | -8.8 | -1.1 | 15.4 | — / — | 0 |
| S8_month_end_close | -254 053 | -17.3 | -4.0 | +22.9 | 46.2 | — / — | 0 |

## Targets table (Phase 2 baseline column)

| Target | Phase 2 baseline |
|---|---|
| S2: first forecast week below threshold vs actual | 6 / 6 (exact match) |
| S3: forecast shows the crisis | P50 never breaches threshold; actual breaches at week 3 |
| S4: spike week | 7 / 7 (exact match) |
| False-alarm weeks (all datasets) | 4 total — S2: 2, S4: 2; all others 0 |
| Week-1 absolute error, S1 and S5–S8 | S1: −16%, S5: −17%, S6: −30%, S7: −10%, S8: −17% |
| Band coverage (P10–P90), S1 and S5–S8 | S1: 0%, S5: 8%, S6: 31%, S7: 15%, S8: 46% |

## Notes

- W1 error entirely in R1 (open AR collection timing); P1, P4, P5 match exactly.
- Band coverage 0–62 % vs target 70–90 %: delay distribution too narrow; no common shock; no partial payments.
- S3 crisis not detected: week-1 P50 is *above* actual (P50 over-forecasts R1 in a crisis because it uses long-run mean delays).
- S2 W13 error +180 %: the big customer pays very late in actuals; P50 distributes receipts more evenly across the horizon.
