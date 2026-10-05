# S2 — Illustrative dataset: a large customer slows down

Fictional company DemoCo Building Supplies S.à r.l. · forecast made on 2026-09-28 · engine tag `phase3-frozen-r1`.
All data is synthetic. Files: `weekly_forecast.csv`, `top_customers.csv`, `open_invoices.csv`.

## Opening position

| Item | Value |
|---|---|
| Cash at bank | €1,200,000 |
| Safety level (4 weeks of fixed costs) | €509,538 |
| Owed by customers (all open invoices) | €5,560,937 |
| Of which overdue | €1,678,304 |

## 13-week cash plan (expected)

| Week | Starts | Receipts | Payments | Closing | Likely range | If all paid on time | Actual |
|---|---|---|---|---|---|---|---|
| 1 | 2026-09-28 | €810,745 | €564,122 | **€1,446,623** | €1,231,071 – €1,705,191 | €1,894,263 | €1,379,575 |
| 2 | 2026-10-05 | €546,583 | €275,011 | **€1,718,196** | €1,492,630 – €1,964,493 | €2,403,244 | €1,627,879 |
| 3 | 2026-10-12 | €546,169 | €475,165 | **€1,789,200** | €1,561,727 – €2,017,527 | €2,681,737 | €1,759,447 |
| 4 | 2026-10-19 | €524,490 | €737,845 | **€1,575,846** | €1,368,405 – €1,801,556 | €2,595,044 | €1,503,999 |
| 5 | 2026-10-26 | €562,885 | €586,523 | **€1,552,208** | €1,339,764 – €1,774,739 | €2,780,156 | €1,520,987 |
| 6 | 2026-11-02 | €485,926 | €1,595,938 | **€442,196** ⚠ | €232,006 – €652,281 | €1,681,556 | €453,599 |
| 7 | 2026-11-09 | €485,870 | €492,060 | **€436,006** ⚠ | €241,696 – €650,981 | €1,644,653 | €460,839 |
| 8 | 2026-11-16 | €457,564 | €251,658 | **€641,912** | €458,074 – €837,672 | €1,719,262 | €881,368 |
| 9 | 2026-11-23 | €544,371 | €965,626 | **€220,657** ⚠ | €44,089 – €378,368 | €1,139,788 | €453,102 |
| 10 | 2026-11-30 | €652,811 | €763,880 | **€109,588** ⚠ | −€26,541 – €242,348 | €682,081 | €473,546 |
| 11 | 2026-12-07 | €585,736 | €435,986 | **€259,338** ⚠ | €148,203 – €370,276 | €668,585 | €797,775 |
| 12 | 2026-12-14 | €628,729 | €692,546 | **€195,521** ⚠ | €91,428 – €298,887 | €482,817 | €750,310 |
| 13 | 2026-12-21 | €616,809 | €392,455 | **€419,876** ⚠ | €333,132 – €504,041 | €614,126 | €215,072 |

⚠ = below the safety level. First week below: **week 6** (2026-11-02), when payments reach €1,595,938, of which €1,433,136 of supplier invoices (the winter-stock order).

**Effect of late payments:** if every customer paid on the due date, week 6 would close at €1,681,556 instead of €442,196: delays keep €1,239,360 in customers' hands.

## 10 largest customers by open receivables

| Customer | Segment | Owed | Overdue | Usual delay | Last 90 days |
|---|---|---|---|---|---|
| CUST_037 | general contractors | €826,239 | €427,526 | 34 days | 44 days |
| CUST_106 | specialised installers | €306,185 | €158,113 | 43 days | 44 days |
| CUST_059 | general contractors | €295,368 | €0 | 4 days | 6 days |
| CUST_010 | general contractors | €289,849 | €107,555 | 23 days | 20 days |
| CUST_083 | specialised installers | €228,686 | €99,013 | 21 days | 26 days |
| CUST_063 | specialised installers | €227,596 | €0 | 2 days | 2 days |
| CUST_155 | property developers | €156,450 | €31,522 | 18 days | 17 days |
| CUST_173 | property developers | €146,469 | €77,115 | 46 days | 40 days |
| CUST_045 | general contractors | €118,096 | €0 | 3 days | 4 days |
| CUST_180 | public entities | €108,910 | €63,058 | 33 days | 37 days |

Delay = days between the due date and payment. Open invoices of these customers, with predicted payment dates, are in `open_invoices.csv`.
