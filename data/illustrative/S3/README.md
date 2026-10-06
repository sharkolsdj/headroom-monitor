# S3 — Illustrative dataset: construction sector slowdown

Fictional company DemoCo Building Supplies S.à r.l. · forecast made on 2026-09-28 · engine tag `phase3-frozen-r1`.
All data is synthetic. Files: `weekly_forecast.csv`, `top_customers.csv`, `open_invoices.csv`.

## Opening position

| Item | Value |
|---|---|
| Cash at bank | €1,200,000 |
| Safety level (4 weeks of fixed costs) | €509,538 |
| Owed by customers (all open invoices) | €5,876,459 |
| Of which overdue | €2,339,264 |

## 13-week cash plan (expected)

| Week | Starts | Receipts | Payments | Closing | Likely range | If all paid on time | Actual |
|---|---|---|---|---|---|---|---|
| 1 | 2026-09-28 | €1,214,039 | €739,605 | **€1,674,434** | €1,222,272 – €2,086,861 | €2,103,067 | €1,230,220 |
| 2 | 2026-10-05 | €676,503 | €195,568 | **€2,155,369** | €1,693,152 – €2,528,279 | €2,880,243 | €1,321,337 |
| 3 | 2026-10-12 | €620,078 | €1,110,599 | **€1,664,847** | €1,276,258 – €2,000,379 | €2,559,298 | €469,362 |
| 4 | 2026-10-19 | €574,058 | €235,289 | **€2,003,617** | €1,669,954 – €2,299,928 | €3,032,782 | €581,075 |
| 5 | 2026-10-26 | €578,603 | €721,406 | **€1,860,813** | €1,551,773 – €2,111,735 | €3,038,795 | €610,744 |
| 6 | 2026-11-02 | €414,488 | €158,988 | **€2,116,312** | €1,858,062 – €2,368,832 | €3,299,573 | €876,858 |
| 7 | 2026-11-09 | €471,178 | €483,852 | **€2,103,638** | €1,866,655 – €2,335,832 | €3,212,296 | €1,120,039 |
| 8 | 2026-11-16 | €457,127 | €847,019 | **€1,713,745** | €1,494,011 – €1,914,775 | €2,697,388 | €487,394 |
| 9 | 2026-11-23 | €420,706 | €349,621 | **€1,784,830** | €1,585,042 – €1,954,469 | €2,629,722 | €668,027 |
| 10 | 2026-11-30 | €680,902 | €761,309 | **€1,704,423** | €1,543,274 – €1,834,902 | €2,197,002 | €830,094 |
| 11 | 2026-12-07 | €487,272 | €439,173 | **€1,752,522** | €1,629,318 – €1,859,216 | €2,099,164 | €1,244,205 |
| 12 | 2026-12-14 | €571,305 | €703,189 | **€1,620,639** | €1,516,861 – €1,703,437 | €1,857,238 | €255,596 |
| 13 | 2026-12-21 | €568,007 | €401,716 | **€1,786,930** | €1,709,246 – €1,856,501 | €1,954,572 | €756,802 |

The expected balance stays above the safety level in all 13 weeks.

## 10 largest customers by open receivables

| Customer | Segment | Owed | Overdue | Usual delay | Last 90 days |
|---|---|---|---|---|---|
| CUST_210 | retail diy | €548,994 | €120,266 | 7 days | 5 days |
| CUST_179 | public entities | €342,233 | €210,160 | 25 days | 30 days |
| CUST_163 | property developers | €266,603 | €126,974 | 45 days | 47 days |
| CUST_158 | property developers | €166,054 | €59,627 | 39 days | 37 days |
| CUST_148 | specialised installers | €161,171 | €68,449 | 25 days | 29 days |
| CUST_084 | specialised installers | €157,720 | €82,194 | 8 days | 22 days |
| CUST_113 | specialised installers | €150,960 | €35,189 | 9 days | 13 days |
| CUST_010 | general contractors | €146,460 | €48,466 | 2 days | 9 days |
| CUST_200 | public entities | €133,420 | €83,148 | 36 days | 40 days |
| CUST_154 | specialised installers | €133,152 | €75,119 | 23 days | 28 days |

Delay = days between the due date and payment. Open invoices of these customers, with predicted payment dates, are in `open_invoices.csv`.
