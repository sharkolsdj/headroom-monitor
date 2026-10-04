"""
Targeted diagnostic: for open AR invoices actually paid in week 1,
what does the engine forecast? And vice versa.
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

eng_analyst = sa.create_engine(settings.role_dsn("hm_analyst"), pool_pre_ping=True)
eng_eval    = sa.create_engine(settings.role_dsn("hm_evaluator"), pool_pre_ping=True)

data   = load_dataset(eng_analyst, "S1_normal")
as_of  = data["as_of"]
beh    = SimpleBehaviour(eng_analyst, "S1_normal", as_of)
open_ar = data["open_ar"]

with eng_eval.connect() as c:
    actual_receipts = {
        row.invoice_id: {"date": row.date, "amount": float(row.amount)}
        for row in c.execute(text(
            "SELECT invoice_id, date, amount FROM eval.future_ar_receipts "
            "WHERE dataset_id='S1_normal'"
        )).fetchall()
    }

# Categorise each open AR invoice
# (act_wk, fcst_wk, od_category)
from collections import defaultdict
buckets = defaultdict(float)  # (fcst_wk_label, act_wk_label) -> amount

cond_n0_amt = 0.0   # od>=ed, cond_n=0 → segment fallback
cond_n0_pushed = 0  # of those, how many pushed out of week 1?

for inv in open_ar:
    od  = (as_of - inv["due_date"]).days
    ed  = beh.expected_delay(inv["cust_code"])
    amt = float(inv["outstanding_amount"])

    if od <= 0:
        delay = ed
        receipt_date = inv["due_date"] + timedelta(days=round(delay))
    else:
        if od >= ed:
            sample = beh.delay_sample(inv["cust_code"])
            cond = [x - od for x in sample if x > od]
            cond_n = len(cond)
            extra = beh.conditional_remaining_delay(inv["cust_code"], float(od))
            receipt_date = as_of + timedelta(days=max(1, round(extra)))
            act = actual_receipts.get(inv["invoice_id"])
            act_wk = date_to_week(act["date"], as_of, 13) if act else None
            fcst_wk = date_to_week(receipt_date, as_of, 13)
            if cond_n == 0:
                cond_n0_amt += amt
                if act_wk == 1 and (fcst_wk is None or fcst_wk > 1):
                    cond_n0_pushed += 1
        else:
            receipt_date = inv["due_date"] + timedelta(days=round(ed))

    fcst_wk = date_to_week(receipt_date, as_of, 13)
    act = actual_receipts.get(inv["invoice_id"])
    act_wk = date_to_week(act["date"], as_of, 13) if act else None

    fcst_label = f"wk{fcst_wk}" if fcst_wk and fcst_wk <= 4 else ("wk5+" if fcst_wk else "beyond")
    act_label  = f"wk{act_wk}"  if act_wk  and act_wk  <= 4 else ("wk5+" if act_wk  else "no_rcpt")
    buckets[(fcst_label, act_label)] += amt

print("Forecast->Actual week matrix (EUR amounts, top pairs by size):")
sorted_b = sorted(buckets.items(), key=lambda x: -x[1])
for (f, a), v in sorted_b[:20]:
    marker = " ** MISS" if f != a else ""
    print(f"  fcst={f:8s}  actual={a:8s}  {v:>12,.0f}{marker}")

print(f"\nTotal od>=ed cond_n=0 outstanding: {cond_n0_amt:,.0f}")
print(f"Of those, pushed out of week 1 when actual=wk1: {cond_n0_pushed}")

# How many unique invoices are in each overdue category?
n_od_lt_ed = sum(1 for inv in open_ar if 0 < (as_of-inv["due_date"]).days < beh.expected_delay(inv["cust_code"]))
n_od_ge_ed = sum(1 for inv in open_ar if (as_of-inv["due_date"]).days >= beh.expected_delay(inv["cust_code"]) > 0)
print(f"\nPartially-overdue (0<od<ed): {n_od_lt_ed} invoices")
print(f"Fully-overdue   (od>=ed>0): {n_od_ge_ed} invoices")
