"""
W1 overdue calibration diagnostic:
  1. W1 model vs actual by segment at as_of = 2026-06-29, 2026-08-31, 2026-08-03
  2. public_entities: % of historical receipts falling on last business day of month
  3. Alternative model W1: overdue customers with >=80% month-end history predict
     to pay at the next month-end (diagnostic only, no engine change)

No file writes. No engine changes.
"""
from __future__ import annotations
import calendar, io, sys
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

AS_OF_DATES = [date(2026, 6, 29), date(2026, 8, 31), date(2026, 8, 3)]
DATASETS    = ["S1_normal", "S6_new_customer"]
SEGMENTS    = ["public_entities", "retail_diy", "property_developers",
               "general_contractors", "specialised_installers", None]
SEG_LABEL   = {
    "public_entities":      "public_entities",
    "retail_diy":           "retail_diy",
    "property_developers":  "property_developers",
    "general_contractors":  "construction F41",
    "specialised_installers": "construction F43",
    None:                   "None/unknown",
}
ME_THRESHOLD = 0.80   # >=80% receipts on last-biz-day-of-month


# ── Date helpers ──────────────────────────────────────────────────────────────

def _last_cal_day(y: int, m: int) -> date:
    """Last calendar day of month — matches generator's _next_month_end()."""
    return date(y, m, calendar.monthrange(y, m)[1])


def _is_last_cal_day(d: date) -> bool:
    return d.day == calendar.monthrange(d.year, d.month)[1]


def _next_lcd_after(as_of: date) -> date:
    """Last calendar day of current month if > as_of, else next month's."""
    lcd = _last_cal_day(as_of.year, as_of.month)
    if lcd > as_of:
        return lcd
    y, m = as_of.year, as_of.month
    m += 1
    if m > 12:
        m, y = 1, y + 1
    return _last_cal_day(y, m)


# ── DB queries ────────────────────────────────────────────────────────────────

def _load_overdue(conn, did: str, as_of: date) -> list[dict]:
    rows = conn.execute(text("""
        SELECT i.invoice_id, i.cust_code, i.due_date, c.segment,
               i.amount_gross - COALESCE(SUM(r.amount), 0.0) AS outstanding
        FROM hm.ar_invoices i
        JOIN hm.counterparties c
            ON c.code = i.cust_code AND c.dataset_id = i.dataset_id
        LEFT JOIN hm.ar_receipts r
            ON r.invoice_id = i.invoice_id AND r.dataset_id = i.dataset_id
            AND r.date <= :as_of
        WHERE i.dataset_id = :did AND i.issue_date <= :as_of
        GROUP BY i.invoice_id, i.cust_code, i.due_date, c.segment, i.amount_gross
        HAVING i.amount_gross - COALESCE(SUM(r.amount), 0.0) > 0.005
           AND i.due_date < :as_of
    """), {"did": did, "as_of": as_of}).fetchall()
    return [dict(r._mapping) for r in rows]


def _load_actual_w1(conn, did: str, as_of: date, inv_ids: set) -> dict[str, float]:
    w1e = as_of + timedelta(7)
    rows = conn.execute(text("""
        SELECT invoice_id, SUM(amount) AS amt FROM hm.ar_receipts
        WHERE dataset_id = :did AND date > :as_of AND date <= :w1e
        GROUP BY invoice_id
    """), {"did": did, "as_of": as_of, "w1e": w1e}).fetchall()
    return {r.invoice_id: float(r.amt) for r in rows if r.invoice_id in inv_ids}


