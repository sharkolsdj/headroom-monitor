# S6 — Illustrative dataset: new customer, slow payer

Fictional company DemoCo Building Supplies S.à r.l. · forecast made on 2026-09-28 · engine tag `phase3-frozen-r1`.
All data is synthetic. Files: `weekly_forecast.csv`, `top_customers.csv`, `open_invoices.csv`.

## Opening position

| Item | Value |
|---|---|
| Cash at bank | €1,200,000 |
| Safety level (4 weeks of fixed costs) | €509,538 |
| Owed by customers (all open invoices) | €5,489,459 |
| Of which overdue | €1,663,444 |

## 13-week cash plan (expected)

| Week | Starts | Receipts | Payments | Closing | Likely range | If all paid on time | Actual |
|---|---|---|---|---|---|---|---|
| 1 | 2026-09-28 | €775,877 | €607,634 | **€1,368,243** | €1,193,831 – €1,549,334 | €1,785,807 | €1,612,155 |
| 2 | 2026-10-05 | €481,760 | €301,063 | **€1,548,940** | €1,341,772 – €1,756,052 | €2,241,596 | €1,722,778 |
| 3 | 2026-10-12 | €505,531 | €434,193 | **€1,620,278** | €1,412,134 – €1,828,480 | €2,529,711 | €1,683,805 |
| 4 | 2026-10-19 | €584,091 | €699,417 | **€1,504,952** | €1,295,672 – €1,718,400 | €2,547,082 | €1,477,255 |
| 5 | 2026-10-26 | €553,176 | €878,773 | **€1,179,355** | €963,030 – €1,385,405 | €2,524,088 | €1,297,451 |
| 6 | 2026-11-02 | €468,040 | €158,685 | **€1,488,711** | €1,275,888 – €1,688,358 | €2,829,935 | €1,424,760 |
| 7 | 2026-11-09 | €516,093 | €482,896 | **€1,521,907** | €1,314,769 – €1,726,324 | €2,817,268 | €1,578,031 |
| 8 | 2026-11-16 | €510,411 | €244,507 | **€1,787,811** | €1,597,948 – €1,956,155 | €2,918,479 | €2,030,574 |
| 9 | 2026-11-23 | €586,709 | €945,797 | **€1,428,723** | €1,246,144 – €1,595,679 | €2,358,138 | €1,490,923 |
| 10 | 2026-11-30 | €748,238 | €756,750 | **€1,420,211** | €1,269,954 – €1,546,821 | €1,932,808 | €1,700,301 |
| 11 | 2026-12-07 | €576,647 | €433,696 | **€1,563,162** | €1,443,896 – €1,665,769 | €1,892,796 | €1,984,292 |
| 12 | 2026-12-14 | €598,107 | €693,453 | **€1,467,816** | €1,377,959 – €1,546,234 | €1,673,701 | €2,054,161 |
| 13 | 2026-12-21 | €574,730 | €394,312 | **€1,648,234** | €1,571,440 – €1,710,060 | €1,777,190 | €1,422,197 |

The expected balance stays above the safety level in all 13 weeks.

## 10 largest customers by open receivables

| Customer | Segment | Owed | Overdue | Usual delay | Last 90 days |
|---|---|---|---|---|---|
| CUST_230 | retail diy | €702,579 | €388,878 | 44 days | 49 days |
| CUST_027 | general contractors | €341,307 | €35,884 | 3 days | 5 days |
| CUST_189 | public entities | €307,661 | €196,073 | 36 days | 39 days |
| CUST_077 | specialised installers | €223,409 | €97,933 | 47 days | 43 days |
| CUST_173 | property developers | €187,697 | €19,069 | 11 days | 11 days |
| CUST_033 | general contractors | €160,368 | €32,015 | 13 days | 15 days |
| CUST_043 | general contractors | €128,503 | €52,075 | 31 days | 29 days |
| CUST_144 | specialised installers | €127,753 | €20,714 | 11 days | 12 days |
| CUST_176 | property developers | €125,626 | €41,617 | 24 days | 24 days |
| CUST_177 | property developers | €120,876 | €32,730 | 13 days | 13 days |

Delay = days between the due date and payment. Open invoices of these customers, with predicted payment dates, are in `open_invoices.csv`.
