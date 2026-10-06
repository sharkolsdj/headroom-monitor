# S7 — Illustrative dataset: partial payments

Fictional company DemoCo Building Supplies S.à r.l. · forecast made on 2026-09-28 · engine tag `phase3-frozen-r1`.
All data is synthetic. Files: `weekly_forecast.csv`, `top_customers.csv`, `open_invoices.csv`.

## Opening position

| Item | Value |
|---|---|
| Cash at bank | €1,200,000 |
| Safety level (4 weeks of fixed costs) | €509,538 |
| Owed by customers (all open invoices) | €5,085,242 |
| Of which overdue | €1,298,751 |

## 13-week cash plan (expected)

| Week | Starts | Receipts | Payments | Closing | Likely range | If all paid on time | Actual |
|---|---|---|---|---|---|---|---|
| 1 | 2026-09-28 | €663,883 | €451,692 | **€1,412,191** | €1,233,531 – €1,583,723 | €1,813,769 | €1,388,573 |
| 2 | 2026-10-05 | €502,383 | €126,457 | **€1,788,116** | €1,584,245 – €1,982,484 | €2,491,956 | €1,830,445 |
| 3 | 2026-10-12 | €519,418 | €1,418,702 | **€888,832** | €688,405 – €1,080,238 | €1,767,374 | €900,266 |
| 4 | 2026-10-19 | €517,190 | €339,048 | **€1,066,974** | €869,828 – €1,259,616 | €2,079,298 | €1,119,651 |
| 5 | 2026-10-26 | €568,725 | €432,531 | **€1,203,168** | €988,287 – €1,377,163 | €2,324,189 | €1,435,203 |
| 6 | 2026-11-02 | €485,478 | €160,521 | **€1,528,125** | €1,317,560 – €1,716,465 | €2,629,126 | €1,841,816 |
| 7 | 2026-11-09 | €526,404 | €1,095,726 | **€958,802** | €751,217 – €1,125,202 | €1,979,357 | €1,242,808 |
| 8 | 2026-11-16 | €474,845 | €247,503 | **€1,186,144** | €1,003,141 – €1,354,325 | €2,039,429 | €1,297,129 |
| 9 | 2026-11-23 | €570,564 | €350,004 | **€1,406,704** | €1,238,734 – €1,551,038 | €2,059,059 | €1,559,474 |
| 10 | 2026-11-30 | €666,734 | €762,112 | **€1,311,325** | €1,190,093 – €1,409,309 | €1,663,954 | €1,751,744 |
| 11 | 2026-12-07 | €579,428 | €434,061 | **€1,456,693** | €1,372,905 – €1,529,811 | €1,676,620 | €1,535,914 |
| 12 | 2026-12-14 | €587,443 | €696,525 | **€1,347,611** | €1,282,080 – €1,409,315 | €1,494,103 | €1,233,427 |
| 13 | 2026-12-21 | €566,522 | €395,578 | **€1,518,555** | €1,461,156 – €1,574,348 | €1,623,805 | €1,299,029 |

The expected balance stays above the safety level in all 13 weeks.

## 10 largest customers by open receivables

| Customer | Segment | Owed | Overdue | Usual delay | Last 90 days |
|---|---|---|---|---|---|
| CUST_004 | general contractors | €449,609 | €56,860 | 8 days | 9 days |
| CUST_141 | specialised installers | €282,962 | €107,762 | 29 days | 28 days |
| CUST_137 | specialised installers | €281,409 | €100,999 | 27 days | 28 days |
| CUST_119 | specialised installers | €241,074 | €37,789 | 6 days | 10 days |
| CUST_049 | general contractors | €233,395 | €0 | 9 days | 11 days |
| CUST_209 | retail diy | €173,647 | €83,571 | 34 days | 35 days |
| CUST_173 | property developers | €162,910 | €62,017 | 54 days | 52 days |
| CUST_053 | general contractors | €140,949 | €40,791 | 22 days | 19 days |
| CUST_231 | retail diy | €140,525 | €46,128 | 7 days | 8 days |
| CUST_192 | public entities | €125,993 | €79,402 | 37 days | 38 days |

Delay = days between the due date and payment. Open invoices of these customers, with predicted payment dates, are in `open_invoices.csv`.
