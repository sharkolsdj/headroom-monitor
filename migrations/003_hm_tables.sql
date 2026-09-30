-- 003: all tables in the hm schema

-- Reference dataset for every generated scenario
CREATE TABLE IF NOT EXISTS hm.datasets (
    dataset_id   TEXT PRIMARY KEY,
    description  TEXT,
    seed         INTEGER        NOT NULL,
    as_of_date   DATE           NOT NULL,
    created_at   TIMESTAMPTZ    NOT NULL DEFAULT NOW()
);

-- Per-dataset copy of company parameters (key/value, value is JSONB)
CREATE TABLE IF NOT EXISTS hm.company_params (
    dataset_id TEXT NOT NULL REFERENCES hm.datasets(dataset_id) ON DELETE CASCADE,
    key        TEXT NOT NULL,
    value      JSONB NOT NULL,
    PRIMARY KEY (dataset_id, key)
);

CREATE TABLE IF NOT EXISTS hm.bank_accounts (
    dataset_id   TEXT NOT NULL REFERENCES hm.datasets(dataset_id) ON DELETE CASCADE,
    account_code TEXT NOT NULL,
    currency     TEXT NOT NULL DEFAULT 'EUR',
    PRIMARY KEY (dataset_id, account_code)
);

CREATE TABLE IF NOT EXISTS hm.bank_balances (
    dataset_id       TEXT          NOT NULL REFERENCES hm.datasets(dataset_id) ON DELETE CASCADE,
    account_code     TEXT          NOT NULL,
    date             DATE          NOT NULL,
    closing_balance  NUMERIC(14,2) NOT NULL,
    PRIMARY KEY (dataset_id, account_code, date)
);

-- amount: positive = inflow, negative = outflow
CREATE TABLE IF NOT EXISTS hm.bank_transactions (
    dataset_id   TEXT          NOT NULL REFERENCES hm.datasets(dataset_id) ON DELETE CASCADE,
    txn_id       TEXT          NOT NULL,
    account_code TEXT          NOT NULL,
    date         DATE          NOT NULL,
    amount       NUMERIC(14,2) NOT NULL,
    category     TEXT,
    ref_type     TEXT,
    ref_id       TEXT,
    PRIMARY KEY (dataset_id, txn_id)
);

-- No display names; names live only in vault.identity_map
CREATE TABLE IF NOT EXISTS hm.counterparties (
    dataset_id         TEXT    NOT NULL REFERENCES hm.datasets(dataset_id) ON DELETE CASCADE,
    code               TEXT    NOT NULL,
    kind               TEXT    NOT NULL CHECK (kind IN ('customer', 'supplier')),
    nace               TEXT,
    segment            TEXT,
    size_band          TEXT,
    payment_terms_days INTEGER,
    onboarded_on       DATE,
    PRIMARY KEY (dataset_id, code)
);

CREATE TABLE IF NOT EXISTS hm.ar_invoices (
    dataset_id    TEXT          NOT NULL REFERENCES hm.datasets(dataset_id) ON DELETE CASCADE,
    invoice_id    TEXT          NOT NULL,
    cust_code     TEXT          NOT NULL,
    issue_date    DATE          NOT NULL,
    due_date      DATE          NOT NULL,
    amount_net    NUMERIC(14,2) NOT NULL,
    vat           NUMERIC(14,2) NOT NULL,
    amount_gross  NUMERIC(14,2) NOT NULL,
    status        TEXT          NOT NULL DEFAULT 'open',
    PRIMARY KEY (dataset_id, invoice_id)
);

CREATE TABLE IF NOT EXISTS hm.ar_receipts (
    dataset_id TEXT          NOT NULL REFERENCES hm.datasets(dataset_id) ON DELETE CASCADE,
    receipt_id TEXT          NOT NULL,
    invoice_id TEXT          NOT NULL,
    date       DATE          NOT NULL,
    amount     NUMERIC(14,2) NOT NULL,
    PRIMARY KEY (dataset_id, receipt_id)
);

CREATE TABLE IF NOT EXISTS hm.ap_invoices (
    dataset_id   TEXT          NOT NULL REFERENCES hm.datasets(dataset_id) ON DELETE CASCADE,
    invoice_id   TEXT          NOT NULL,
    supp_code    TEXT          NOT NULL,
    issue_date   DATE          NOT NULL,
    due_date     DATE          NOT NULL,
    amount_net   NUMERIC(14,2) NOT NULL,
    vat          NUMERIC(14,2) NOT NULL,
    amount_gross NUMERIC(14,2) NOT NULL,
    status       TEXT          NOT NULL DEFAULT 'open',
    PRIMARY KEY (dataset_id, invoice_id)
);

