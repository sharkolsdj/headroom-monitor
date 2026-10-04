"""
Q2-end W1 calibration: model vs actual at as_of = 2026-06-29
W1 window = 2026-06-30 .. 2026-07-06 (crosses Q2 end / Q3 start).
Overdue buckets: od_01_07, od_08_14, od_15_30, od_gt30.
Datasets: S1_normal, S6_new_customer.
No file writes.
"""
from __future__ import annotations
import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import sqlalchemy as sa
from sqlalchemy import text

from config import settings
from engine._behaviour import RecencyBehaviour

AS_OF = date(2026, 6, 29)
W1_END = AS_OF + timedelta(days=7)


def _overdue_bucket(od: int) -> str:
    if od <= 0:  return "not_due"
    if od <= 7:  return "od_01_07"
    if od <= 14: return "od_08_14"
    if od <= 30: return "od_15_30"
    return "od_gt30"


def run(eng: sa.Engine, dataset_id: str) -> None:
    print(f"\n{'='*72}")
    print(f"  W1 calibration at as_of={AS_OF}  (W1 crosses Q2/Q3)  [{dataset_id}]")
    print(f"  W1 window: {AS_OF + timedelta(1)} .. {W1_END}")
    print(f"{'='*72}")

    with eng.connect() as conn:
        # Open AR at AS_OF
        rows = conn.execute(text("""
            SELECT i.invoice_id, i.cust_code, i.due_date,
                   i.amount_gross - COALESCE(SUM(r.amount), 0.0) AS outstanding
            FROM hm.ar_invoices i
            LEFT JOIN hm.ar_receipts r
                ON r.invoice_id = i.invoice_id AND r.dataset_id = i.dataset_id
                AND r.date <= :as_of
            WHERE i.dataset_id = :did
              AND i.issue_date <= :as_of
            GROUP BY i.invoice_id, i.cust_code, i.due_date, i.amount_gross
            HAVING i.amount_gross - COALESCE(SUM(r.amount), 0.0) > 0.005
        """), {"did": dataset_id, "as_of": AS_OF}).fetchall()
        open_ar = [dict(r._mapping) for r in rows]

        overdue = [inv for inv in open_ar if (AS_OF - inv["due_date"]).days > 0]

        # Actual W1 receipts
        actual_rows = conn.execute(text("""
            SELECT invoice_id, SUM(amount) AS amt
            FROM hm.ar_receipts
            WHERE dataset_id = :did
              AND date > :as_of
              AND date <= :w1end
            GROUP BY invoice_id
        """), {"did": dataset_id, "as_of": AS_OF, "w1end": W1_END}).fetchall()
        actual_w1 = {r.invoice_id: float(r.amt) for r in actual_rows}

    beh = RecencyBehaviour(eng, dataset_id, AS_OF)

    # Bucket accumulators
    from collections import defaultdict
    buckets: dict[str, dict] = defaultdict(lambda: {
        "n": 0, "total": 0.0, "model_w1": 0.0, "actual_w1": 0.0,
    })

    for inv in overdue:
        od = (AS_OF - inv["due_date"]).days
        bkt = _overdue_bucket(od)
        amt = float(inv["outstanding"])
        inv_id = inv["invoice_id"]

        b = buckets[bkt]
        b["n"] += 1
        b["total"] += amt

        # Model W1 fraction
        sample = beh.delay_sample(inv["cust_code"])
        cond = [x - od for x in sample if x > od]
        if cond:
            w1_frac = sum(1 for r in cond if r <= 6) / len(cond)
        else:
            w1_frac = 1.0
        b["model_w1"] += amt * w1_frac

        # Actual W1
        b["actual_w1"] += actual_w1.get(inv_id, 0.0)

    BUCKETS = ["od_01_07", "od_08_14", "od_15_30", "od_gt30"]
    print(f"\n  {'Bucket':12s}  {'N':>4}  {'Total':>12}  {'Model W1%':>10}  {'Actual W1%':>11}  {'Gap':>6}")
    print("  " + "-"*64)
    for bkt in BUCKETS:
        b = buckets.get(bkt)
        if not b or b["n"] == 0:
            print(f"  {bkt:12s}  {'--':>4}")
            continue
        m_pct = b["model_w1"]  / b["total"] * 100 if b["total"] else 0
        a_pct = b["actual_w1"] / b["total"] * 100 if b["total"] else 0
        gap   = m_pct - a_pct
        print(f"  {bkt:12s}  {b['n']:>4}  {b['total']:>12,.0f}  "
              f"{m_pct:>9.1f}%  {a_pct:>10.1f}%  {gap:>+6.1f}%")

    # Totals
    total_n     = sum(b["n"]         for b in buckets.values())
    total_total = sum(b["total"]     for b in buckets.values())
    total_model = sum(b["model_w1"]  for b in buckets.values())
    total_actual= sum(b["actual_w1"] for b in buckets.values())
    if total_total:
        print("  " + "-"*64)
        print(f"  {'TOTAL':12s}  {total_n:>4}  {total_total:>12,.0f}  "
              f"{total_model/total_total*100:>9.1f}%  "
              f"{total_actual/total_total*100:>10.1f}%  "
              f"{(total_model-total_actual)/total_total*100:>+6.1f}%")


def main() -> None:
    eng = sa.create_engine(settings.role_dsn("hm_analyst"), pool_pre_ping=True)
    for did in ("S1_normal", "S6_new_customer"):
        run(eng, did)
    print(f"\n{'='*72}")
    print("  Done. No files written.")
    print(f"{'='*72}\n")


if __name__ == "__main__":
    main()
