"""Diagnose profit discrepancy and MC band vs expected line."""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from pathlib import Path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import sqlalchemy as sa
from sqlalchemy import text
from config import settings

eng = sa.create_engine(settings.role_dsn("hm_analyst"))

print("=== S2 12 historical months (Oct 25 – Sep 26) ===")
with eng.connect() as c:
    rows = c.execute(text("""
        SELECT month, revenue_booked, cogs, opex, profit
        FROM hm.month_closes
        WHERE dataset_id='S2_big_customer' AND month < '2026-10-01'
        ORDER BY month
    """)).fetchall()
    total = 0.0
    print("month       EBIT        dep_implied  profit      EBIT-profit")
    for r in rows:
        ebit = float(r.revenue_booked) - float(r.cogs) - float(r.opex)
        p = float(r.profit)
        total += p
        print(f"{r.month}  {ebit:>10,.0f}   {20833:>10,.0f}  {p:>10,.0f}  {ebit-p:>10,.0f}")
    print(f"Sum: {total:,.0f}  (overview_all total_profit=577,715)")

print()
print("=== Recurring outflows for S2 (checking tax/payroll months) ===")
with eng.connect() as c:
    rows = c.execute(text("""
        SELECT kind, rule, amount FROM hm.recurring_outflows
        WHERE dataset_id='S2_big_customer'
    """)).fetchall()
    for r in rows:
        print(f"  {r.kind:20s}  amount={float(r.amount):>10,.0f}  rule={r.rule}")

print()
print("=== Generator: what does profit include? ===")
# Check the month_closes generator file
gen_file = ROOT / "ingestion" / "generator" / "_month_closes.py"
if gen_file.exists():
    print(gen_file.read_text()[:3000])
else:
    # Try other locations
    import glob
    files = glob.glob(str(ROOT / "ingestion" / "**" / "*.py"), recursive=True)
    for f in files:
        if "close" in f.lower() or "month" in f.lower():
            print(f"Found: {f}")
