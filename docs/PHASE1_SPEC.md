# Phase 1 — Synthetic data, public data and data protection

Status: specification, to be implemented in three steps (1A, 1B, 1C).
Everything in this phase is **synthetic** except the public statistics in `data/public/`.
Owner: Daniele. Implementation: Claude Code. Date: 2026-09-30.

## 0. Principles (apply to every step)

- All cash numbers are computed deterministically in Python. No LLM is used in this phase.
- Every generator run is reproducible: one global `SEED` in config, and a per-dataset seed derived from it.
- No real company or person names anywhere. Customers and suppliers are codes (`CUST_001`, `SUPP_01`).
  Fictional display names live only in the encrypted vault (section 1A.3).
- Every table write is audit-logged by a database trigger, not by application code.
- The forecasting system must never be able to read the "hidden truth" of a scenario or its future
  actuals. Those live in a separate schema readable only by the evaluator role.
- All monetary amounts in EUR, stored as `NUMERIC(14,2)`. Dates as `DATE`, timestamps as `TIMESTAMPTZ`.

## 1. The fictional company

| Parameter | Value | Note |
|---|---|---|
| Name | "DemoCo Building Supplies S.à r.l." (fictional) | Only in the vault |
| Activity | Wholesale distribution of building and installation materials | NACE G46.73 / G46.74 |
| Employees | 90 | |
| Net revenue | ~€25.0m / year | EU average for medium enterprises ~€26m (Eurostat SBS 2023) |
| Gross margin | 30% | Purchases (COGS) ~€17.5m |
| Payroll, total cost | €5.6m / year | Net salaries ~€290k paid last working day; social + withholding ~€177k paid on the 15th of the following month |
| Rent | €35k / month | Paid on the 1st |
| Other fixed opex | €50k / month | Energy, vehicles, IT, insurance; paid on the 5th |
| VAT | 17% on sales and purchases | Monthly return; net VAT paid on the 15th of the following month |
| Corporate tax advances | Quarterly, €40k each | Paid 10 Mar / 10 Jun / 10 Sep / 10 Dec |
| Profit on paper | ~€0.45–0.5m net / year | Must be positive in every scenario |
| Revolving credit facility | €1.0m, undrawn | Available as a CFO action later |
| Safety threshold | 4 × weekly fixed cash costs (~€510k) | `SAFETY_WEEKS` in config |

All values above are parameters in `config/company.yaml`, not constants in code.

### Timeline

- **As-of date**: Monday 2026-09-28.
- **History**: 52 weeks, 2025-09-29 → 2026-09-27 (Mondays as week start).
- **Forecast horizon**: 13 weeks, 2026-09-28 → 2026-12-27 (includes December).
- **Future actuals**: the generator also simulates what really happens in the 13 horizon weeks.
  These are stored in `eval.*` only, to measure forecast error in Phase 5.
- The opening bank balance at the start of history is **solved by the generator** so that the
  as-of balance lands on a target (default €1.2m, per-scenario override allowed).

## 2. Customers (237)

### Segments

| Segment | NACE | Share of customers | Payment terms (days) |
|---|---|---|---|
| General contractors | F41 | 25% | 60 |
| Specialised installers (plumbing, electrical, HVAC) | F43 | 40% | 45 |
| Property developers / renovation | L68 / F41 | 10% | 60 |
| Public entities (communes, public bodies) | O84 | 10% | 30 |
| Retail / DIY and other | G47 | 15% | 30 |

### Size distribution

- Annual revenue per customer drawn from a log-normal; the generator tunes sigma so that the
  **top 20 customers = 57–63% of revenue** and the largest single customer = 6–9%.
- Ordering frequency by size: large weekly, medium bi-weekly, small monthly.
  Invoice amount = customer annual revenue / invoices per year, with ±25% noise.
- Expected total: ~2,000 customer invoices per year.

### Payment behaviour archetypes

