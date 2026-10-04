"""
Final diagnostic: how many open AR invoices are overdue vs not-yet-due,
and what delays does the engine assign to the overdue ones vs what actually happens.
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
from engine._grid import date_to_week
from config import settings

eng_admin  = sa.create_engine(settings.postgres_dsn, pool_pre_ping=True)
eng_eval   = sa.create_engine(settings.role_dsn("hm_evaluator"), pool_pre_ping=True)
eng_analyst = sa.create_engine(settings.role_dsn("hm_analyst"), pool_pre_ping=True)

data = load_dataset(eng_analyst, "S1_normal")
as_of      = data["as_of"]
beh = SimpleBehaviour(eng_analyst, "S1_normal", as_of)

open_ar = data["open_ar"]
print(f"Open AR invoices: {len(open_ar)}")

overdue     = [inv for inv in open_ar if inv["due_date"] < as_of]
not_yet_due = [inv for inv in open_ar if inv["due_date"] >= as_of]
print(f"  overdue:     {len(overdue)}")
print(f"  not yet due: {len(not_yet_due)}")

# What fraction of overdue invoices have overdue_days >= expected_delay?
flagged_beyond = 0
for inv in overdue:
    od = (as_of - inv["due_date"]).days
    ed = beh.expected_delay(inv["cust_code"])
    if od >= ed:
        flagged_beyond += 1
print(f"  overdue where overdue_days >= expected_delay (uses conditional): {flagged_beyond}")

# For overdue invoices, what does the engine forecast (week) vs actual (from eval)?
with eng_eval.connect() as c:
    actual_receipts = {
        row.invoice_id: {"date": row.date, "amount": float(row.amount)}
        for row in c.execute(text(
            "SELECT invoice_id, date, amount FROM eval.future_ar_receipts "
            "WHERE dataset_id='S1_normal'"
        )).fetchall()
    }

wk1_fcst_overdue = 0.0
wk1_actual_overdue = 0.0
wk1_fcst_notdue = 0.0
wk1_actual_notdue = 0.0

for inv in open_ar:
    od = (as_of - inv["due_date"]).days
    ed = beh.expected_delay(inv["cust_code"])
    amt = float(inv["outstanding_amount"])
    cust = inv["cust_code"]
    due  = inv["due_date"]

    # Engine forecast receipt date
    if od <= 0:  # not yet due
        delay = ed
        receipt_date = due + timedelta(days=round(delay))
    else:
        if od >= ed:
            extra = beh.conditional_remaining_delay(cust, float(od))
            receipt_date = as_of + timedelta(days=max(1, round(extra)))
        else:
            receipt_date = due + timedelta(days=round(ed))

    fcst_wk = date_to_week(receipt_date, as_of, 13)

    # Actual receipt date
    act = actual_receipts.get(inv["invoice_id"])
    act_wk = date_to_week(act["date"], as_of, 13) if act else None

    if od <= 0:
        if fcst_wk == 1:
            wk1_fcst_notdue += amt
        if act_wk == 1:
            wk1_actual_notdue += amt
    else:
        if fcst_wk == 1:
            wk1_fcst_overdue += amt
        if act_wk == 1:
            wk1_actual_overdue += amt

print(f"\nWeek-1 breakdown:")
print(f"  Not-yet-due:  forecast={wk1_fcst_notdue:>10,.0f}  actual={wk1_actual_notdue:>10,.0f}")
print(f"  Overdue:      forecast={wk1_fcst_overdue:>10,.0f}  actual={wk1_actual_overdue:>10,.0f}")
print(f"  Total R1 fcst={wk1_fcst_notdue+wk1_fcst_overdue:>10,.0f}  actual={wk1_actual_notdue+wk1_actual_overdue:>10,.0f}")

# Check conditional_remaining_delay for overdue invoices
print(f"\nConditional remaining delay samples (first 10 overdue):")
for inv in overdue[:10]:
    od = (as_of - inv["due_date"]).days
    ed = beh.expected_delay(inv["cust_code"])
    sample = beh.delay_sample(inv["cust_code"])
    cond = [x - od for x in sample if x > od]
    extra = beh.conditional_remaining_delay(inv["cust_code"], float(od))
    act = actual_receipts.get(inv["invoice_id"])
    act_days = (act["date"] - as_of).days if act else None
    print(f"  {inv['cust_code']:12s}  od={od:3d}  ed={ed:5.1f}  "
          f"cond_n={len(cond):3d}  extra={extra:4.1f}  "
          f"actual_remaining={act_days}")
