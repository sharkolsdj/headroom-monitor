"""
W1 overdue calibration diagnostic:
  1. Split model W1 vs actual W1 by construction (F41/F43) vs all others
     at as_of = 2026-09-28 and 2026-06-29, for S1_normal and S6_new_customer.
  2. Seasonal contamination of conditional pools:
     - Share of conditional pool observations whose due_date falls in a
       seasonal window (construction leave Jul-Aug for F41/F43 obs, or
       Dec 20 - Jan 5 for all obs)
     - Model W1% if those observations are excluded (diagnostic only).
No file writes. No engine changes.
"""
from __future__ import annotations
import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import sqlalchemy as sa
from sqlalchemy import text

from config import settings
from engine._behaviour import RecencyBehaviour

AS_OF_DATES = [date(2026, 9, 28), date(2026, 6, 29)]
DATASETS    = ["S1_normal", "S6_new_customer"]
CONSTR_NACE = {"F41", "F43"}
CONSTR_LEAVE_WINDOWS = [(7, 5), (8, 1), (8, 2)]  # (month, week_of_month)


# ── Seasonal helpers ──────────────────────────────────────────────────────────

def _iso_week_start(year: int, month: int, week_of_month: int) -> date | None:
    """Monday of the nth week (1-based) of month/year, or None if overflows."""
    try:
        d = date(year, month, 1)
        d += timedelta(days=(7 - d.weekday()) % 7)
        d += timedelta(weeks=week_of_month - 1)
        return d if d.month == month else None
    except ValueError:
        return None


def _is_seasonal(dd: date, nace: str | None) -> bool:
    """True if dd inflates the generator delay (year-end always; F41/F43 Jul-Aug)."""
    if (dd.month == 12 and dd.day >= 20) or (dd.month == 1 and dd.day <= 5):
        return True
    if nace in CONSTR_NACE:
        for m, w in CONSTR_LEAVE_WINDOWS:
            ws = _iso_week_start(dd.year, m, w)
            if ws and ws <= dd < ws + timedelta(weeks=1):
                return True
    return False


# ── DB helpers ────────────────────────────────────────────────────────────────

def _load_open_overdue(conn, dataset_id: str, as_of: date) -> list[dict]:
    rows = conn.execute(text("""
        SELECT i.invoice_id, i.cust_code, i.due_date, c.nace, c.segment,
               i.amount_gross - COALESCE(SUM(r.amount), 0.0) AS outstanding
        FROM hm.ar_invoices i
        JOIN hm.counterparties c
            ON c.code = i.cust_code AND c.dataset_id = i.dataset_id
        LEFT JOIN hm.ar_receipts r
            ON r.invoice_id = i.invoice_id AND r.dataset_id = i.dataset_id
            AND r.date <= :as_of
        WHERE i.dataset_id = :did AND i.issue_date <= :as_of
        GROUP BY i.invoice_id, i.cust_code, i.due_date, c.nace, c.segment, i.amount_gross
        HAVING i.amount_gross - COALESCE(SUM(r.amount), 0.0) > 0.005
           AND i.due_date < :as_of
    """), {"did": dataset_id, "as_of": as_of}).fetchall()
    return [dict(r._mapping) for r in rows]


def _load_actual_w1(conn, dataset_id: str, as_of: date, inv_ids: set) -> dict[str, float]:
    w1_end = as_of + timedelta(days=7)
    rows = conn.execute(text("""
        SELECT invoice_id, SUM(amount) AS amt
        FROM hm.ar_receipts
        WHERE dataset_id = :did AND date > :as_of AND date <= :w1e
        GROUP BY invoice_id
    """), {"did": dataset_id, "as_of": as_of, "w1e": w1_end}).fetchall()
    return {r.invoice_id: float(r.amt) for r in rows if r.invoice_id in inv_ids}


