# S5 — Illustrative dataset: seasonal slowdowns

Fictional company DemoCo Building Supplies S.à r.l. · forecast made on 2026-09-28 · engine tag `phase3-frozen-r1`.
All data is synthetic. Files: `weekly_forecast.csv`, `top_customers.csv`, `open_invoices.csv`.

## Opening position

| Item | Value |
|---|---|
| Cash at bank | €1,200,000 |
| Safety level (4 weeks of fixed costs) | €509,538 |
| Owed by customers (all open invoices) | €4,762,454 |
| Of which overdue | €953,519 |

## 13-week cash plan (expected)

| Week | Starts | Receipts | Payments | Closing | Likely range | If all paid on time | Actual |
|---|---|---|---|---|---|---|---|
| 1 | 2026-09-28 | €593,645 | €545,982 | **€1,247,663** | €1,094,653 – €1,401,260 | €1,649,704 | €1,368,251 |
| 2 | 2026-10-05 | €527,187 | €201,722 | **€1,573,129** | €1,390,106 – €1,734,070 | €2,205,361 | €1,670,960 |
| 3 | 2026-10-12 | €525,794 | €1,174,024 | **€924,899** | €750,912 – €1,090,917 | €1,706,990 | €1,014,859 |
| 4 | 2026-10-19 | €545,208 | €254,510 | **€1,215,597** | €1,036,647 – €1,380,941 | €2,031,499 | €1,303,337 |
| 5 | 2026-10-26 | €561,509 | €746,520 | **€1,030,585** | €858,639 – €1,197,645 | €1,932,171 | €1,201,996 |
| 6 | 2026-11-02 | €549,595 | €160,495 | **€1,419,686** | €1,253,619 – €1,574,629 | €2,292,160 | €1,679,917 |
| 7 | 2026-11-09 | €511,195 | €1,037,650 | **€893,231** | €733,966 – €1,046,449 | €1,677,972 | €968,936 |
| 8 | 2026-11-16 | €448,135 | €246,395 | **€1,094,971** | €954,269 – €1,223,568 | €1,700,417 | €1,416,623 |
| 9 | 2026-11-23 | €527,796 | €353,318 | **€1,269,449** | €1,151,799 – €1,371,511 | €1,729,163 | €1,558,912 |
| 10 | 2026-11-30 | €596,043 | €759,878 | **€1,105,614** | €1,019,890 – €1,180,848 | €1,345,093 | €1,721,804 |
| 11 | 2026-12-07 | €574,102 | €436,578 | **€1,243,138** | €1,177,386 – €1,304,707 | €1,388,336 | €1,968,718 |
| 12 | 2026-12-14 | €581,822 | €697,303 | **€1,127,657** | €1,077,025 – €1,176,864 | €1,209,708 | €1,334,413 |
| 13 | 2026-12-21 | €574,209 | €398,126 | **€1,303,740** | €1,262,102 – €1,343,484 | €1,345,402 | €1,278,589 |

The expected balance stays above the safety level in all 13 weeks.

## 10 largest customers by open receivables

| Customer | Segment | Owed | Overdue | Usual delay | Last 90 days |
|---|---|---|---|---|---|
| CUST_061 | specialised installers | €335,565 | €113,303 | 21 days | 27 days |
| CUST_171 | property developers | €298,744 | €25,545 | 2 days | 3 days |
| CUST_088 | specialised installers | €256,048 | €42,058 | 3 days | 3 days |
| CUST_035 | general contractors | €249,511 | €60,994 | 20 days | 22 days |
| CUST_139 | specialised installers | €241,813 | €61,525 | 10 days | 9 days |
| CUST_010 | general contractors | €203,627 | €40,271 | 10 days | 15 days |
| CUST_056 | general contractors | €147,329 | €15,412 | 8 days | 10 days |
| CUST_037 | general contractors | €127,715 | €15,850 | 3 days | 4 days |
| CUST_116 | specialised installers | €125,343 | €14,178 | 12 days | 12 days |
| CUST_014 | general contractors | €107,549 | €20,242 | 8 days | 10 days |

Delay = days between the due date and payment. Open invoices of these customers, with predicted payment dates, are in `open_invoices.csv`.
