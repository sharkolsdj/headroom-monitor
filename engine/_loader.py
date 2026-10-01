"""Load data from hm.* as hm_analyst (no access to eval.*)."""
from __future__ import annotations

from datetime import date
from typing import Any

import sqlalchemy as sa
from sqlalchemy import text


def load_dataset(engine: sa.Engine, dataset_id: str) -> dict[str, Any]:
    """
    Return all hm.* data for a dataset needed by the engine.
    Connects as hm_analyst — no eval.* tables accessible.
    """
    with engine.connect() as conn:
        # ── Dataset metadata ──────────────────────────────────────────────────
        ds = conn.execute(text("""
            SELECT dataset_id, as_of_date, seed
            FROM hm.datasets WHERE dataset_id = :did
        """), {"did": dataset_id}).fetchone()
        if ds is None:
            raise ValueError(f"Dataset '{dataset_id}' not found in hm.datasets")

        as_of: date = ds.as_of_date

        # ── Opening balance (bank balance at end of week before as_of) ────────
        opening_bal_row = conn.execute(text("""
            SELECT closing_balance
            FROM hm.bank_balances
            WHERE dataset_id = :did
              AND date = :aod_sunday
            LIMIT 1
        """), {"did": dataset_id, "aod_sunday": as_of - __import__("datetime").timedelta(days=1)}).fetchone()
        opening_balance = float(opening_bal_row.closing_balance) if opening_bal_row else 0.0

        # ── Open AR (issued ≤ as_of, not fully paid) ──────────────────────────
        open_ar_rows = conn.execute(text("""
            SELECT
                i.invoice_id, i.cust_code, i.due_date,
                i.amount_gross,
                i.amount_gross - COALESCE(SUM(r.amount), 0.0) AS outstanding_amount,
                c.segment
            FROM hm.ar_invoices i
            JOIN hm.counterparties c
                ON c.code = i.cust_code AND c.dataset_id = i.dataset_id
            LEFT JOIN hm.ar_receipts r
                ON r.invoice_id = i.invoice_id AND r.dataset_id = i.dataset_id
            WHERE i.dataset_id = :did
              AND i.issue_date <= :as_of
            GROUP BY i.invoice_id, i.cust_code, i.due_date, i.amount_gross, c.segment
            HAVING i.amount_gross - COALESCE(SUM(r.amount), 0.0) > 0.005
        """), {"did": dataset_id, "as_of": as_of}).fetchall()
        open_ar = [dict(row._mapping) for row in open_ar_rows]

        # ── Open AP (issued ≤ as_of, not fully paid) ──────────────────────────
        open_ap_rows = conn.execute(text("""
            SELECT
                i.invoice_id, i.supp_code, i.due_date,
                i.amount_gross,
                i.amount_gross - COALESCE(SUM(p.amount), 0.0) AS outstanding_amount
            FROM hm.ap_invoices i
            LEFT JOIN hm.ap_payments p
                ON p.invoice_id = i.invoice_id AND p.dataset_id = i.dataset_id
            WHERE i.dataset_id = :did
              AND i.issue_date <= :as_of
            GROUP BY i.invoice_id, i.supp_code, i.due_date, i.amount_gross
            HAVING i.amount_gross - COALESCE(SUM(p.amount), 0.0) > 0.005
        """), {"did": dataset_id, "as_of": as_of}).fetchall()
        open_ap = [dict(row._mapping) for row in open_ap_rows]

        # ── History AR (for SimpleBehaviour and R2 seasonal factors) ─────────
        history_ar_rows = conn.execute(text("""
            SELECT i.invoice_id, i.cust_code, i.issue_date, i.due_date,
                   i.amount_net, i.amount_gross, i.vat, c.segment
            FROM hm.ar_invoices i
            JOIN hm.counterparties c
                ON c.code = i.cust_code AND c.dataset_id = i.dataset_id
            WHERE i.dataset_id = :did
              AND i.issue_date < :as_of
        """), {"did": dataset_id, "as_of": as_of}).fetchall()
        history_ar = [dict(row._mapping) for row in history_ar_rows]

        # ── History AP (for P5 VAT) ───────────────────────────────────────────
        history_ap_rows = conn.execute(text("""
            SELECT invoice_id, supp_code, issue_date, due_date,
                   amount_net, amount_gross, vat
            FROM hm.ap_invoices
            WHERE dataset_id = :did
              AND issue_date < :as_of
        """), {"did": dataset_id, "as_of": as_of}).fetchall()
        history_ap = [dict(row._mapping) for row in history_ap_rows]

        # ── Recurring outflows ────────────────────────────────────────────────
        recur_rows = conn.execute(text("""
            SELECT kind, rule, amount
            FROM hm.recurring_outflows
            WHERE dataset_id = :did
        """), {"did": dataset_id}).fetchall()
        recurring = [{"kind": r.kind, "rule": r.rule, "amount": float(r.amount)}
                     for r in recur_rows]

        # ── Segments (for R2 and P2) ──────────────────────────────────────────
        seg_rows = conn.execute(text("""
            SELECT DISTINCT segment, payment_terms_days
            FROM hm.counterparties
            WHERE dataset_id = :did AND kind = 'customer'
        """), {"did": dataset_id}).fetchall()
        segments = [{"code": r.segment, "payment_terms_days": r.payment_terms_days}
                    for r in seg_rows]

        # ── History start date ────────────────────────────────────────────────
        hist_start_row = conn.execute(text("""
            SELECT MIN(issue_date) FROM hm.ar_invoices WHERE dataset_id = :did
        """), {"did": dataset_id}).fetchone()
        history_start = hist_start_row[0] if hist_start_row and hist_start_row[0] else as_of

    return {
        "dataset_id": dataset_id,
        "as_of": as_of,
        "opening_balance": opening_balance,
        "open_ar": open_ar,
        "open_ap": open_ap,
        "history_ar": history_ar,
        "history_ap": history_ap,
        "recurring": recurring,
        "segments": segments,
        "history_start": history_start,
    }


def analyst_engine(settings) -> sa.Engine:
    """Return a SQLAlchemy engine connecting as hm_analyst."""
    return sa.create_engine(settings.role_dsn("hm_analyst"), pool_pre_ping=True)