Each customer gets one archetype. The delay (days after due date, can be negative for early
payment) is drawn per invoice from a normal distribution, floored at -10.

| Archetype | Share | Mean delay (days) | SD (days) |
|---|---|---|---|
| Punctual | 30% | 2 | 3 |
| Normal | 40% | 8 | 6 |
| Slow | 20% | 20 | 10 |
| Chronic late | 10% | 35 | 15 |

Modifiers applied on top:

- **Sector stress** (from STATEC, section 1B): `delay × (1 + beta × (stress_index − 1))`, beta = 0.5.
- **Seasonality**: construction collective leave (last week of July + first 2 weeks of August) adds
  +10 days to receipts due in that window; year-end (20 Dec – 5 Jan) adds +7 days.
- **Public entities** are never chronic late but may pay in batches (month end).

## 3. Suppliers (25)

- One **major supplier** (`SUPP_01`) = ~35% of purchases, terms 60 days.
- Four mid suppliers = ~35% combined, terms 45 days.
- Twenty small suppliers = ~30% combined, terms 30 days.
- The company pays suppliers **on the due date** (it is disciplined); a parameter allows early
  payment for a 2% discount on selected suppliers (off by default).

## 4. The 8 scenarios

Each scenario is a **config overlay** on the base dataset, generated with its own seed.
Every transactional row carries `dataset_id` (e.g. `S2_big_customer`).
For every scenario the generator writes its **hidden truth** to `eval.scenario_truth` and the
**future actuals** of the 13 horizon weeks to `eval.future_*`.

| ID | Name | What the generator plants | Hidden truth recorded | Acceptance check |
|---|---|---|---|---|
| S1 | Normal | Base behaviour only | "no shortfall" | Actual balance ≥ threshold in all 13 weeks |
| S2 | Big customer deteriorating | A top-3 customer (6–9% of revenue) drifts from +10 to +45 days delay over the last 4 months; €900k of its invoices fall due in weeks 4–6. Major supplier bill of €1.4m due in week 6 | Customer code, drift start, shortfall week | Actual balance < threshold in at least one of weeks 6–9; contractual (on-time) projection stays above threshold |
| S3 | Sector crisis | ALL F41+F43 customers except the top-5 globally by revenue (≈55–60 customers) receive +30–50 extra days delay (multiplied by STATEC construction stress index ≈1.16) from 3 months before as-of; 2 of the smallest affected customers go bankrupt during the horizon (no further payments) | List of affected codes, excluded top-5, bankrupt codes, shock start | No single affected customer > 20% of cohort AR; actual balance dips below threshold in at least one of weeks 7–11 |
| S4 | Outflow spike | Extraordinary major-supplier bill (€1.1m net) + moved tax advance (€40k) fall in horizon week 7; week 8 has natural inflow surplus that restores the balance above threshold | Spike week (7) and components | Actual balance < threshold in week 7; recovers to ≥ threshold by week 8 |
| S5 | Seasonality | History shows August and December slowdowns; horizon includes December | Seasonal factors used | December receipts ≥ 15% below November; no shortfall unless combined |
| S6 | New customer, no history | A new F43 customer onboarded 6 weeks before as-of, 2 invoices (€150k total) due in horizon, no payment history. Its true archetype is "slow" | True archetype | Its future payments arrive ≥ 15 days late |
| S7 | Partial payments | 3 customers pay 50–70% of an invoice on time and the rest 3–6 weeks later | Codes and split rules | Partial rows exist and sum to invoice amount |
| S8 | Month-end close | The accountant (fiduciaire) closes each month 15–20 days late; the September close (booked ~18 Oct) cancels one €60k invoice and adds €25k of credit notes; one bank fee batch is recognised late | Adjustments list | `month_closes` and `close_adjustments` populated; booked revenue differs from invoiced by the adjustments |

## 1A. Database schema, roles, vault, audit

