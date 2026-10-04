"""
W1 overdue bias diagnostic — three checks:
  1a. Date-formula check: receipt = as_of + (D - od), NOT as_of + D
  1b. KM tail: conditional pools with censored max; residual mass placement
  1c. Historical calibration at as_of - 4/8/12/16 wk (hm data only, no eval)

No file writes to data/demo.
"""
from __future__ import annotations
import io, random, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import sqlalchemy as sa
from sqlalchemy import text

from config import settings
from engine._loader import load_dataset
from engine._behaviour import RecencyBehaviour, _km_mean, _km_sample

N_HIST = 100   # MC runs for historical calibration (fast)

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def _overdue_bucket(od: int) -> str:
    if od <= 0:  return "not_due"
    if od <= 7:  return "od_01_07"
    if od <= 14: return "od_08_14"
    if od <= 30: return "od_15_30"
    return "od_gt30"


def _load_open_ar_at(conn, dataset_id: str, as_of: date) -> list[dict]:
    """Open AR at an arbitrary as_of within the dataset's history."""
    rows = conn.execute(text("""
        SELECT i.invoice_id, i.cust_code, i.due_date,
               i.amount_gross,
               i.amount_gross - COALESCE(SUM(r.amount), 0.0) AS outstanding_amount,
               c.segment
        FROM hm.ar_invoices i
        JOIN hm.counterparties c
            ON c.code = i.cust_code AND c.dataset_id = i.dataset_id
        LEFT JOIN hm.ar_receipts r
            ON r.invoice_id = i.invoice_id AND r.dataset_id = i.dataset_id
            AND r.date <= :as_of
        WHERE i.dataset_id = :did
          AND i.issue_date <= :as_of
        GROUP BY i.invoice_id, i.cust_code, i.due_date, i.amount_gross, c.segment
        HAVING i.amount_gross - COALESCE(SUM(r.amount), 0.0) > 0.005
        ORDER BY i.invoice_id
    """), {"did": dataset_id, "as_of": as_of}).fetchall()
    return [dict(r._mapping) for r in rows]


def _actual_w1_at(conn, dataset_id: str, as_of: date, open_ids: set) -> dict[str, float]:
    """Receipts in (as_of, as_of+7] for invoices in open_ids, from hm.ar_receipts."""
    rows = conn.execute(text("""
        SELECT invoice_id, SUM(amount) AS amt
        FROM hm.ar_receipts
        WHERE dataset_id = :did
          AND date > :as_of
          AND date <= :w1end
        GROUP BY invoice_id
    """), {"did": dataset_id, "as_of": as_of, "w1end": as_of + timedelta(days=7)}).fetchall()
    return {r.invoice_id: float(r.amt)
            for r in rows if r.invoice_id in open_ids}


# -----------------------------------------------------------------------------
# 1a. Date-formula check
# -----------------------------------------------------------------------------

