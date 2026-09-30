-- 005: eval schema — hidden truth and future actuals, readable only by hm_evaluator
-- The forecasting system (hm_analyst) must never read these tables.

-- Hidden truth per scenario: what the generator planted and what acceptance checks verify
CREATE TABLE IF NOT EXISTS eval.scenario_truth (
    dataset_id TEXT        PRIMARY KEY,
    truth      JSONB       NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Future bank balances for the 13 horizon weeks (ground truth for forecast error in Phase 5)
CREATE TABLE IF NOT EXISTS eval.future_bank_balances (
    dataset_id      TEXT          NOT NULL,
    account_code    TEXT          NOT NULL,
    week_start      DATE          NOT NULL,
    closing_balance NUMERIC(14,2) NOT NULL,
    PRIMARY KEY (dataset_id, account_code, week_start)
);

-- Future AR receipts for the 13 horizon weeks
CREATE TABLE IF NOT EXISTS eval.future_ar_receipts (
    dataset_id TEXT          NOT NULL,
    receipt_id TEXT          NOT NULL,
    invoice_id TEXT          NOT NULL,
    date       DATE          NOT NULL,
    amount     NUMERIC(14,2) NOT NULL,
    PRIMARY KEY (dataset_id, receipt_id)
);

-- Future AP payments for the 13 horizon weeks
CREATE TABLE IF NOT EXISTS eval.future_ap_payments (
    dataset_id TEXT          NOT NULL,
    payment_id TEXT          NOT NULL,
    invoice_id TEXT          NOT NULL,
    date       DATE          NOT NULL,
    amount     NUMERIC(14,2) NOT NULL,
    PRIMARY KEY (dataset_id, payment_id)
);
