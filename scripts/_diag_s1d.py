"""
Diagnostic: find the bias source in SimpleBehaviour for S1_normal.
Checks how many invoices qualify, and whether future receipts are included.
"""
import sys
from pathlib import Path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import sqlalchemy as sa
from sqlalchemy import text
from engine._behaviour import SimpleBehaviour
from engine._loader import load_dataset
from config import settings
from datetime import timedelta

eng_admin  = sa.create_engine(settings.postgres_dsn, pool_pre_ping=True)
eng_analyst = sa.create_engine(settings.role_dsn("hm_analyst"), pool_pre_ping=True)

data = load_dataset(eng_analyst, "S1_normal")
as_of      = data["as_of"]
hist_start = as_of - timedelta(days=365)

print(f"as_of={as_of}  hist_start={hist_start}")

with eng_admin.connect() as c:
    # Total qualifying invoices under SimpleBehaviour's query
    n_qual = c.execute(text("""
        SELECT COUNT(*) FROM (
            SELECT i.invoice_id
            FROM hm.ar_invoices i
            JOIN hm.counterparties cp ON cp.code=i.cust_code AND cp.dataset_id=i.dataset_id
            LEFT JOIN hm.ar_receipts r ON r.invoice_id=i.invoice_id AND r.dataset_id=i.dataset_id
            WHERE i.dataset_id='S1_normal'
              AND i.issue_date >= :hist AND i.issue_date <= :as_of
            GROUP BY i.invoice_id, i.cust_code, i.due_date, cp.segment, i.amount_gross
            HAVING COALESCE(SUM(r.amount), 0) >= i.amount_gross * 0.99
        ) sub
    """), {"hist": hist_start, "as_of": as_of}).scalar()
    print(f"Invoices qualifying (HAVING paid>=99%): {n_qual}")

    # How many of those have max(r.date) > as_of?  (future receipts)
    n_future = c.execute(text("""
        SELECT COUNT(*) FROM (
            SELECT i.invoice_id, MAX(r.date) AS last_receipt
            FROM hm.ar_invoices i
            JOIN hm.counterparties cp ON cp.code=i.cust_code AND cp.dataset_id=i.dataset_id
            LEFT JOIN hm.ar_receipts r ON r.invoice_id=i.invoice_id AND r.dataset_id=i.dataset_id
            WHERE i.dataset_id='S1_normal'
              AND i.issue_date >= :hist AND i.issue_date <= :as_of
            GROUP BY i.invoice_id, i.cust_code, i.due_date, cp.segment, i.amount_gross
            HAVING COALESCE(SUM(r.amount), 0) >= i.amount_gross * 0.99
        ) sub WHERE last_receipt > :as_of
    """), {"hist": hist_start, "as_of": as_of}).scalar()
    print(f"  Of which receipt_date > as_of (FUTURE receipts included in training): {n_future}")

    n_past = c.execute(text("""
        SELECT COUNT(*) FROM (
            SELECT i.invoice_id, MAX(r.date) AS last_receipt
            FROM hm.ar_invoices i
            JOIN hm.counterparties cp ON cp.code=i.cust_code AND cp.dataset_id=i.dataset_id
            LEFT JOIN hm.ar_receipts r ON r.invoice_id=i.invoice_id AND r.dataset_id=i.dataset_id
            WHERE i.dataset_id='S1_normal'
              AND i.issue_date >= :hist AND i.issue_date <= :as_of
            GROUP BY i.invoice_id, i.cust_code, i.due_date, cp.segment, i.amount_gross
            HAVING COALESCE(SUM(r.amount), 0) >= i.amount_gross * 0.99
        ) sub WHERE last_receipt <= :as_of
    """), {"hist": hist_start, "as_of": as_of}).scalar()
    print(f"  Of which receipt_date <= as_of (truly historical): {n_past}")

    # Mean delay with vs without future receipts
    mean_with = c.execute(text("""
        SELECT AVG((MAX(r.date) - i.due_date)) FROM (
            SELECT i.invoice_id, i.due_date
            FROM hm.ar_invoices i
            LEFT JOIN hm.ar_receipts r ON r.invoice_id=i.invoice_id AND r.dataset_id=i.dataset_id
            WHERE i.dataset_id='S1_normal'
              AND i.issue_date >= :hist AND i.issue_date <= :as_of
            GROUP BY i.invoice_id, i.due_date, i.amount_gross
            HAVING COALESCE(SUM(r.amount), 0) >= i.amount_gross * 0.99
        ) sub
        JOIN hm.ar_receipts r ON r.invoice_id=sub.invoice_id AND r.dataset_id='S1_normal'
        -- can't re-join easily; do it inline
    """), {"hist": hist_start, "as_of": as_of}).scalar()

    # Simpler: mean delay for ALL qualifying invoices
    mean_all = c.execute(text("""
        SELECT AVG(last_receipt - due_date) FROM (
            SELECT i.due_date, MAX(r.date) AS last_receipt
            FROM hm.ar_invoices i
            JOIN hm.counterparties cp ON cp.code=i.cust_code AND cp.dataset_id=i.dataset_id
            LEFT JOIN hm.ar_receipts r ON r.invoice_id=i.invoice_id AND r.dataset_id=i.dataset_id
            WHERE i.dataset_id='S1_normal'
              AND i.issue_date >= :hist AND i.issue_date <= :as_of
            GROUP BY i.invoice_id, i.due_date, cp.segment, i.amount_gross
            HAVING COALESCE(SUM(r.amount), 0) >= i.amount_gross * 0.99
        ) sub
    """), {"hist": hist_start, "as_of": as_of}).scalar()
    print(f"\nMean delay over ALL qualifying invoices: {float(mean_all):.1f} days")

    mean_past_only = c.execute(text("""
        SELECT AVG(last_receipt - due_date) FROM (
            SELECT i.due_date, MAX(r.date) AS last_receipt
            FROM hm.ar_invoices i
            JOIN hm.counterparties cp ON cp.code=i.cust_code AND cp.dataset_id=i.dataset_id
            LEFT JOIN hm.ar_receipts r ON r.invoice_id=i.invoice_id AND r.dataset_id=i.dataset_id
            WHERE i.dataset_id='S1_normal'
              AND i.issue_date >= :hist AND i.issue_date <= :as_of
            GROUP BY i.invoice_id, i.due_date, cp.segment, i.amount_gross
            HAVING COALESCE(SUM(r.amount), 0) >= i.amount_gross * 0.99
        ) sub WHERE last_receipt <= :as_of
    """), {"hist": hist_start, "as_of": as_of}).scalar()
    print(f"Mean delay over PAST-ONLY qualifying invoices: {float(mean_past_only) if mean_past_only else 'N/A':.1f} days")

# Engine's segment pool delays
beh = SimpleBehaviour(eng_analyst, "S1_normal", as_of)
for seg, pool in beh._seg_pools.items():
    if pool:
        print(f"\nEngine segment pool '{seg}': n={len(pool)}, mean={sum(pool)/len(pool):.1f}, min={min(pool):.0f}, max={max(pool):.0f}")

print(f"\nEngine customers with own sample: {sum(1 for v in beh._sources.values() if v=='customer')}")
print(f"Engine customers using segment:   {sum(1 for v in beh._sources.values() if v=='segment')}")
print(f"Engine customers with NO sample:  {sum(1 for c in data['open_ar'] if not beh.delay_sample(c['cust_code']))}")
