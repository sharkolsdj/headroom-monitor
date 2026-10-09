# S7 — Illustrative dataset: partial payments

Fictional company DemoCo Building Supplies S.à r.l. · forecast made on 2026-09-28 · engine tag `phase3-frozen-r1`.
All data is synthetic. Files: `weekly_forecast.csv`, `top_customers.csv`, `open_invoices.csv`, and the same three tables formatted in Excel: `S7_sample_dataset.xlsx`.

## Opening position

| Item | Value |
|---|---|
| Cash at bank | €1,200,000 |
| Safety level (4 weeks of fixed costs) | €509,538 |
| Owed by customers (all open invoices) | €5,084,470 |
| Of which overdue | €1,297,979 |

## 13-week cash plan (expected)

| Week | Starts | Receipts | Payments | Closing | Likely range | If all paid on time | Actual |
|---|---|---|---|---|---|---|---|
| 1 | 2026-09-28 | €655,195 | €348,413 | **€1,506,782** | €1,331,737 – €1,693,669 | €1,904,398 | €1,498,166 |
| 2 | 2026-10-05 | €509,437 | €398,556 | **€1,617,663** | €1,427,387 – €1,825,841 | €2,320,993 | €1,668,503 |
| 3 | 2026-10-12 | €526,208 | €953,365 | **€1,190,506** | €985,487 – €1,377,785 | €2,063,185 | €1,182,312 |
| 4 | 2026-10-19 | €514,543 | €400,886 | **€1,304,163** | €1,088,251 – €1,496,896 | €2,314,374 | €1,339,492 |
| 5 | 2026-10-26 | €562,359 | €626,736 | **€1,239,786** | €1,031,582 – €1,429,094 | €2,365,998 | €1,540,564 |
| 6 | 2026-11-02 | €489,009 | €160,521 | **€1,568,274** | €1,368,398 – €1,753,770 | €2,668,964 | €1,844,069 |
| 7 | 2026-11-09 | €523,814 | €1,285,406 | **€806,683** | €618,727 – €981,051 | €1,831,033 | €1,157,106 |
| 8 | 2026-11-16 | €483,045 | €247,503 | **€1,042,225** | €864,854 – €1,206,929 | €1,889,244 | €1,522,740 |
| 9 | 2026-11-23 | €568,724 | €350,004 | **€1,260,945** | €1,102,458 – €1,399,641 | €1,911,880 | €1,587,612 |
| 10 | 2026-11-30 | €674,838 | €762,112 | **€1,173,671** | €1,050,563 – €1,266,827 | €1,518,742 | €1,753,935 |
| 11 | 2026-12-07 | €577,948 | €434,061 | **€1,317,558** | €1,234,276 – €1,390,443 | €1,531,279 | €1,246,068 |
| 12 | 2026-12-14 | €587,637 | €696,525 | **€1,208,671** | €1,142,318 – €1,270,382 | €1,347,769 | €1,328,304 |
| 13 | 2026-12-21 | €567,175 | €395,578 | **€1,380,268** | €1,319,636 – €1,436,840 | €1,475,813 | €1,285,825 |

The expected balance stays above the safety level in all 13 weeks.

## Top 10 customers by open receivables

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

Delay = days between the due date and payment.

## Open invoices of these customers

100 open invoices, of which 32 already overdue. Each one, with its predicted payment date, likely range and remind-by date, is in `open_invoices.csv`.

## Planned payments to suppliers

Supplier invoices already received and known large bills, by week (from `weekly_forecast.csv`).

| Week | Starts | Supplier invoices received | Purchases for new sales | Known large bills |
|---|---|---|---|---|
| 1 | 2026-09-28 | €23,413 | €0 | €0 |
| 2 | 2026-10-05 | €348,556 | €0 | €0 |
| 3 | 2026-10-12 | €696,024 | €0 | €0 |
| 4 | 2026-10-19 | €400,886 | €0 | €0 |
| 5 | 2026-10-26 | €220,496 | €81,240 | €0 |
| 6 | 2026-11-02 | €0 | €110,521 | €0 |
| 7 | 2026-11-09 | €799,490 | €212,459 | €0 |
| 8 | 2026-11-16 | €0 | €247,503 | €0 |
| 9 | 2026-11-23 | €0 | €350,004 | €0 |
| 10 | 2026-11-30 | €0 | €387,112 | €0 |
| 11 | 2026-12-07 | €0 | €394,061 | €0 |
| 12 | 2026-12-14 | €0 | €396,342 | €0 |
| 13 | 2026-12-21 | €0 | €395,578 | €0 |

## Recurring outflows

Payroll, rent, overheads, tax advances and VAT, by week.

| Week | Starts | Payroll, rent, overheads, tax | VAT |
|---|---|---|---|
| 1 | 2026-09-28 | €325,000 | €0 |
| 2 | 2026-10-05 | €50,000 | €0 |
| 3 | 2026-10-12 | €177,000 | €80,341 |
| 4 | 2026-10-19 | €0 | €0 |
| 5 | 2026-10-26 | €325,000 | €0 |
| 6 | 2026-11-02 | €50,000 | €0 |
| 7 | 2026-11-09 | €177,000 | €96,457 |
| 8 | 2026-11-16 | €0 | €0 |
| 9 | 2026-11-23 | €0 | €0 |
| 10 | 2026-11-30 | €375,000 | €0 |
| 11 | 2026-12-07 | €40,000 | €0 |
| 12 | 2026-12-14 | €177,000 | €123,183 |
| 13 | 2026-12-21 | €0 | €0 |