def _load_month_end_fracs(conn, did: str, as_of: date) -> tuple[dict, float, int]:
    """
    Returns:
      cust_me_frac: {cust_code: (n_me, n_total)} for paid invoices in last 12 months
      public_entities_pct: overall % of public_entities receipts on last-biz-day
      public_entities_n: total receipt count for public_entities
    """
    hist_start = as_of - timedelta(days=365)
    rows = conn.execute(text("""
        SELECT i.cust_code, c.segment, MAX(r.date) AS receipt_date
        FROM hm.ar_invoices i
        JOIN hm.counterparties c
            ON c.code = i.cust_code AND c.dataset_id = i.dataset_id
        LEFT JOIN hm.ar_receipts r
            ON r.invoice_id = i.invoice_id AND r.dataset_id = i.dataset_id
        WHERE i.dataset_id  = :did
          AND i.issue_date >= :hs AND i.issue_date <= :as_of
        GROUP BY i.invoice_id, i.cust_code, c.segment, i.amount_gross
        HAVING COALESCE(SUM(r.amount), 0.0) >= i.amount_gross * 0.99
    """), {"did": did, "hs": hist_start, "as_of": as_of}).fetchall()

    cust_me: dict[str, list[bool]] = defaultdict(list)
    pe_me = pe_total = 0

    for row in rows:
        if row.receipt_date is None:
            continue
        is_me = _is_last_cal_day(row.receipt_date)
        cust_me[row.cust_code].append(is_me)
        if row.segment == "public_entities":
            pe_total += 1
            if is_me:
                pe_me += 1

    cust_me_frac = {c: (sum(v), len(v)) for c, v in cust_me.items()}
    pe_pct = pe_me / pe_total * 100 if pe_total > 0 else 0.0
    return cust_me_frac, pe_pct, pe_total


# ── W1 model fraction ─────────────────────────────────────────────────────────

def _model_w1_frac(beh: RecencyBehaviour, cust: str, od: float) -> float:
    sample = beh.delay_sample(cust)
    cond = [x - od for x in sample if x > od]
    if cond:
        return sum(1 for r in cond if r <= 6) / len(cond)
    return 1.0


# ── Run one (as_of, dataset) ──────────────────────────────────────────────────