def check_1a(eng: sa.Engine, dataset_id: str) -> None:
    data = load_dataset(eng, dataset_id)
    as_of = data["as_of"]
    beh = RecencyBehaviour(eng, dataset_id, as_of)

    overdue = sorted(
        [inv for inv in data["open_ar"] if (as_of - inv["due_date"]).days > 0],
        key=lambda x: (as_of - x["due_date"]).days, reverse=True
    )

    print(f"\n{'-'*72}")
    print(f"  1a. Date-formula check — {dataset_id}")
    print(f"{'-'*72}")
    print(f"  receipt_date should equal as_of + (D − od) = due_date + D\n")

    for inv in overdue[:3]:
        od = (as_of - inv["due_date"]).days
        cust = inv["cust_code"]
        sample = beh.delay_sample(cust)
        sample_sorted = sorted(sample)

        # Show smallest, median, and a few above od
        above_od = [x for x in sample_sorted if x > od]

        print(f"  Invoice {inv['invoice_id'][:12]}  cust={cust}  due={inv['due_date']}  od={od}d")
        print(f"    sample (min/P25/P50/P75/max): "
              f"{sample_sorted[0]:.0f}/{sample_sorted[len(sample_sorted)//4]:.0f}/"
              f"{sample_sorted[len(sample_sorted)//2]:.0f}/"
              f"{sample_sorted[3*len(sample_sorted)//4]:.0f}/"
              f"{sample_sorted[-1]:.0f}d")
        print(f"    above_od (D > {od}): {len(above_od)}/{len(sample)} samples "
              f"({len(above_od)/len(sample)*100:.0f}%)")
        if above_od:
            r = above_od[0]   # one example remaining
            rd = as_of + timedelta(days=max(1, round(r - od)))
            expected_rd = inv["due_date"] + timedelta(days=round(r))
            match = "OK" if rd == expected_rd else "BUG"
            print(f"    example D={r:.0f}: remaining=D-od={r-od:.0f}  "
                  f"receipt=as_of+{r-od:.0f}={rd}  due+D={expected_rd}  {match}")
        else:
            print(f"    NO samples above od={od} → fallback remaining=1d (receipt=as_of+1)")
        print()


# -----------------------------------------------------------------------------
# 1b. KM tail: conditional pool analysis
# -----------------------------------------------------------------------------

def check_1b(eng: sa.Engine, dataset_id: str) -> None:
    data = load_dataset(eng, dataset_id)
    as_of = data["as_of"]
    beh = RecencyBehaviour(eng, dataset_id, as_of)

    overdue = [inv for inv in data["open_ar"] if (as_of - inv["due_date"]).days > 0]

    print(f"\n{'-'*72}")
    print(f"  1b. KM tail analysis — {dataset_id}  ({len(overdue)} overdue invoices)")
    print(f"{'-'*72}")

    by_bucket: dict[str, dict] = defaultdict(lambda: {
        "n": 0, "n_cens_max": 0, "sum_S": 0.0, "sum_filt": 0.0, "sum_total": 0.0,
    })

    for inv in overdue:
        od = (as_of - inv["due_date"]).days
        cust = inv["cust_code"]
        bkt = _overdue_bucket(od)
        obs = beh._raw_obs.get(cust) or list(beh._seg_pool_obs.get(beh._cust_seg.get(cust, ""), []))

        row = by_bucket[bkt]
        row["n"] += 1

        if not obs:
            continue

        # Conditional pool
        cond_obs = []
        for delay, w, is_event in obs:
            if is_event and delay > od:
                cond_obs.append((delay - od, w, True))
            elif not is_event and delay >= od:
                cond_obs.append((delay - od, w, False))

        if not cond_obs:
            row["n_cens_max"] += 1   # no data at all → treat as censored max
            continue

        max_obs = max(cond_obs, key=lambda x: x[0])
        max_is_censored = not max_obs[2]
        if max_is_censored:
            row["n_cens_max"] += 1

        # Compute residual S from KM steps on cond_obs
        events = [(d, w) for d, w, e in cond_obs if e]
        if not events:
            continue
        t_min_c = min(d for d, _, _ in cond_obs)
        shifted_c = [(d - t_min_c, w, e) for d, w, e in cond_obs]
        S = 1.0
        for t in sorted(set(d for d, w, e in shifted_c if e)):
            at_risk = sum(w for d, w, _ in shifted_c if d >= t)
            evts    = sum(w for d, w, e in shifted_c if e and d == t)
            if at_risk > 0:
                S *= 1.0 - evts / at_risk
        row["sum_S"] += S

        # Fraction of bootstrap samples that would be filtered (x == od or x < od)
        sample = beh.delay_sample(cust)
        n_filt = sum(1 for x in sample if x <= od)
        row["sum_filt"] += n_filt
        row["sum_total"] += len(sample)

    BUCKETS = ["od_01_07", "od_08_14", "od_15_30", "od_gt30"]
    HDR = f"  {'Bucket':12s}  {'N':>4}  {'Cens-max%':>10}  {'Avg S':>7}  {'Filtered%':>10}"
    print(HDR)
    print("  " + "-"*(len(HDR)-2))
    for bkt in BUCKETS:
        r = by_bucket.get(bkt)
        if not r or r["n"] == 0:
            continue
        cens_pct = r["n_cens_max"] / r["n"] * 100
        avg_s    = r["sum_S"] / r["n"]
        filt_pct = r["sum_filt"] / r["sum_total"] * 100 if r["sum_total"] > 0 else 0
        print(f"  {bkt:12s}  {r['n']:>4}  {cens_pct:>9.0f}%  {avg_s:>7.3f}  {filt_pct:>9.0f}%")

    print(f"\n  Interpretation:")
    print(f"  Cens-max% = % of invoices where the conditional pool's max obs is censored")
    print(f"  Avg S     = mean residual survival mass at t_max_s (placed at censored time)")
    print(f"  Filtered% = % of bootstrap samples filtered out by x>od in MC cond")