Implement as ordered SQL migrations in `migrations/` (plain `.sql` files, applied by a small
`scripts/migrate.py` that records applied files in `hm.schema_migrations`).

### Schemas

- `hm` — operational data the system reads and writes.
- `vault` — encrypted identity map. Readable only by `hm_admin`.
- `eval` — hidden truth and future actuals. Readable only by `hm_evaluator`.
- `audit` — audit log. Insert via trigger only; readable by `hm_admin` and `hm_approver`.

### Tables in `hm`

| Table | Purpose / key columns |
|---|---|
| `datasets` | `dataset_id` PK, description, seed, as_of_date, created_at |
| `company_params` | dataset_id, key, value JSONB |
| `bank_accounts` | account_code (e.g. `ACC_MAIN`), currency, dataset_id |
| `bank_balances` | dataset_id, account_code, date, closing_balance |
| `bank_transactions` | dataset_id, txn_id, account_code, date, amount (+ in / − out), category, ref_type, ref_id |
| `counterparties` | dataset_id, code (`CUST_###` / `SUPP_##`), kind, nace, segment, size_band, payment_terms_days, onboarded_on. **No names** |
| `ar_invoices` | dataset_id, invoice_id, cust_code, issue_date, due_date, amount_net, vat, amount_gross, status |
| `ar_receipts` | dataset_id, receipt_id, invoice_id, date, amount |
| `ap_invoices` | same shape for suppliers |
| `ap_payments` | same shape for supplier payments |
| `recurring_outflows` | dataset_id, kind (payroll_net, payroll_social, rent, opex, vat, tax_advance), rule (JSONB), amount |
| `credit_facilities` | dataset_id, facility_code, limit, drawn, rate_ref |
| `month_closes` | dataset_id, month, close_booked_on, revenue_booked, cogs, opex, profit |
| `close_adjustments` | dataset_id, month, kind, ref_id, amount, note |
| `parameters` | key, value JSONB, version, valid_from, proposed_by, approved_by, status — versioned, never updated in place |
| `approvals` | approval_id, subject_type, subject_id, decision, decided_by, decided_at, comment |
| `forecast_runs`, `forecast_lines` | created now, filled from Phase 2 (run_id, week_start, scenario, p10, p50, p90, components JSONB) |
| `public_series` | source, series_id, period, value, unit, fetched_at, source_url |

### Vault

- Extension `pgcrypto`.
- `vault.identity_map(code, display_name_enc BYTEA, iban_enc BYTEA)`, encrypted with
  `pgp_sym_encrypt` using the key in `.env` → `HM_VAULT_KEY` (never in code, never in git).
- Display names are **fictional** and generated from neutral word lists
  ("Nordwerk Bau", "Atelier Delta"…), never real company names.

### Roles

| Role | Can |
|---|---|
| `hm_reader` | SELECT on `hm` |
| `hm_analyst` | reader + INSERT on `forecast_runs`, `forecast_lines`, proposals in `parameters` |
| `hm_approver` | analyst + INSERT on `approvals`, approve `parameters`; SELECT on `audit` |
| `hm_evaluator` | SELECT on `eval` and `hm` |
| `hm_admin` | everything, including `vault` |

The application connects as `hm_analyst`. The generator connects as `hm_admin`.
Passwords come from `.env`.

### Audit

- `audit.log(id, ts, db_user, table_name, op, row_pk JSONB, old_row JSONB, new_row JSONB)`.
- One generic trigger function attached to every `hm` table (INSERT, UPDATE, DELETE).
- For bulk generator loads, the audit trigger records one summary row per table and batch
  (`op = 'BULK_LOAD'`, row count) instead of one row per inserted row, to keep the log readable.

### Tests for 1A

- Migrations apply on an empty DB and are idempotent (second run = no changes).
- `hm_analyst` gets "permission denied" on `vault.*`, `eval.*` and `audit.*`.
- An UPDATE on any `hm` table creates an audit row with old and new values.
- `parameters` rejects UPDATE (only INSERT of a new version).