def run(eng: sa.Engine, did: str, as_of: date,
        pe_pct: float, pe_n: int,
        cust_me_frac: dict) -> None:
    w1e  = as_of + timedelta(7)
    nlbd = _next_lcd_after(as_of)
    in_w1 = as_of < nlbd <= w1e

    print(f"\n{'='*72}")
    print(f"  {did}  |  as_of={as_of}  W1={as_of+timedelta(1)}..{w1e}")
    print(f"  Next month-end: {nlbd}  {'(IN W1)' if in_w1 else '(outside W1)'}")
    print(f"{'='*72}")

    with eng.connect() as conn:
        overdue  = _load_overdue(conn, did, as_of)
        inv_ids  = {inv["invoice_id"] for inv in overdue}
        actual_w1 = _load_actual_w1(conn, did, as_of, inv_ids)

    has_actual = bool(actual_w1) or any(True for inv in overdue
                                        if (as_of + timedelta(1)) <= as_of + timedelta(7))

    beh = RecencyBehaviour(eng, did, as_of)

    # ── Item 1: by segment ────────────────────────────────────────────────────
    seg_acc: dict[str | None, dict] = {}
    for seg in SEGMENTS:
        seg_acc[seg] = {"n": 0, "total": 0.0, "model": 0.0, "actual": 0.0}

    alt_model_total = alt_model_me = 0.0   # item 3

    for inv in overdue:
        od    = float((as_of - inv["due_date"]).days)
        amt   = float(inv["outstanding"])
        cust  = inv["cust_code"]
        seg   = inv["segment"]
        inv_id = inv["invoice_id"]

        m_frac  = _model_w1_frac(beh, cust, od)
        act_amt = actual_w1.get(inv_id, 0.0)

        g = seg_acc.get(seg, seg_acc[None])
        g["n"]      += 1
        g["total"]  += amt
        g["model"]  += amt * m_frac
        g["actual"] += act_amt

        # Item 3: alternative month-end model
        n_me, n_tot = cust_me_frac.get(cust, (0, 0))
        if n_tot > 0 and n_me / n_tot >= ME_THRESHOLD:
            # Predict payment at next month-end
            alt_frac = 1.0 if in_w1 else 0.0
        else:
            alt_frac = m_frac

        alt_model_total += amt
        alt_model_me    += amt * alt_frac

    # Print item 1
    print(f"\n  -- 1. W1 by segment --")
    hdr = f"  {'Segment':22s}  {'N':>4}  {'Total':>11}  {'Model W1%':>10}  {'Actual W1%':>11}  {'Gap':>6}"
    print(hdr)
    print("  " + "-"*72)
    tot = {"n": 0, "total": 0.0, "model": 0.0, "actual": 0.0}
    for seg in SEGMENTS:
        g = seg_acc[seg]
        if g["n"] == 0:
            continue
        label = SEG_LABEL.get(seg, str(seg))
        mp = g["model"]  / g["total"] * 100 if g["total"] else 0
        if actual_w1:
            ap = g["actual"] / g["total"] * 100 if g["total"] else 0
            gap_s = f"{mp-ap:>+6.1f}%"
            ap_s  = f"{ap:>10.1f}%"
        else:
            ap_s  = f"{'n/a':>10s}"
            gap_s = f"{'n/a':>6s}"
        print(f"  {label:22s}  {g['n']:>4}  {g['total']:>11,.0f}  "
              f"{mp:>9.1f}%  {ap_s}  {gap_s}")
        for k in tot:
            tot[k] += g[k]
    print("  " + "-"*72)
    mp = tot["model"]  / tot["total"] * 100 if tot["total"] else 0
    if actual_w1:
        ap = tot["actual"] / tot["total"] * 100 if tot["total"] else 0
        print(f"  {'TOTAL':22s}  {tot['n']:>4}  {tot['total']:>11,.0f}  "
              f"{mp:>9.1f}%  {ap:>10.1f}%  {mp-ap:>+6.1f}%")
    else:
        print(f"  {'TOTAL':22s}  {tot['n']:>4}  {tot['total']:>11,.0f}  "
              f"{mp:>9.1f}%  {'n/a':>10s}  {'n/a':>6s}")

    # Print item 2 (per as_of)
    print(f"\n  -- 2. public_entities receipts on last-calendar-day-of-month --")
    print(f"  History window: {as_of - timedelta(365)} .. {as_of}  "
          f"(n={pe_n}  on-last-biz-day: {pe_pct:.1f}%)")

    # Print item 3
    print(f"\n  -- 3. Alternative model: >=80% month-end customers pay at next month-end --")
    print(f"  Next month-end: {nlbd}  {'IN W1 window' if in_w1 else 'outside W1 window'}")
    if alt_model_total > 0:
        alt_pct  = alt_model_me / alt_model_total * 100
        orig_pct = tot["model"] / tot["total"] * 100 if tot["total"] else 0
        print(f"  Original model W1%:     {orig_pct:.1f}%")
        print(f"  Alt model W1% (item 3): {alt_pct:.1f}%")
        if actual_w1:
            act_pct = tot["actual"] / tot["total"] * 100 if tot["total"] else 0
            print(f"  Actual W1%:             {act_pct:.1f}%")

    # Count month-end customers in overdue
    me_custs = set()
    me_inv_total = 0.0
    for inv in overdue:
        cust = inv["cust_code"]
        n_me, n_tot = cust_me_frac.get(cust, (0, 0))
        if n_tot > 0 and n_me / n_tot >= ME_THRESHOLD:
            me_custs.add(cust)
            me_inv_total += float(inv["outstanding"])
    print(f"  (>=80% month-end customers: {len(me_custs)} unique, "
          f"{me_inv_total:,.0f} outstanding, "
          f"{me_inv_total/alt_model_total*100:.1f}% of overdue total)")


def main() -> None:
    eng = sa.create_engine(settings.role_dsn("hm_analyst"), pool_pre_ping=True)

    # Note on "None" segment
    with eng.connect() as conn:
        rows = conn.execute(text("""
            SELECT kind, nace, segment, COUNT(*) as n
            FROM hm.counterparties WHERE dataset_id='S1_normal'
            GROUP BY kind, nace, segment ORDER BY kind, segment
        """)).fetchall()
    print("\n  NOTE: 'None' segment in hm.counterparties:")
    for r in rows:
        if r.segment is None:
            print(f"    kind={r.kind}  nace={r.nace}  segment={r.segment}  n={r.n}")
    print()

    for did in DATASETS:
        for as_of in AS_OF_DATES:
            with eng.connect() as conn:
                cust_me_frac, pe_pct, pe_n = \
                    _load_month_end_fracs(conn, did, as_of)
            run(eng, did, as_of, pe_pct, pe_n, cust_me_frac)

    print(f"\n{'='*72}")
    print("  Done. No files written.")
    print(f"{'='*72}\n")


if __name__ == "__main__":
    main()