# -----------------------------------------------------------------------------
# 1c. Historical calibration
# -----------------------------------------------------------------------------

def check_1c(eng: sa.Engine, dataset_id: str) -> None:
    data = load_dataset(eng, dataset_id)
    ds_as_of = data["as_of"]

    print(f"\n{'-'*72}")
    print(f"  1c. Historical W1 calibration — {dataset_id}")
    print(f"{'-'*72}")
    print(f"  as_of          {'Model W1%':>10}  {'Actual W1%':>11}  {'n_overdue':>10}")
    print(f"  {'-'*62}")

    with eng.connect() as conn:
        for lag_wk in (4, 8, 12, 16):
            as_of_h = ds_as_of - timedelta(weeks=lag_wk)
            open_ar = _load_open_ar_at(conn, dataset_id, as_of_h)
            overdue_ar = [inv for inv in open_ar if (as_of_h - inv["due_date"]).days > 0]

            if not overdue_ar:
                print(f"  {as_of_h}  (no overdue invoices)")
                continue

            open_ids = {inv["invoice_id"] for inv in overdue_ar}
            total_amount = sum(float(inv["outstanding_amount"]) for inv in overdue_ar)

            # Instantiate RecencyBehaviour at the historical as_of
            beh_h = RecencyBehaviour(eng, dataset_id, as_of_h)

            # Model W1: fraction of bootstrap samples with remaining ≤ 6 days
            model_w1 = 0.0
            for inv in overdue_ar:
                od = (as_of_h - inv["due_date"]).days
                sample = beh_h.delay_sample(inv["cust_code"])
                cond = [x - od for x in sample if x > od]
                if cond:
                    w1_frac = sum(1 for r in cond if r <= 6) / len(cond)
                else:
                    w1_frac = 1.0   # fallback remaining=1 → W1
                model_w1 += float(inv["outstanding_amount"]) * w1_frac

            # Actual W1 from hm.ar_receipts
            actual_w1_by_inv = _actual_w1_at(conn, dataset_id, as_of_h, open_ids)
            actual_w1 = sum(actual_w1_by_inv.values())

            model_pct  = model_w1  / total_amount * 100 if total_amount else 0
            actual_pct = actual_w1 / total_amount * 100 if total_amount else 0

            print(f"  {as_of_h}  {model_pct:>9.1f}%  {actual_pct:>10.1f}%  {len(overdue_ar):>10}")


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

def main() -> None:
    eng = sa.create_engine(settings.role_dsn("hm_analyst"), pool_pre_ping=True)

    for did in ("S1_normal", "S6_new_customer"):
        check_1a(eng, did)
        check_1b(eng, did)
        check_1c(eng, did)

    print(f"\n{'='*72}")
    print("  Done. No files written.")
    print(f"{'='*72}")


if __name__ == "__main__":
    main()