def _load_pool_with_due_dates(conn, dataset_id: str, as_of: date) -> dict:
    """
    Returns:
      cust_pool   : {cust_code: [(delay, weight, due_date, nace)]}  paid obs per customer
      seg_pool    : {segment:   [(delay, weight, due_date, nace)]}  all paid obs per segment
      cust_seg    : {cust_code: segment}
      cust_nace   : {cust_code: nace}
      n_paid_cust : {cust_code: int}
    """
    hist_start = as_of - timedelta(days=365)
    rows = conn.execute(text("""
        SELECT i.cust_code, c.segment, c.nace,
               i.due_date, i.amount_gross,
               COALESCE(SUM(r.amount), 0.0) AS paid_amount,
               MAX(r.date) AS last_receipt_date
        FROM hm.ar_invoices i
        JOIN hm.counterparties c
            ON c.code = i.cust_code AND c.dataset_id = i.dataset_id
        LEFT JOIN hm.ar_receipts r
            ON r.invoice_id = i.invoice_id AND r.dataset_id = i.dataset_id
        WHERE i.dataset_id = :did
          AND i.issue_date >= :hs AND i.issue_date <= :as_of
        GROUP BY i.invoice_id, i.cust_code, c.segment, c.nace,
                 i.due_date, i.amount_gross
        HAVING COALESCE(SUM(r.amount), 0.0) >= i.amount_gross * 0.99
        ORDER BY i.invoice_id
    """), {"did": dataset_id, "hs": hist_start, "as_of": as_of}).fetchall()

    cust_pool:    dict[str, list] = defaultdict(list)
    seg_pool:     dict[str, list] = defaultdict(list)
    cust_seg:     dict[str, str]  = {}
    cust_nace:    dict[str, str]  = {}
    n_paid_cust:  dict[str, int]  = defaultdict(int)

    for row in rows:
        if row.last_receipt_date is None:
            continue
        delay = float((row.last_receipt_date - row.due_date).days)
        age = (as_of - row.last_receipt_date).days
        w = 2.0 ** (-age / 60.0)
        entry = (delay, w, row.due_date, row.nace)
        cust_pool[row.cust_code].append(entry)
        seg_pool[row.segment].append(entry)
        cust_seg[row.cust_code]  = row.segment
        cust_nace[row.cust_code] = row.nace
        n_paid_cust[row.cust_code] += 1

    return dict(cust_pool), dict(seg_pool), cust_seg, cust_nace, dict(n_paid_cust)


# ── W1 estimation helpers ─────────────────────────────────────────────────────

def _model_w1_frac_bootstrap(beh: RecencyBehaviour, cust: str, od: float) -> float:
    """Standard model W1 using pre-bootstrapped RecencyBehaviour sample."""
    sample = beh.delay_sample(cust)
    cond = [x - od for x in sample if x > od]
    if cond:
        return sum(1 for r in cond if r <= 6) / len(cond)
    return 1.0


def _model_w1_frac_no_seasonal(
    pool_entries: list[tuple],  # [(delay, weight, due_date, nace)]
    od: float,
) -> float | None:
    """
    Weighted conditional W1 fraction using only non-seasonal pool observations.
    Returns None if no conditional observations remain.
    """
    non_seas = [(d, w) for d, w, dd, nace in pool_entries
                if not _is_seasonal(dd, nace)]
    cond = [(d, w) for d, w in non_seas if d > od]
    if not cond:
        return None
    total_w = sum(w for _, w in cond)
    if total_w <= 0:
        return None
    return sum(w for d, w in cond if d - od <= 6) / total_w


def _seasonal_frac_in_cond(
    pool_entries: list[tuple],  # [(delay, weight, due_date, nace)]
    od: float,
) -> float:
    """Weighted fraction of conditional pool observations (D > od) that are seasonal."""
    cond = [(d, w, _is_seasonal(dd, nace))
            for d, w, dd, nace in pool_entries if d > od]
    if not cond:
        return 0.0
    total_w = sum(w for _, w, _ in cond)
    seas_w  = sum(w for _, w, s in cond if s)
    return seas_w / total_w if total_w > 0 else 0.0


# ── Main diagnostic ───────────────────────────────────────────────────────────

