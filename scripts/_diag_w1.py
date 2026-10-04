"""
W1 calibration diagnostic — open AR, week 1, by overdue bucket × delay source.
No file writes to data/demo. Run: .venv/Scripts/python.exe scripts/_diag_w1.py
"""
from __future__ import annotations
import random, sys
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import sqlalchemy as sa
from sqlalchemy import text

from config import settings
from engine._loader import load_dataset
from engine._behaviour import RecencyBehaviour
from engine._montecarlo import _r1_sample
from engine._components import r1_open_receivables

N_RUNS = 1_000
SEED   = 42


def _bucket(od: int) -> str:
    if od <= 0:  return "not_due"
    if od <= 7:  return "od_01_07"
    if od <= 14: return "od_08_14"
    if od <= 30: return "od_15_30"
    return "od_gt30"


def diagnose(dataset_id: str) -> None:
    eng_analyst = sa.create_engine(settings.role_dsn("hm_analyst"), pool_pre_ping=True)
    eng_eval    = sa.create_engine(settings.role_dsn("hm_evaluator"), pool_pre_ping=True)

    data   = load_dataset(eng_analyst, dataset_id)
    as_of  = data["as_of"]
    beh    = RecencyBehaviour(eng_analyst, dataset_id, as_of)
    open_ar = data["open_ar"]

    # ── Classify each invoice ─────────────────────────────────────────────────
    inv_meta: dict[str, dict] = {}
    for inv in open_ar:
        od  = (as_of - inv["due_date"]).days
        inv_meta[inv["invoice_id"]] = {
            "bucket": _bucket(od),
            "source": beh.source(inv["cust_code"]),
            "amount": float(inv["outstanding_amount"]),
        }

    # ── Accumulate MC W1 amounts per invoice ──────────────────────────────────
    inv_w1_total: dict[str, float] = defaultdict(float)
    rng = random.Random(SEED)
    for _ in range(N_RUNS):
        r1_wk, _ = _r1_sample(open_ar, beh, as_of, 13, rng, "expected")
        for item in r1_wk.get(1, []):
            inv_w1_total[item["invoice_id"]] += item["amount"]

    # ── Actual W1 receipts from eval ──────────────────────────────────────────
    w1_end = as_of + timedelta(days=6)
    with eng_eval.connect() as conn:
        rows = conn.execute(text("""
            SELECT invoice_id, SUM(amount) AS amt
            FROM eval.future_ar_receipts
            WHERE dataset_id = :did AND date <= :w1end
            GROUP BY invoice_id
        """), {"did": dataset_id, "w1end": w1_end}).fetchall()
    actual_w1: dict[str, float] = {r.invoice_id: float(r.amt) for r in rows}

    # ── Aggregate by (bucket, source) ─────────────────────────────────────────
    BUCKETS  = ["not_due", "od_01_07", "od_08_14", "od_15_30", "od_gt30"]
    SOURCES  = ["customer", "segment"]
    tbl: dict[tuple, dict] = {}
    for inv in open_ar:
        iid = inv["invoice_id"]
        meta = inv_meta[iid]
        key  = (meta["bucket"], meta["source"])
        if key not in tbl:
            tbl[key] = {"n": 0, "amount": 0.0, "model_w1": 0.0, "actual_w1": 0.0}
        tbl[key]["n"]        += 1
        tbl[key]["amount"]   += meta["amount"]
        tbl[key]["model_w1"] += inv_w1_total.get(iid, 0.0) / N_RUNS
        tbl[key]["actual_w1"] += actual_w1.get(iid, 0.0)

    # ── R1 13-week deterministic total ────────────────────────────────────────
    r1_det, _ = r1_open_receivables(open_ar, beh, as_of, 13, "expected")
    r1_fcst   = sum(i["amount"] for items in r1_det.values() for i in items)
    with eng_eval.connect() as conn:
        r1_act = float(conn.execute(text("""
            SELECT COALESCE(SUM(r.amount), 0)
            FROM eval.future_ar_receipts r
            JOIN hm.ar_invoices i
              ON i.invoice_id = r.invoice_id AND i.dataset_id = r.dataset_id
            WHERE r.dataset_id = :did
              AND i.issue_date <= :as_of
        """), {"did": dataset_id, "as_of": as_of}).scalar())

    # ── Print ─────────────────────────────────────────────────────────────────
    print(f"\n{'='*80}")
    print(f"  {dataset_id}  —  W1 open-AR breakdown  (N_MC={N_RUNS})")
    print(f"{'='*80}")
    HDR = f"{'Bucket':12s}  {'Source':10s}  {'N':>4}  {'Amount':>11}  {'Model W1':>11}  {'Actual W1':>11}"
    print(HDR)
    print("-" * len(HDR))
    tot_amount = tot_model = tot_actual = 0.0
    for bkt in BUCKETS:
        for src in SOURCES:
            key = (bkt, src)
            if key not in tbl:
                continue
            row = tbl[key]
            am, mw, aw = row["amount"], row["model_w1"], row["actual_w1"]
            tot_amount += am; tot_model += mw; tot_actual += aw
            pm = mw / am * 100 if am else 0
            pa = aw / am * 100 if am else 0
            print(f"{bkt:12s}  {src:10s}  {row['n']:>4}  {am:>11,.0f}  "
                  f"{mw:>8,.0f} {pm:>3.0f}%  {aw:>8,.0f} {pa:>3.0f}%")
    print("-" * len(HDR))
    pm = tot_model / tot_amount * 100 if tot_amount else 0
    pa = tot_actual / tot_amount * 100 if tot_amount else 0
    print(f"{'TOTAL':12s}  {'':10s}  {'':>4}  {tot_amount:>11,.0f}  "
          f"{tot_model:>8,.0f} {pm:>3.0f}%  {tot_actual:>8,.0f} {pa:>3.0f}%")

    diff_pct  = (r1_fcst - r1_act) / r1_act * 100 if r1_act else 0
    print(f"\nR1 13-wk total:  forecast={r1_fcst:,.0f}  actual={r1_act:,.0f}"
          f"  diff={r1_fcst - r1_act:+,.0f} ({diff_pct:+.1f}%)")


if __name__ == "__main__":
    diagnose("S1_normal")
    diagnose("S6_new_customer")
    print("\nDone.")
