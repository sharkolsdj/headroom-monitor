# Data Protection — HeadRoom Monitor

**Version:** 1.0 · **Date:** 2026-09-30 · **Owner:** Daniele

> **Demo note:** All data in this repository is synthetic and computer-generated. It does not
> represent any real company, person, or financial transaction.

---

## 1. What is collected

HeadRoom Monitor processes the following categories of information:

| Category | Examples | Sensitivity |
|---|---|---|
| Bank balances and transactions | Account balance, payment in/out, date, amount | Business-confidential |
| AR/AP invoices | Issue date, due date, net amount, VAT, gross amount | Business-confidential |
| Payment dates and delays | Receipt date, days overdue | Business-confidential |
| Counterparty codes | `CUST_001`, `SUPP_01` — pseudonymised codes only | Low |
| Sector codes | NACE codes (e.g. F41, G46.73) | Public |
| Public statistics | ECB rates, STATEC bankruptcy counts by sector | Public |

**What is NOT collected:** Individual names, contact details, home addresses, personal financial
data, or any data that directly identifies a natural person.

---

## 2. Purpose and legal basis

**Purpose:** Cash-flow forecasting and liquidity early-warning for the operating company.
Specifically:
- Producing a rolling 13-week cash forecast.
- Identifying weeks where the projected balance falls below the safety threshold.
- Drafting narrative alerts for review by a human approver.

**Principle:** Purpose limitation applies — data ingested for cash forecasting must not be used
for credit scoring, marketing, or any purpose other than the one above.

---

## 3. Data minimisation

| Measure | Implementation |
|---|---|
| Pseudonymisation | Customers and suppliers are identified only by codes (`CUST_###`, `SUPP_##`). |
| No contact data | No email, phone, or postal address is stored in the operational database. |
| No personal identifiers | No individual names, dates of birth, or national ID numbers. |
| IBAN isolation | IBANs are stored only in the encrypted vault (`vault.identity_map`), not in operational tables. |
| Display names in vault only | Company names (encrypted) live in `vault.identity_map`; the forecasting engine never reads them. |

---

## 4. Security measures

| Measure | Detail |
|---|---|
| Role-based access control | Five database roles (`hm_reader`, `hm_analyst`, `hm_approver`, `hm_evaluator`, `hm_admin`) with least-privilege grants. |
| Encryption at rest | Vault entries (`display_name_enc`, `iban_enc`) encrypted with `pgp_sym_encrypt` using a key held only in `.env`. |
| Secrets in `.env` | Database passwords, vault key, and API keys are never committed to git. |
| Audit log | Every INSERT/UPDATE/DELETE on `hm.*` tables is recorded in `audit.log` with timestamp, actor role, and row values. |
| Human approval gate | No forecasting recommendation or proposed action is surfaced without passing through `gate/` and receiving explicit human confirmation. |
| No LLM arithmetic | LLMs are used only for narrative generation, never for cash calculations. All arithmetic runs deterministically in `engine/`. |
| Local-first LLM option | With `LLM_PROVIDER=local`, all data stays on the machine (Ollama). With `LLM_PROVIDER=haiku`, only pseudonymised, aggregated JSON is sent to Anthropic. |

---

## 5. Data retention

| Data type | Retention | Basis |
|---|---|---|
| Transactional data (invoices, receipts, payments, balances) | 24 months rolling | Operational necessity; configurable parameter |
| Audit log (`audit.log`) | 10 years | Aligned with Luxembourg accounting record retention (Art. 25 loi du 19 décembre 2002) — to be confirmed with legal counsel |
| Public statistics (`hm.public_series`) | Indefinite | Public domain, no personal data |
| Vault entries (`vault.identity_map`) | Same as counterparty lifetime | Deleted when counterparty is archived |

---

## 6. LLM data flows

When the system generates narrative alerts or explanations, the data sent to any LLM is:
- Aggregated weekly cash totals (not individual transaction lines)
- Pseudonymised codes (not company names or IBANs)
- Computed metrics (balance, variance, threshold)

With `LLM_PROVIDER=local` (Ollama), no data leaves the machine.  
With `LLM_PROVIDER=haiku` (Anthropic Claude), pseudonymised aggregates are sent over HTTPS.  
Neither mode sends vault content, individual invoice details, or IBAN data.

---

## 7. References

- **GDPR** (Regulation (EU) 2016/679), Articles 5, 25, 32 (purpose limitation, data minimisation, security).
- **CNPD** — Commission nationale pour la protection des données (Luxembourg data protection authority): [cnpd.public.lu](https://cnpd.public.lu)
- **Luxembourg accounting retention**: Loi du 19 décembre 2002, Art. 25 — 10-year retention for accounting records.
