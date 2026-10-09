# S4 — Illustrative dataset: one-week payment spike

Fictional company DemoCo Building Supplies S.à r.l. · forecast made on 2026-09-28 · engine tag `phase3-frozen-r1`.
All data is synthetic. Files: `weekly_forecast.csv`, `top_customers.csv`, `open_invoices.csv`, and the same three tables formatted in Excel: `S4_sample_dataset.xlsx`.

## Opening position

| Item | Value |
|---|---|
| Cash at bank | €1,200,000 |
| Safety level (4 weeks of fixed costs) | €509,538 |
| Owed by customers (all open invoices) | €5,301,849 |
| Of which overdue | €1,419,217 |

## 13-week cash plan (expected)

| Week | Starts | Receipts | Payments | Closing | Likely range | If all paid on time | Actual |
|---|---|---|---|---|---|---|---|
| 1 | 2026-09-28 | €730,976 | €564,122 | **€1,366,853** | €1,192,606 – €1,561,768 | €1,803,647 | €1,410,593 |
| 2 | 2026-10-05 | €524,130 | €275,011 | **€1,615,972** | €1,405,891 – €1,801,879 | €2,275,364 | €1,638,867 |
| 3 | 2026-10-12 | €508,568 | €475,165 | **€1,649,376** | €1,443,025 – €1,840,485 | €2,521,309 | €1,725,086 |
| 4 | 2026-10-19 | €523,862 | €186,247 | **€1,986,991** | €1,771,530 – €2,175,983 | €2,964,657 | €2,074,006 |
| 5 | 2026-10-26 | €554,697 | €586,523 | **€1,955,165** | €1,752,966 – €2,140,563 | €3,123,764 | €2,129,400 |
| 6 | 2026-11-02 | €473,733 | €484,438 | **€1,944,460** | €1,745,564 – €2,136,673 | €3,113,733 | €2,203,656 |
| 7 | 2026-11-09 | €485,654 | €2,233,263 | **€196,851** ⚠ | €20,115 – €385,667 | €1,322,009 | €389,339 |
| 8 | 2026-11-16 | €467,119 | €251,658 | **€412,312** ⚠ | €228,760 – €579,742 | €1,387,273 | €765,859 |
| 9 | 2026-11-23 | €530,635 | €355,533 | **€587,414** | €426,186 – €736,065 | €1,414,025 | €947,686 |
| 10 | 2026-11-30 | €660,548 | €763,880 | **€484,082** ⚠ | €353,210 – €606,435 | €955,081 | €1,016,384 |
| 11 | 2026-12-07 | €579,091 | €435,986 | **€627,187** | €524,108 – €723,205 | €942,083 | €1,337,453 |
| 12 | 2026-12-14 | €621,260 | €692,546 | **€555,901** | €472,180 – €634,024 | €756,691 | €1,337,722 |
| 13 | 2026-12-21 | €604,427 | €392,455 | **€767,873** | €694,162 – €823,121 | €889,051 | €1,290,819 |

⚠ = below the safety level. First week below: **week 7** (2026-11-09), when payments reach €2,233,263, of which €1,741,203 of supplier invoices.

**Effect of late payments:** if every customer paid on the due date, week 7 would close at €1,322,009 instead of €196,851: delays keep €1,125,158 in customers' hands.

## Top 10 customers by open receivables

| Customer | Segment | Owed | Overdue | Usual delay | Last 90 days |
|---|---|---|---|---|---|
| CUST_037 | general contractors | €567,152 | €168,438 | 23 days | 21 days |
| CUST_106 | specialised installers | €306,185 | €158,113 | 43 days | 44 days |
| CUST_059 | general contractors | €295,368 | €0 | 4 days | 6 days |
| CUST_010 | general contractors | €289,849 | €107,555 | 23 days | 20 days |
| CUST_083 | specialised installers | €228,686 | €99,013 | 21 days | 26 days |
| CUST_063 | specialised installers | €227,596 | €0 | 2 days | 2 days |
| CUST_155 | property developers | €156,450 | €31,522 | 18 days | 17 days |
| CUST_173 | property developers | €146,469 | €77,115 | 46 days | 40 days |
| CUST_045 | general contractors | €118,096 | €0 | 3 days | 4 days |
| CUST_180 | public entities | €108,910 | €63,058 | 33 days | 37 days |

Delay = days between the due date and payment.

## Open invoices of these customers

114 open invoices, of which 37 already overdue. Each one, with its predicted payment date, likely range and remind-by date, is in `open_invoices.csv`.

## Planned payments to suppliers

Supplier invoices already received and known large bills, by week (from `weekly_forecast.csv`).

| Week | Starts | Supplier invoices received | Purchases for new sales | Known large bills |
|---|---|---|---|---|
| 1 | 2026-09-28 | €239,122 | €0 | €0 |
| 2 | 2026-10-05 | €225,011 | €0 | €0 |
| 3 | 2026-10-12 | €298,165 | €0 | €0 |
| 4 | 2026-10-19 | €186,247 | €0 | €0 |
| 5 | 2026-10-26 | €178,878 | €82,645 | €0 |
| 6 | 2026-11-02 | €321,636 | €112,802 | €0 |
| 7 | 2026-11-09 | €1,741,203 | €217,117 | €0 |
| 8 | 2026-11-16 | €0 | €251,658 | €0 |
| 9 | 2026-11-23 | €0 | €355,533 | €0 |
| 10 | 2026-11-30 | €0 | €388,880 | €0 |
| 11 | 2026-12-07 | €0 | €395,986 | €0 |
| 12 | 2026-12-14 | €0 | €393,618 | €0 |
| 13 | 2026-12-21 | €0 | €392,455 | €0 |

## Recurring outflows

Payroll, rent, overheads, tax advances and VAT, by week.

| Week | Starts | Payroll, rent, overheads, tax | VAT |
|---|---|---|---|
| 1 | 2026-09-28 | €325,000 | €0 |
| 2 | 2026-10-05 | €50,000 | €0 |
| 3 | 2026-10-12 | €177,000 | €0 |
| 4 | 2026-10-19 | €0 | €0 |
| 5 | 2026-10-26 | €325,000 | €0 |
| 6 | 2026-11-02 | €50,000 | €0 |
| 7 | 2026-11-09 | €177,000 | €97,943 |
| 8 | 2026-11-16 | €0 | €0 |
| 9 | 2026-11-23 | €0 | €0 |
| 10 | 2026-11-30 | €375,000 | €0 |
| 11 | 2026-12-07 | €40,000 | €0 |
| 12 | 2026-12-14 | €177,000 | €121,928 |
| 13 | 2026-12-21 | €0 | €0 |
