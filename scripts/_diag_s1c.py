"""
Diagnostic: compare engine estimated delay vs actual computed delay for S1_normal.
Actual delay = (receipt_date - due_date) averaged over each customer's paid history.
Engine delay = SimpleBehaviour.expected_delay() from last-12-months paid invoices.
"""
import sys
from pathlib import Path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import sqlalchemy as sa
from sqlalchemy import text
from datetime import date
from config import settings
from engine._behaviour import SimpleBehaviour
from engine._loader import load_dataset

eng_admin = sa.create_engine(settings.postgres_dsn, pool_pre_ping=True)
eng_analyst = sa.create_engine(settings.role_dsn("hm_analyst"), pool_pre_ping=True)
eng_eval   = sa.create_engine(settings.role_dsn("hm_evaluator"), pool_pre_ping=True)

data = load_dataset(eng_analyst, "S1_normal")
as_of = data["as_of"]
hist_start = as_of - __import__("datetime").timedelta(days=365)

beh = SimpleBehaviour(eng_analyst, "S1_normal", as_of)

# True mean delay from ALL paid invoices (not just last 12m) via eval + hm
with eng_admin.connect() as c:
    rows = c.execute(text("""
        SELECT i.cust_code,
               AVG( (r.date - i.due_date) ) AS true_mean_delay,
               COUNT(*) AS n
        FROM hm.ar_invoices i
        JOIN hm.ar_receipts r ON r.invoice_id=i.invoice_id AND r.dataset_id=i.dataset_id
        WHERE i.dataset_id='S1_normal'
          AND i.issue_date >= :hist
          AND i.issue_date <= :as_of
        GROUP BY i.cust_code
        HAVING COUNT(*) >= 5
        ORDER BY i.cust_code
    """), {"hist": hist_start, "as_of": as_of}).fetchall()

print(f"{'Code':12s}  {'True':>7s}  {'Engine':>8s}  {'Diff':>7s}  N")
diffs = []
for r in rows:
    code = r.cust_code
    true_d = float(r.true_mean_delay)
    eng_d  = beh.expected_delay(code)
    diff   = eng_d - true_d
    diffs.append(diff)
    if abs(diff) > 5:
        print(f"  {code:12s}  {true_d:7.1f}  {eng_d:8.1f}  {diff:+7.1f}  {r.n}")

if diffs:
    avg = sum(diffs) / len(diffs)
    print(f"\nTotal customers compared: {len(diffs)}")
    print(f"Mean bias (engine - true): {avg:+.2f} days  (positive = engine overestimates delay)")

# Also check the SimpleBehaviour query: does it use issue_date or paid date?
print("\n--- SimpleBehaviour internal query check ---")
with eng_admin.connect() as c:
    # Check: how many invoices qualify under current query?
    n = c.execute(text("""
        SELECT COUNT(DISTINCT i.invoice_id)
        FROM hm.ar_invoices i
        JOIN hm.counterparties c2 ON c2.code=i.cust_code AND c2.dataset_id=i.dataset_id
        LEFT JOIN hm.ar_receipts r ON r.invoice_id=i.invoice_id AND r.dataset_id=i.dataset_id
        WHERE i.dataset_id='S1_normal'
          AND i.issue_date >= :hist AND i.issue_date <= :as_of
        GROUP BY i.invoice_id, i.amount_gross
        HAVING COALESCE(SUM(r.amount), 0) >= i.amount_gross * 0.99
    """), {"hist": hist_start, "as_of": as_of}).fetchone()
    print(f"  Invoices matching SimpleBehaviour HAVING clause: {n[0] if n else '?'}")

# Check: what is the delay formula? r.date - i.due_date
with eng_admin.connect() as c:
    sample = c.execute(text("""
        SELECT i.cust_code, i.due_date, MAX(r.date) AS receipt_date,
               MAX(r.date) - i.due_date AS delay_days
        FROM hm.ar_invoices i
        JOIN hm.ar_receipts r ON r.invoice_id=i.invoice_id AND r.dataset_id=i.dataset_id
        WHERE i.dataset_id='S1_normal'
          AND i.issue_date >= :hist AND i.issue_date <= :as_of
        GROUP BY i.cust_code, i.invoice_id, i.due_date
        ORDER BY delay_days DESC
        LIMIT 10
    """), {"hist": hist_start, "as_of": as_of}).fetchall()
    print("\nSample invoice delays (top 10 by delay):")
    for r in sample:
        print(f"  {r.cust_code}  due={r.due_date}  receipt={r.receipt_date}  delay={r.delay_days}d")
