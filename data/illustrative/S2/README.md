# S2 — Big Customer (Illustrative Dataset)

As-of date: 2026-09-28  |  Opening balance: €1,200,000  |  Safety threshold: €509,538

---

## Opening position

| Item | Value |
|------|-------|
| Opening cash balance | €1,200,000 |
| Safety threshold (4 × weekly fixed costs) | €509,538 |
| Headroom above threshold | €690,462 |
| Total open AR | €5,560,937 |
| Total open AP | €3,722,250 |

---

## Top 10 customers by open receivables

| Customer | Segment | Open AR (€) | Avg delay (days) | Delay source |
|----------|---------|-------------|-----------------|--------------|
| CUST_037 | general_contractors | 826,239 | 28.3 | customer |
| CUST_106 | specialised_installers | 306,185 | 38.1 | customer |
| CUST_059 | general_contractors | 295,368 | 3.7 | customer |
| CUST_010 | general_contractors | 289,849 | 21.3 | customer |
| CUST_083 | specialised_installers | 228,686 | 21.1 | customer |
| CUST_063 | specialised_installers | 227,596 | 2.5 | customer |
| CUST_155 | property_developers | 156,450 | 12.5 | customer |
| CUST_173 | property_developers | 146,469 | 47.7 | customer |
| CUST_045 | general_contractors | 118,096 | 2.8 | customer |
| CUST_180 | public_entities | 108,910 | 34.1 | customer |

---

## Open invoices (top-10 customers, due within 13-week horizon)

| Invoice ID | Customer | Due date | Outstanding (€) | Overdue? |
|------------|----------|----------|-----------------|----------|
| AR_CUST_173_0033 | CUST_173 | 2026-07-12 | 10,946 | Yes |
| AR_CUST_037_0035 | CUST_037 | 2026-07-24 | 56,850 | Yes |
| AR_CUST_173_0035 | CUST_173 | 2026-07-26 | 10,912 | Yes |
| AR_CUST_010_0036 | CUST_010 | 2026-08-04 | 26,053 | Yes |
| AR_CUST_083_0038 | CUST_083 | 2026-08-06 | 20,283 | Yes |
| AR_CUST_037_0037 | CUST_037 | 2026-08-07 | 57,440 | Yes |
| AR_CUST_180_0041 | CUST_180 | 2026-08-12 | 8,958 | Yes |
| AR_CUST_037_0038 | CUST_037 | 2026-08-14 | 43,539 | Yes |
| AR_CUST_106_0040 | CUST_106 | 2026-08-16 | 25,157 | Yes |
| AR_CUST_173_0038 | CUST_173 | 2026-08-16 | 9,583 | Yes |
| AR_CUST_180_0042 | CUST_180 | 2026-08-19 | 8,658 | Yes |
| AR_CUST_037_0039 | CUST_037 | 2026-08-21 | 44,970 | Yes |
| AR_CUST_173_0039 | CUST_173 | 2026-08-23 | 7,523 | Yes |
| AR_CUST_106_0041 | CUST_106 | 2026-08-23 | 27,516 | Yes |
| AR_CUST_180_0043 | CUST_180 | 2026-08-26 | 9,708 | Yes |
| AR_CUST_037_0040 | CUST_037 | 2026-08-28 | 56,287 | Yes |
| AR_CUST_173_0040 | CUST_173 | 2026-08-30 | 8,046 | Yes |
| AR_CUST_010_0040 | CUST_010 | 2026-09-01 | 16,010 | Yes |
| AR_CUST_180_0044 | CUST_180 | 2026-09-02 | 8,255 | Yes |
| AR_CUST_083_0042 | CUST_083 | 2026-09-03 | 18,037 | Yes |
| AR_CUST_037_0041 | CUST_037 | 2026-09-04 | 51,756 | Yes |
| AR_CUST_106_0043 | CUST_106 | 2026-09-06 | 20,046 | Yes |
| AR_CUST_173_0041 | CUST_173 | 2026-09-06 | 9,914 | Yes |
| AR_CUST_010_0041 | CUST_010 | 2026-09-08 | 21,460 | Yes |
| AR_CUST_180_0045 | CUST_180 | 2026-09-09 | 7,591 | Yes |

---

## Planned payments above €50k

| Supplier | Due date | Amount (€) |
|----------|----------|------------|
| SUPP_04 | 2026-10-03 | 162,617 |
| SUPP_02 | 2026-10-05 | 146,807 |
| SUPP_03 | 2026-10-15 | 141,229 |
| SUPP_01 | 2026-10-25 | 551,598 |
| SUPP_05 | 2026-10-26 | 155,330 |
| SUPP_04 | 2026-11-02 | 157,523 |
| SUPP_01 | 2026-11-04 | 1,111,500 |
| SUPP_02 | 2026-11-05 | 164,113 |
| SUPP_01 | 2026-11-24 | 610,093 |

---

## Recurring outflows

| Kind | Rule | Monthly amount (€) |
|------|------|-------------------|
| payroll_net | day=last_working | 290,000 |
| payroll_social | day_of_month=15 | 177,000 |
| rent | day_of_month=1 | 35,000 |
| opex | day_of_month=5 | 50,000 |
| vat | day_of_month=15, following_month=True | 0 |
| tax_advance | day=10, months=[3, 6, 9, 12] | 40,000 |

---

*Generated from hm_analyst as of 2026-09-28.*