def run(eng: sa.Engine, dataset_id: str, as_of: date) -> None:
    w1_end = as_of + timedelta(days=7)
    print(f"\n{'='*72}")
    print(f"  {dataset_id}  |  as_of={as_of}  W1 window: "
          f"{as_of + timedelta(1)} .. {w1_end}")
    print(f"{'='*72}")

    with eng.connect() as conn:
        overdue = _load_open_overdue(conn, dataset_id, as_of)
        inv_ids = {inv["invoice_id"] for inv in overdue}
        actual_w1 = _load_actual_w1(conn, dataset_id, as_of, inv_ids)
        cust_pool, seg_pool, cust_seg, cust_nace, n_paid = \
            _load_pool_with_due_dates(conn, dataset_id, as_of)

    beh = RecencyBehaviour(eng, dataset_id, as_of)

    # Accumulators for item 1: construction vs others
    grp: dict[str, dict] = {
        "F41/F43 (construction)": {"n": 0, "total": 0.0, "model": 0.0, "actual": 0.0},
        "all others":             {"n": 0, "total": 0.0, "model": 0.0, "actual": 0.0},
    }

    # Accumulators for item 2: seasonal contamination
    seas_acc = {
        "n": 0, "total": 0.0,
        "model": 0.0, "model_no_seas": 0.0, "actual": 0.0,
        "w_seas": 0.0, "w_cond_total": 0.0,
        "n_no_cond_noseas": 0,
    }

    for inv in overdue:
        od   = float((as_of - inv["due_date"]).days)
        amt  = float(inv["outstanding"])
        cust = inv["cust_code"]
        nace = inv["nace"] or ""
        inv_id = inv["invoice_id"]
        grp_key = "F41/F43 (construction)" if nace in CONSTR_NACE else "all others"

        # Choose pool for seasonal analysis (same logic as RecencyBehaviour)
        if n_paid.get(cust, 0) >= 5:
            pool = cust_pool.get(cust, [])
        else:
            seg = cust_seg.get(cust) or inv.get("segment", "")
            pool = seg_pool.get(seg, [])

        # Standard model W1 (bootstrap)
        m_frac = _model_w1_frac_bootstrap(beh, cust, od)
        act_frac = actual_w1.get(inv_id, 0.0) / amt if amt > 0 else 0.0

        # Item 1 accumulation
        g = grp[grp_key]
        g["n"]      += 1
        g["total"]  += amt
        g["model"]  += amt * m_frac
        g["actual"] += actual_w1.get(inv_id, 0.0)

        # Item 2: seasonal contamination
        sf = _seasonal_frac_in_cond(pool, od)
        cond_w = sum(w for d, w, _, _ in pool if d > od)
        seas_acc["w_seas"]       += sf * cond_w
        seas_acc["w_cond_total"] += cond_w

        ns_frac = _model_w1_frac_no_seasonal(pool, od)

        seas_acc["n"]      += 1
        seas_acc["total"]  += amt
        seas_acc["model"]  += amt * m_frac
        seas_acc["actual"] += actual_w1.get(inv_id, 0.0)
        if ns_frac is not None:
            seas_acc["model_no_seas"] += amt * ns_frac
        else:
            seas_acc["model_no_seas"] += amt * m_frac  # fallback to original
            seas_acc["n_no_cond_noseas"] += 1

    # ── Item 1: construction vs others ───────────────────────────────────────
    print(f"\n  -- 1. W1 by segment group --")
    print(f"  {'Group':25s}  {'N':>4}  {'Total':>11}  "
          f"{'Model W1%':>10}  {'Actual W1%':>11}  {'Gap':>6}")
    print("  " + "-"*72)
    for gname in ["F41/F43 (construction)", "all others"]:
        g = grp[gname]
        if g["n"] == 0:
            continue
        mp  = g["model"]  / g["total"] * 100 if g["total"] else 0
        ap  = g["actual"] / g["total"] * 100 if g["total"] else 0
        print(f"  {gname:25s}  {g['n']:>4}  {g['total']:>11,.0f}  "
              f"{mp:>9.1f}%  {ap:>10.1f}%  {(mp-ap):>+6.1f}%")
    # Total
    tot = {"n": sum(g["n"] for g in grp.values()),
           "total":  sum(g["total"]  for g in grp.values()),
           "model":  sum(g["model"]  for g in grp.values()),
           "actual": sum(g["actual"] for g in grp.values())}
    if tot["total"]:
        mp = tot["model"]  / tot["total"] * 100
        ap = tot["actual"] / tot["total"] * 100
        print("  " + "-"*72)
        print(f"  {'TOTAL':25s}  {tot['n']:>4}  {tot['total']:>11,.0f}  "
              f"{mp:>9.1f}%  {ap:>10.1f}%  {(mp-ap):>+6.1f}%")

    # ── Item 2: seasonal contamination ───────────────────────────────────────
    print(f"\n  -- 2. Seasonal contamination of conditional pools --")
    T = seas_acc["total"]
    wc = seas_acc["w_cond_total"]
    seas_pct = seas_acc["w_seas"] / wc * 100 if wc > 0 else 0.0
    orig_pct = seas_acc["model"]         / T * 100 if T else 0.0
    noseas_pct = seas_acc["model_no_seas"] / T * 100 if T else 0.0
    act_pct  = seas_acc["actual"]        / T * 100 if T else 0.0
    print(f"  Seasonal obs in conditional pools (weighted): {seas_pct:.1f}%")
    print(f"  Model W1% (original):              {orig_pct:.1f}%")
    print(f"  Model W1% (seasonal obs excluded): {noseas_pct:.1f}%")
    print(f"  Actual W1%:                        {act_pct:.1f}%")
    if seas_acc["n_no_cond_noseas"]:
        print(f"  (Note: {seas_acc['n_no_cond_noseas']} invoices had empty no-seasonal "
              f"conditional pool; original W1 used as fallback)")


def main() -> None:
    eng = sa.create_engine(settings.role_dsn("hm_analyst"), pool_pre_ping=True)
    for as_of in AS_OF_DATES:
        for did in DATASETS:
            run(eng, did, as_of)
    print(f"\n{'='*72}")
    print("  Done. No files written.")
    print(f"{'='*72}\n")


if __name__ == "__main__":
    main()
