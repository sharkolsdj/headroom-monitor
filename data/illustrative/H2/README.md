# H2 — Illustrative dataset: unseen test, sector slowdown

Fictional company DemoCo Building Supplies S.à r.l. · forecast made on 2026-09-28 · engine tag `phase3-frozen-r1`.
All data is synthetic. Files: `weekly_forecast.csv`, `top_customers.csv`, `open_invoices.csv`.

## Opening position

| Item | Value |
|---|---|
| Cash at bank | €1,200,000 |
| Safety level (4 weeks of fixed costs) | €509,538 |
| Owed by customers (all open invoices) | €5,943,841 |
| Of which overdue | €2,368,103 |

## 13-week cash plan (expected)

| Week | Starts | Receipts | Payments | Closing | Likely range | If all paid on time | Actual |
|---|---|---|---|---|---|---|---|
| 1 | 2026-09-28 | €1,330,903 | €374,313 | **€2,156,590** | €1,562,466 – €2,622,219 | €2,502,887 | €1,570,190 |
| 2 | 2026-10-05 | €588,898 | €312,315 | **€2,433,173** | €1,865,343 – €2,808,952 | €3,046,103 | €1,659,862 |
| 3 | 2026-10-12 | €551,532 | €623,022 | **€2,361,684** | €1,869,284 – €2,694,600 | €3,213,358 | €1,537,221 |
| 4 | 2026-10-19 | €491,508 | €441,596 | **€2,411,595** | €1,984,686 – €2,732,304 | €3,408,370 | €1,508,991 |
| 5 | 2026-10-26 | €639,073 | €1,099,022 | **€1,951,647** | €1,537,700 – €2,277,535 | €3,285,003 | €1,356,950 |
| 6 | 2026-11-02 | €446,364 | €308,027 | **€2,089,983** | €1,726,916 – €2,380,559 | €3,390,669 | €1,402,354 |
| 7 | 2026-11-09 | €434,784 | €488,146 | **€2,036,621** | €1,691,815 – €2,345,188 | €3,267,066 | €1,326,973 |
| 8 | 2026-11-16 | €420,016 | €248,408 | **€2,208,229** | €1,882,990 – €2,476,619 | €3,260,332 | €1,439,814 |
| 9 | 2026-11-23 | €400,403 | €986,647 | **€1,621,986** | €1,313,654 – €1,853,645 | €2,471,704 | €1,087,993 |
| 10 | 2026-11-30 | €775,432 | €760,971 | **€1,636,447** | €1,421,901 – €1,807,506 | €2,028,959 | €1,535,661 |
| 11 | 2026-12-07 | €552,291 | €432,483 | **€1,756,255** | €1,584,429 – €1,877,166 | €2,001,029 | €1,740,062 |
| 12 | 2026-12-14 | €548,429 | €693,946 | **€1,610,739** | €1,473,027 – €1,694,733 | €1,753,881 | €1,430,100 |
| 13 | 2026-12-21 | €509,366 | €392,756 | **€1,727,349** | €1,633,272 – €1,794,960 | €1,821,763 | €915,658 |

The expected balance stays above the safety level in all 13 weeks.

## Top 10 customers by open receivables

| Customer | Segment | Owed | Overdue | Usual delay | Last 90 days |
|---|---|---|---|---|---|
| CUST_119 | specialised installers | €794,094 | €430,131 | 26 days | 31 days |
| CUST_181 | public entities | €384,565 | €205,341 | 20 days | 22 days |
| CUST_053 | general contractors | €356,076 | €75,186 | 7 days | 6 days |
| CUST_055 | general contractors | €197,179 | €22,131 | 11 days | 12 days |
| CUST_148 | specialised installers | €174,049 | €81,054 | 25 days | 29 days |
| CUST_037 | general contractors | €168,988 | €57,546 | 35 days | 34 days |
| CUST_114 | specialised installers | €159,206 | €83,263 | 35 days | 46 days |
| CUST_237 | retail diy | €151,572 | €21,401 | 9 days | 8 days |
| CUST_091 | specialised installers | €147,076 | €68,648 | 20 days | 25 days |
| CUST_080 | specialised installers | €116,746 | €50,334 | 3 days | 18 days |

Delay = days between the due date and payment.

## Open invoices of these customers

115 open invoices, of which 47 already overdue. Each one, with its predicted payment date, likely range and remind-by date, is in `open_invoices.csv`.

## Planned payments to suppliers

Supplier invoices already received and known large bills, by week (from `weekly_forecast.csv`).

| Week | Starts | Supplier invoices received | Purchases for new sales | Known large bills |
|---|---|---|---|---|
| 1 | 2026-09-28 | €49,313 | €0 | €0 |
| 2 | 2026-10-05 | €262,315 | €0 | €0 |
| 3 | 2026-10-12 | €252,912 | €0 | €0 |
| 4 | 2026-10-19 | €441,596 | €0 | €0 |
| 5 | 2026-10-26 | €691,547 | €82,475 | €0 |
| 6 | 2026-11-02 | €146,789 | €111,239 | €0 |
| 7 | 2026-11-09 | €0 | €214,531 | €0 |
| 8 | 2026-11-16 | €0 | €248,408 | €0 |
| 9 | 2026-11-23 | €635,120 | €351,527 | €0 |
| 10 | 2026-11-30 | €0 | €385,971 | €0 |
| 11 | 2026-12-07 | €0 | €392,483 | €0 |
| 12 | 2026-12-14 | €0 | €394,025 | €0 |
| 13 | 2026-12-21 | €0 | €392,756 | €0 |

## Recurring outflows

Payroll, rent, overheads, tax advances and VAT, by week.

| Week | Starts | Payroll, rent, overheads, tax | VAT |
|---|---|---|---|
| 1 | 2026-09-28 | €325,000 | €0 |
| 2 | 2026-10-05 | €50,000 | €0 |
| 3 | 2026-10-12 | €177,000 | €193,110 |
| 4 | 2026-10-19 | €0 | €0 |
| 5 | 2026-10-26 | €325,000 | €0 |
| 6 | 2026-11-02 | €50,000 | €0 |
| 7 | 2026-11-09 | €177,000 | €96,615 |
| 8 | 2026-11-16 | €0 | €0 |
| 9 | 2026-11-23 | €0 | €0 |
| 10 | 2026-11-30 | €375,000 | €0 |
| 11 | 2026-12-07 | €40,000 | €0 |
| 12 | 2026-12-14 | €177,000 | €122,920 |
| 13 | 2026-12-21 | €0 | €0 |
