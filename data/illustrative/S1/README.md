# S1 — Illustrative dataset: normal quarter

Fictional company DemoCo Building Supplies S.à r.l. · forecast made on 2026-09-28 · engine tag `phase3-frozen-r1`.
All data is synthetic. Files: `weekly_forecast.csv`, `top_customers.csv`, `open_invoices.csv`, and the same three tables formatted in Excel: `S1_sample_dataset.xlsx`.

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
| 3 | 2026-10-12 | €508,568 | €556,261 | **€1,568,278** | €1,361,927 – €1,759,752 | €2,440,094 | €1,637,888 |
| 4 | 2026-10-19 | €524,087 | €737,845 | **€1,354,521** | €1,138,810 – €1,544,161 | €2,332,060 | €1,435,210 |
| 5 | 2026-10-26 | €554,657 | €586,523 | **€1,322,655** | €1,120,961 – €1,507,608 | €2,490,961 | €1,490,604 |
| 6 | 2026-11-02 | €473,903 | €484,438 | **€1,312,120** | €1,112,837 – €1,503,862 | €2,480,434 | €1,564,860 |
| 7 | 2026-11-09 | €485,731 | €492,060 | **€1,305,791** | €1,128,030 – €1,493,999 | €2,430,752 | €1,615,948 |
| 8 | 2026-11-16 | €466,465 | €251,658 | **€1,520,598** | €1,336,571 – €1,688,588 | €2,495,721 | €1,992,469 |
| 9 | 2026-11-23 | €531,330 | €965,626 | **€1,086,301** | €924,786 – €1,234,103 | €1,912,296 | €1,564,203 |
| 10 | 2026-11-30 | €660,350 | €763,880 | **€982,772** | €851,502 – €1,104,482 | €1,453,492 | €1,632,900 |
| 11 | 2026-12-07 | €579,230 | €435,986 | **€1,126,015** | €1,022,773 – €1,221,773 | €1,440,255 | €1,913,969 |
| 12 | 2026-12-14 | €620,807 | €692,546 | **€1,054,276** | €969,725 – €1,132,485 | €1,255,368 | €1,914,238 |
| 13 | 2026-12-21 | €604,566 | €392,455 | **€1,266,387** | €1,192,734 – €1,321,591 | €1,387,176 | €1,287,823 |

The expected balance stays above the safety level in all 13 weeks.

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
| 4 | 2026-10-19 | €737,845 | €0 | €0 |
| 5 | 2026-10-26 | €178,878 | €82,645 | €0 |
| 6 | 2026-11-02 | €321,636 | €112,802 | €0 |
| 7 | 2026-11-09 | €0 | €217,117 | €0 |
| 8 | 2026-11-16 | €0 | €251,658 | €0 |
| 9 | 2026-11-23 | €610,093 | €355,533 | €0 |
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
| 3 | 2026-10-12 | €177,000 | €81,096 |
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
