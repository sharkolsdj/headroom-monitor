# H1 — Illustrative dataset: unseen test, customer drift

Fictional company DemoCo Building Supplies S.à r.l. · forecast made on 2026-09-28 · engine tag `phase3-frozen-r1`.
All data is synthetic. Files: `weekly_forecast.csv`, `top_customers.csv`, `open_invoices.csv`.

## Opening position

| Item | Value |
|---|---|
| Cash at bank | €1,200,000 |
| Safety level (4 weeks of fixed costs) | €509,538 |
| Owed by customers (all open invoices) | €5,455,715 |
| Of which overdue | €1,873,827 |

## 13-week cash plan (expected)

| Week | Starts | Receipts | Payments | Closing | Likely range | If all paid on time | Actual |
|---|---|---|---|---|---|---|---|
| 1 | 2026-09-28 | €1,246,741 | €629,833 | **€1,816,908** | €1,615,394 – €1,994,849 | €2,139,140 | €1,476,970 |
| 2 | 2026-10-05 | €462,075 | €332,894 | **€1,946,089** | €1,733,611 – €2,142,157 | €2,559,059 | €1,586,316 |
| 3 | 2026-10-12 | €461,087 | €1,096,236 | **€1,310,940** | €1,092,109 – €1,510,007 | €2,119,186 | €1,177,316 |
| 4 | 2026-10-19 | €475,060 | €243,060 | **€1,542,940** | €1,309,672 – €1,754,148 | €2,484,216 | €1,322,283 |
| 5 | 2026-10-26 | €550,341 | €1,565,367 | **€527,913** | €304,094 – €743,836 | €1,787,026 | €711,614 |
| 6 | 2026-11-02 | €422,166 | €478,702 | **€471,377** ⚠ | €256,650 – €677,278 | €1,720,620 | €644,962 |
| 7 | 2026-11-09 | €440,201 | €1,062,500 | **−€150,922** ⚠ | −€361,772 – €52,816 | €1,036,383 | −€231,676 |
| 8 | 2026-11-16 | €407,990 | €248,882 | **€8,186** ⚠ | −€197,522 – €210,385 | €1,047,937 | €213,693 |
| 9 | 2026-11-23 | €509,886 | €350,140 | **€167,932** ⚠ | −€17,826 – €350,398 | €1,022,448 | €319,214 |
| 10 | 2026-11-30 | €817,965 | €759,719 | **€226,179** ⚠ | €60,282 – €367,015 | €626,114 | €537,526 |
| 11 | 2026-12-07 | €536,987 | €432,130 | **€331,036** ⚠ | €200,113 – €449,481 | €607,017 | €766,380 |
| 12 | 2026-12-14 | €526,905 | €691,746 | **€166,194** ⚠ | €56,212 – €271,270 | €364,867 | €143,854 |
| 13 | 2026-12-21 | €504,222 | €393,019 | **€277,396** ⚠ | €167,907 – €380,431 | €431,195 | €273,498 |

⚠ = below the safety level. First week below: **week 6** (2026-11-02), when payments reach €478,702, of which €316,112 of supplier invoices.

**Effect of late payments:** if every customer paid on the due date, week 6 would close at €1,720,620 instead of €471,377: delays keep €1,249,243 in customers' hands.

## 10 largest customers by open receivables

| Customer | Segment | Owed | Overdue | Usual delay | Last 90 days |
|---|---|---|---|---|---|
| CUST_119 | specialised installers | €717,270 | €258,220 | 21 days | 26 days |
| CUST_181 | public entities | €686,408 | €479,150 | 33 days | 43 days |
| CUST_053 | general contractors | €356,076 | €75,186 | 7 days | 6 days |
| CUST_055 | general contractors | €197,179 | €22,131 | 11 days | 12 days |
| CUST_037 | general contractors | €168,988 | €57,546 | 35 days | 34 days |
| CUST_178 | property developers | €129,608 | €40,206 | 14 days | 17 days |
| CUST_237 | retail diy | €128,322 | €21,294 | 4 days | 8 days |
| CUST_114 | specialised installers | €118,673 | €51,281 | 41 days | 37 days |
| CUST_148 | specialised installers | €114,437 | €34,872 | 19 days | 23 days |
| CUST_195 | public entities | €112,359 | €77,001 | 32 days | 39 days |

Delay = days between the due date and payment. Open invoices of these customers, with predicted payment dates, are in `open_invoices.csv`.