## 1B. Public data

Store raw downloads in `data/public/raw/` and normalised rows in `hm.public_series`.
Every row keeps its `source_url` and `fetched_at`. Script: `ingestion/public_data.py`.

| Series | Source | Use |
|---|---|---|
| Bankruptcies by NACE section, annual (and quarterly if available) | STATEC via LUSTAT / data.public.lu dataset "Démographie des entreprises" (CC0) | Sector stress index |
| ECB deposit facility rate | ECB Data Portal API (series FM, deposit facility rate; verify key on data.ecb.europa.eu) | Reference rate for excess-cash suggestions |
| 3-month Euribor (optional) | ECB Data Portal API | Cost reference for the credit facility |

Rules:

- First try the official APIs (LUSTAT SDMX, ECB SDMX REST). If LUSTAT cannot be reached
  programmatically, fall back to `data/public/manual/statec_bankruptcies.csv`, filled by hand from
  STATEC publications, with a `source_url` per row. Do not invent values.
- Figures already verified from STATEC publications (use to test the fallback):
  2025 total bankruptcies 1,187; construction 165 in 2025 vs 197 in 2024.
- **Sector stress index** = sector bankruptcies in the latest year / sector average of the previous
  5 available years. 1.0 = normal. Stored per NACE section in `hm.public_series`
  (`series_id = 'stress_index_<NACE>'`).
- The generator reads the stress index; if missing, it uses 1.0 and logs a warning.

## 1C. Generator

Package `ingestion/generator/`, entry point `python -m ingestion.generator --all` (or `--dataset S2`).

Steps per dataset:

1. Build counterparties (237 customers, 25 suppliers) with segments, archetypes, sizes.
2. Simulate 52 weeks of history + 13 weeks of future day by day: invoices, due dates, receipts
   (with archetype + modifiers + scenario overlay), supplier invoices and payments, recurring outflows.
3. Solve the opening balance so that the as-of balance = target.
4. Build month closes (with S8 adjustments where relevant).
5. Write history to `hm.*`, future actuals and hidden truth to `eval.*`.
6. Export CSVs to `data/synthetic/<dataset_id>/` with a README stating "SYNTHETIC DATA".
7. Run the acceptance checks of section 4 and write `data/synthetic/<dataset_id>/checks.json`.

Global tests (`tests/test_generator.py`):

- Same seed → identical output (hash of the CSVs).
- Revenue within €24–26m; top-20 share 57–63%; largest customer 6–9%.
- Profit on paper positive in every dataset.
- No string resembling a company name in any `hm` table (only codes).
- All 8 scenario acceptance checks pass.

## 5. Data protection (docs/data_protection.md)

A one-page document covering:

- **What is collected**: bank balances and transactions, invoices, payment dates, sector codes.
  No personal data about individuals; counterparty names only in the encrypted vault.
- **Why**: forecasting cash and explaining shortfalls (purpose limitation).
- **Minimisation**: codes instead of names; no contact details; IBANs only in the vault.
- **Security**: role separation, encryption at rest for the vault, audit log, secrets in `.env`.
- **Retention**: transactional data 24 months rolling (parameter), audit log 10 years (aligned with
  accounting record retention, to confirm with legal).
- **LLM use**: only aggregated, pseudonymised JSON leaves the engine; with `LLM_PROVIDER=local`
  nothing leaves the machine; with `haiku` only pseudonymised aggregates are sent.
- **References**: GDPR, CNPD (Luxembourg data protection authority).
- **Demo note**: all data in this repository is synthetic.

## 6. Definition of done for Phase 1

- [ ] 1A migrations, roles, vault, audit + tests green
- [ ] 1B public data fetched (or manual fallback with sources) + stress index computed
- [ ] 1C generator produces the 8 datasets, all acceptance checks pass, tests green
- [ ] `docs/data_protection.md` written
- [ ] Commit + push after each step
