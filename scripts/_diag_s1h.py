"""
Compare historical delays (training data) vs actual future delays (from eval).
If actual future delays are systematically shorter, the engine learns too-slow
behavior from history and we can identify the discrepancy.
"""
import sys
from pathlib import Path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import sqlalchemy as sa
from sqlalchemy import text
from datetime import timedelta
from engine._behaviour import SimpleBehaviour
from engine._loader import load_dataset
from config import settings

eng_admin   = sa.create_engine(settings.postgres_dsn, pool_pre_ping=True)
eng_analyst = sa.create_engine(settings.role_dsn("hm_analyst"), pool_pre_ping=True)
eng_eval    = sa.create_engine(settings.role_dsn("hm_evaluator"), pool_pre_ping=True)

data  = load_dataset(eng_analyst, "S1_normal")
as_of = data["as_of"]
hist_start = as_of - timedelta(days=365)
beh   = SimpleBehaviour(eng_analyst, "S1_normal", as_of)

# Actual future delays for open_ar invoices that get paid
with eng_eval.connect() as c:
    future_rows = c.execute(text("""
        SELECT r.invoice_id, r.date AS receipt_date, i.due_date,
               (r.date - i.due_date) AS delay_days
        FROM eval.future_ar_receipts r
        JOIN hm.ar_invoices i ON i.invoice_id = r.invoice_id AND i.dataset_id = r.dataset_id
        WHERE r.dataset_id = 'S1_normal'
    """)).fetchall()

future_delays = [float(r.delay_days) for r in future_rows]

# Historical delays (full training window)
with eng_admin.connect() as c:
    hist_rows = c.execute(text("""
        SELECT i.cust_code, MAX(r.date) - i.due_date AS delay_days
        FROM hm.ar_invoices i
        JOIN hm.ar_receipts r ON r.invoice_id = i.invoice_id AND r.dataset_id = i.dataset_id
        WHERE i.dataset_id = 'S1_normal'
          AND i.issue_date >= :hist AND i.issue_date <= :as_of
        GROUP BY i.invoice_id, i.cust_code, i.due_date, i.amount_gross
        HAVING COALESCE(SUM(r.amount), 0) >= i.amount_gross * 0.99
    """), {"hist": hist_start, "as_of": as_of}).fetchall()

hist_delays = [float(r.delay_days) for r in hist_rows]

print("=== Historical training delays ===")
print(f"  N={len(hist_delays)}")
print(f"  Mean={sum(hist_delays)/len(hist_delays):.1f}d")
hist_sorted = sorted(hist_delays)
p25 = hist_sorted[len(hist_sorted)//4]
p50 = hist_sorted[len(hist_sorted)//2]
p75 = hist_sorted[3*len(hist_sorted)//4]
print(f"  P25={p25:.0f}d  P50={p50:.0f}d  P75={p75:.0f}d  Max={max(hist_delays):.0f}d")
print(f"  Negative (early payers): {sum(1 for x in hist_delays if x < 0)}")
print(f"  0-7 days: {sum(1 for x in hist_delays if 0 <= x <= 7)}")
print(f"  8-14 days: {sum(1 for x in hist_delays if 8 <= x <= 14)}")
print(f"  >21 days: {sum(1 for x in hist_delays if x > 21)}")

print("\n=== Actual future delays (evaluation period) ===")
print(f"  N={len(future_delays)}")
if future_delays:
    print(f"  Mean={sum(future_delays)/len(future_delays):.1f}d")
    fs = sorted(future_delays)
    print(f"  P25={fs[len(fs)//4]:.0f}d  P50={fs[len(fs)//2]:.0f}d  P75={fs[3*len(fs)//4]:.0f}d  Max={max(future_delays):.0f}d")
    print(f"  Negative (early payers): {sum(1 for x in future_delays if x < 0)}")
    print(f"  0-7 days: {sum(1 for x in future_delays if 0 <= x <= 7)}")
    print(f"  8-14 days: {sum(1 for x in future_delays if 8 <= x <= 14)}")
    print(f"  >21 days: {sum(1 for x in future_delays if x > 21)}")

# What fraction of future receipts (week 1) are for currently-overdue invoices?
open_ar = data["open_ar"]
open_ar_ids = {inv["invoice_id"] for inv in open_ar}
with eng_eval.connect() as c:
    week1_rows = c.execute(text("""
        SELECT r.invoice_id, r.date AS receipt_date, i.due_date
        FROM eval.future_ar_receipts r
        JOIN hm.ar_invoices i ON i.invoice_id = r.invoice_id AND i.dataset_id = r.dataset_id
        WHERE r.dataset_id = 'S1_normal'
          AND r.date <= :w1end
    """), {"w1end": as_of + timedelta(days=6)}).fetchall()

w1_overdue = [r for r in week1_rows if r.invoice_id in open_ar_ids and r.due_date < as_of]
w1_notdue  = [r for r in week1_rows if r.invoice_id in open_ar_ids and r.due_date >= as_of]
w1_new     = [r for r in week1_rows if r.invoice_id not in open_ar_ids]
print(f"\n=== Week-1 actual receipts breakdown ===")
print(f"  Overdue (od>0) open AR:   {len(w1_overdue):3d} invoices")
print(f"  Not-yet-due open AR:       {len(w1_notdue):3d} invoices")
print(f"  New invoices (R2):         {len(w1_new):3d} invoices")

# For overdue invoices paid in wk1: what are their actual delays vs engine expected_delay?
print(f"\nOverdue invoices paid in week 1 (actual od->actual delay from as_of):")
for r in sorted(w1_overdue, key=lambda x: -(as_of - x.due_date).days)[:10]:
    od = (as_of - r.due_date).days
    act_remaining = (r.receipt_date - as_of).days
    ed = beh.expected_delay(r.invoice_id[:8])  # might not match
    inv = next((i for i in open_ar if i["invoice_id"] == r.invoice_id), None)
    if inv:
        ed = beh.expected_delay(inv["cust_code"])
        print(f"  {inv['cust_code']:12s}  od={od:3d}  ed={ed:5.1f}  actual_remaining={act_remaining}d")
