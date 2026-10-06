# S8 — Illustrative dataset: late month-end close

Fictional company DemoCo Building Supplies S.à r.l. · forecast made on 2026-09-28 · engine tag `phase3-frozen-r1`.
All data is synthetic. Files: `weekly_forecast.csv`, `top_customers.csv`, `open_invoices.csv`.

## Opening position

| Item | Value |
|---|---|
| Cash at bank | €1,200,000 |
| Safety level (4 weeks of fixed costs) | €509,538 |
| Owed by customers (all open invoices) | €5,434,369 |
| Of which overdue | €1,400,127 |

## 13-week cash plan (expected)

| Week | Starts | Receipts | Payments | Closing | Likely range | If all paid on time | Actual |
|---|---|---|---|---|---|---|---|
| 1 | 2026-09-28 | €751,267 | €568,342 | **€1,382,925** | €1,121,166 – €1,598,504 | €1,823,530 | €1,470,933 |
| 2 | 2026-10-05 | €482,348 | €211,246 | **€1,654,027** | €1,431,442 – €1,884,746 | €2,348,198 | €1,652,892 |
| 3 | 2026-10-12 | €489,412 | €673,716 | **€1,469,723** | €1,222,492 – €1,706,251 | €2,387,010 | €1,405,916 |
| 4 | 2026-10-19 | €499,028 | €376,155 | **€1,592,596** | €1,333,857 – €1,829,325 | €2,690,792 | €1,550,182 |
| 5 | 2026-10-26 | €542,414 | €956,941 | **€1,178,069** | €917,905 – €1,426,806 | €2,438,052 | €1,406,069 |
| 6 | 2026-11-02 | €497,414 | €323,694 | **€1,351,789** | €1,082,055 – €1,607,122 | €2,603,747 | €1,436,008 |
| 7 | 2026-11-09 | €505,168 | €483,818 | **€1,373,139** | €1,114,405 – €1,656,825 | €2,559,681 | €1,539,318 |
| 8 | 2026-11-16 | €488,695 | €246,790 | **€1,615,045** | €1,310,296 – €1,887,982 | €2,684,648 | €1,685,012 |
| 9 | 2026-11-23 | €539,285 | €916,857 | **€1,237,473** | €957,240 – €1,505,790 | €2,171,564 | €1,559,462 |
| 10 | 2026-11-30 | €683,274 | €756,792 | **€1,163,955** | €896,145 – €1,397,675 | €1,712,507 | €1,787,391 |
| 11 | 2026-12-07 | €654,449 | €427,203 | **€1,391,201** | €1,144,743 – €1,570,425 | €1,723,417 | €1,913,078 |
| 12 | 2026-12-14 | €650,163 | €689,377 | **€1,351,987** | €1,162,007 – €1,475,151 | €1,535,754 | €1,723,081 |
| 13 | 2026-12-21 | €601,293 | €392,920 | **€1,560,359** | €1,416,697 – €1,628,631 | €1,649,473 | €1,285,333 |

The expected balance stays above the safety level in all 13 weeks.

## 10 largest customers by open receivables

| Customer | Segment | Owed | Overdue | Usual delay | Last 90 days |
|---|---|---|---|---|---|
| CUST_007 | general contractors | €1,541,707 | €409,270 | 26 days | 28 days |
| CUST_154 | specialised installers | €222,994 | €95,012 | 21 days | 24 days |
| CUST_178 | property developers | €203,874 | €41,755 | 13 days | 13 days |
| CUST_050 | general contractors | €146,931 | €14,960 | 2 days | 3 days |
| CUST_197 | public entities | €144,719 | €93,107 | 37 days | 40 days |
| CUST_005 | general contractors | €144,120 | €12,843 | 9 days | 11 days |
| CUST_166 | property developers | €137,114 | €27,034 | 11 days | 12 days |
| CUST_156 | property developers | €135,410 | €36,491 | 26 days | 28 days |
| CUST_145 | specialised installers | €104,493 | €14,213 | 11 days | 13 days |
| CUST_047 | general contractors | €90,317 | €24,858 | 22 days | 23 days |

Delay = days between the due date and payment. Open invoices of these customers, with predicted payment dates, are in `open_invoices.csv`.