CREATE TABLE IF NOT EXISTS hm.ap_payments (
    dataset_id TEXT          NOT NULL REFERENCES hm.datasets(dataset_id) ON DELETE CASCADE,
    payment_id TEXT          NOT NULL,
    invoice_id TEXT          NOT NULL,
    date       DATE          NOT NULL,
    amount     NUMERIC(14,2) NOT NULL,
    PRIMARY KEY (dataset_id, payment_id)
);

-- rule JSONB encodes the scheduling rule, e.g. {"day_of_month": 1} for rent
CREATE TABLE IF NOT EXISTS hm.recurring_outflows (
    id         BIGSERIAL     PRIMARY KEY,
    dataset_id TEXT          NOT NULL REFERENCES hm.datasets(dataset_id) ON DELETE CASCADE,
    kind       TEXT          NOT NULL,
    rule       JSONB         NOT NULL,
    amount     NUMERIC(14,2) NOT NULL
);

-- "limit" is a reserved word; use limit_amount
CREATE TABLE IF NOT EXISTS hm.credit_facilities (
    dataset_id    TEXT          NOT NULL REFERENCES hm.datasets(dataset_id) ON DELETE CASCADE,
    facility_code TEXT          NOT NULL,
    limit_amount  NUMERIC(14,2) NOT NULL,
    drawn         NUMERIC(14,2) NOT NULL DEFAULT 0,
    rate_ref      TEXT,
    PRIMARY KEY (dataset_id, facility_code)
);

-- month stored as the first day of that month
CREATE TABLE IF NOT EXISTS hm.month_closes (
    dataset_id      TEXT          NOT NULL REFERENCES hm.datasets(dataset_id) ON DELETE CASCADE,
    month           DATE          NOT NULL,
    close_booked_on DATE,
    revenue_booked  NUMERIC(14,2),
    cogs            NUMERIC(14,2),
    opex            NUMERIC(14,2),
    profit          NUMERIC(14,2),
    PRIMARY KEY (dataset_id, month)
);

CREATE TABLE IF NOT EXISTS hm.close_adjustments (
    adj_id     BIGSERIAL     PRIMARY KEY,
    dataset_id TEXT          NOT NULL REFERENCES hm.datasets(dataset_id) ON DELETE CASCADE,
    month      DATE          NOT NULL,
    kind       TEXT          NOT NULL,
    ref_id     TEXT,
    amount     NUMERIC(14,2) NOT NULL,
    note       TEXT
);

-- Append-only versioned parameters; UPDATE is blocked by trigger in 006
CREATE TABLE IF NOT EXISTS hm.parameters (
    key         TEXT        NOT NULL,
    value       JSONB       NOT NULL,
    version     INTEGER     NOT NULL DEFAULT 1,
    valid_from  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    proposed_by TEXT,
    approved_by TEXT,
    status      TEXT        NOT NULL DEFAULT 'proposed',
    PRIMARY KEY (key, version)
);

CREATE TABLE IF NOT EXISTS hm.approvals (
    approval_id  BIGSERIAL   PRIMARY KEY,
    subject_type TEXT        NOT NULL,
    subject_id   TEXT        NOT NULL,
    decision     TEXT        NOT NULL,
    decided_by   TEXT        NOT NULL,
    decided_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    comment      TEXT
);

CREATE TABLE IF NOT EXISTS hm.forecast_runs (
    run_id     BIGSERIAL   PRIMARY KEY,
    dataset_id TEXT        NOT NULL REFERENCES hm.datasets(dataset_id) ON DELETE CASCADE,
    scenario   TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS hm.forecast_lines (
    id         BIGSERIAL     PRIMARY KEY,
    run_id     BIGINT        NOT NULL REFERENCES hm.forecast_runs(run_id) ON DELETE CASCADE,
    week_start DATE          NOT NULL,
    p10        NUMERIC(14,2),
    p50        NUMERIC(14,2),
    p90        NUMERIC(14,2),
    components JSONB
);

-- Normalised public statistics (ECB rates, STATEC bankruptcies, stress indices)
CREATE TABLE IF NOT EXISTS hm.public_series (
    id         BIGSERIAL   PRIMARY KEY,
    source     TEXT        NOT NULL,
    series_id  TEXT        NOT NULL,
    period     TEXT        NOT NULL,
    value      NUMERIC     NOT NULL,
    unit       TEXT,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source_url TEXT,
    UNIQUE (source, series_id, period)
);
