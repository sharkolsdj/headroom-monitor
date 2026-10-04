"""
Check: do any customers have negative expected_delay?
If so, deterministic uses due+ed which could go past (lost to beyond),
while MC uses due+max(0,ed) which floors at due date.
"""
import sys
from pathlib import Path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import sqlalchemy as sa
from datetime import timedelta
from engine._behaviour import SimpleBehaviour
from engine._loader import load_dataset
from engine._grid import date_to_week
from config import settings

eng_analyst = sa.create_engine(settings.role_dsn("hm_analyst"), pool_pre_ping=True)
data   = load_dataset(eng_analyst, "S1_normal")
as_of  = data["as_of"]
beh    = SimpleBehaviour(eng_analyst, "S1_normal", as_of)
open_ar = data["open_ar"]

# Check delay samples for negative values
neg_ed = []
for inv in open_ar:
    ed = beh.expected_delay(inv["cust_code"])
    if ed < 0:
        neg_ed.append((inv["cust_code"], ed, float(inv["outstanding_amount"]),
                       (inv["due_date"] - as_of).days))

print(f"Not-yet-due invoices with negative expected_delay: {len(neg_ed)}")
for code, ed, amt, days_to_due in neg_ed[:10]:
    receipt_det = days_to_due + round(ed)  # days from as_of
    print(f"  {code:12s}  ed={ed:6.1f}  amt={amt:>10,.0f}  due_in={days_to_due:3d}d  "
          f"receipt_det=as_of+{receipt_det}d  in_past={'YES' if receipt_det < 0 else 'no'}")

# Also check: for wk2->wk1 misses specifically, what is od and ed?
import sqlalchemy as sa
from sqlalchemy import text
eng_eval = sa.create_engine(settings.role_dsn("hm_evaluator"), pool_pre_ping=True)
with eng_eval.connect() as c:
    actual_receipts = {
        row.invoice_id: {"date": row.date, "amount": float(row.amount)}
        for row in c.execute(text(
            "SELECT invoice_id, date, amount FROM eval.future_ar_receipts "
            "WHERE dataset_id='S1_normal'"
        )).fetchall()
    }

wk2_to_wk1 = []
for inv in open_ar:
    od  = (as_of - inv["due_date"]).days
    ed  = beh.expected_delay(inv["cust_code"])
    amt = float(inv["outstanding_amount"])
    if od <= 0:
        receipt_date = inv["due_date"] + timedelta(days=round(ed))
    else:
        if od >= ed:
            extra = beh.conditional_remaining_delay(inv["cust_code"], float(od))
            receipt_date = as_of + timedelta(days=max(1, round(extra)))
        else:
            receipt_date = inv["due_date"] + timedelta(days=round(ed))
    fcst_wk = date_to_week(receipt_date, as_of, 13)
    act = actual_receipts.get(inv["invoice_id"])
    act_wk = date_to_week(act["date"], as_of, 13) if act else None
    if fcst_wk == 2 and act_wk == 1:
        remaining_to_due = (inv["due_date"] - as_of).days
        sample = beh.delay_sample(inv["cust_code"])
        wk2_to_wk1.append((inv["cust_code"], od, round(ed,1), amt, remaining_to_due,
                           (receipt_date - as_of).days,
                           (act["date"] - as_of).days if act else None,
                           len(sample)))

wk2_to_wk1.sort(key=lambda x: -x[3])
print(f"\nfcst=wk2, actual=wk1 invoices ({len(wk2_to_wk1)} total, showing top 15 by amount):")
print(f"  {'Cust':12s}  {'od':>4s}  {'ed':>5s}  {'amt':>10s}  "
      f"{'due_in':>7s}  {'fcst_d':>7s}  {'act_d':>6s}  {'n_hist':>6s}")
for code, od, ed, amt, due_in, fcst_d, act_d, n in wk2_to_wk1[:15]:
    print(f"  {code:12s}  {od:>4d}  {ed:>5.1f}  {amt:>10,.0f}  "
          f"  {due_in:>4d}d    {fcst_d:>4d}d  {act_d if act_d else '?':>5}d  {n:>6d}")
