"""
Cash-flow component diagnostic for Phase 2A.

Connects as:
  hm_analyst   — runs engine components (same role as production engine)
  hm_evaluator — reads eval.future_ar_receipts / eval.future_ap_payments
                 (NEVER imported by the engine itself)

Usage:
  python scripts/diag_2a_cashflow.py
"""
from __future__ import annotations

import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy import text

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from config import settings
from ingestion.generator._cfg import load as load_cfg
from engine._loader import load_dataset
from engine._behaviour import SimpleBehaviour
from engine._components import (
    r1_open_receivables,
    r2_future_sales,
    p1_open_payables,
    p2_future_purchases,
    p4_recurring,
    p5_vat,
)
from engine._forecast import _SUPPLIER_TERM_MIX, ENGINE_VERSION


def _sum_items(by_week: dict[int, list[dict]]) -> float:
    return sum(float(item["amount"]) for items in by_week.values() for item in items)


def _sum_by_kind(by_week: dict[int, list[dict]]) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for items in by_week.values():
        for item in items:
            totals[item.get("kind", "?")] += float(item["amount"])
    return dict(totals)


def _week_detail(by_week: dict[int, list[dict]], week: int) -> list[dict]:
    return by_week.get(week, [])


def run_component_breakdown(
    analyst_engine: sa.Engine,
    dataset_id: str,
    scenario: str = "expected",
) -> dict:
    """Run all components separately and return totals + per-week detail."""
    data = load_dataset(analyst_engine, dataset_id)
    as_of: date = data["as_of"]
    behaviour = SimpleBehaviour(analyst_engine, dataset_id, as_of)

    r1_by_week, beyond = r1_open_receivables(
        data["open_ar"], behaviour, as_of, 13, scenario
    )
    r2_by_week, sf, r2_net_by_issue_week = r2_future_sales(
        data["history_ar"], data["segments"], behaviour, as_of, data["history_start"]
    )
    p1_by_week = p1_open_payables(data["open_ap"], as_of, 13)
    p2_by_week = p2_future_purchases(
        r2_net_by_issue_week, 0.30, 0.17, _SUPPLIER_TERM_MIX, as_of, 13
    )
    p4_by_week = p4_recurring(data["recurring"], as_of, 13)
    p5_by_week = p5_vat(
        data["history_ar"], data["history_ap"],
        r2_by_week, p2_by_week, as_of, 15, 13,
        r2_net_by_issue_week=r2_net_by_issue_week,
        gross_margin=0.30,
        vat_rate=0.17,
    )

    return {
        "as_of":   as_of,
        "R1":      _sum_items(r1_by_week),
        "R2":      _sum_items(r2_by_week),
        "R2_net_all_issues": sum(r2_net_by_issue_week.values()),
        "P1":      _sum_items(p1_by_week),
        "P2":      _sum_items(p2_by_week),
        "P4_by_kind": _sum_by_kind(p4_by_week),
        "P5":      _sum_items(p5_by_week),
        "week8_pay":  _week_detail(p1_by_week, 8) + _week_detail(p2_by_week, 8)
                    + _week_detail(p4_by_week, 8) + _week_detail(p5_by_week, 8),
        "week13_pay": _week_detail(p1_by_week, 13) + _week_detail(p2_by_week, 13)
                    + _week_detail(p4_by_week, 13) + _week_detail(p5_by_week, 13),
        "week8_rec":  _week_detail(r1_by_week, 8) + _week_detail(r2_by_week, 8),
        "week13_rec": _week_detail(r1_by_week, 13) + _week_detail(r2_by_week, 13),
        "open_ar_total": sum(float(inv["outstanding_amount"]) for inv in data["open_ar"]),
        "open_ap_total": sum(float(inv["outstanding_amount"]) for inv in data["open_ap"]),
        "beyond_horizon_count": len(beyond),
    }


def eval_comparison(evaluator_engine: sa.Engine, analyst_engine: sa.Engine,
                    dataset_id: str, as_of: date) -> dict:
    """Compare engine R1/P1 totals to eval ground-truth (hm_evaluator only)."""
    horizon_end = as_of + timedelta(weeks=13) - timedelta(days=1)

    with evaluator_engine.connect() as conn:
        # Total future AR receipts in 13-week window
        eval_ar_total = float(conn.execute(text("""
            SELECT COALESCE(SUM(amount), 0)
            FROM eval.future_ar_receipts
            WHERE dataset_id = :did
              AND date BETWEEN :aod AND :hend
        """), {"did": dataset_id, "aod": as_of, "hend": horizon_end}).scalar())

        # R1-origin: receipts for invoices already issued at as_of
        eval_r1 = float(conn.execute(text("""
            SELECT COALESCE(SUM(f.amount), 0)
            FROM eval.future_ar_receipts f
            JOIN hm.ar_invoices a
                ON a.invoice_id = f.invoice_id AND a.dataset_id = f.dataset_id
            WHERE f.dataset_id = :did
              AND f.date BETWEEN :aod AND :hend
        """), {"did": dataset_id, "aod": as_of, "hend": horizon_end}).scalar())

        # R2-origin: receipts for invoices issued AFTER as_of (future sales)
        eval_r2 = eval_ar_total - eval_r1

        # Total future AP payments in 13-week window
        eval_ap_total = float(conn.execute(text("""
            SELECT COALESCE(SUM(amount), 0)
            FROM eval.future_ap_payments
            WHERE dataset_id = :did
              AND date BETWEEN :aod AND :hend
        """), {"did": dataset_id, "aod": as_of, "hend": horizon_end}).scalar())

        # P1-origin: payments on invoices already issued at as_of
        eval_p1 = float(conn.execute(text("""
            SELECT COALESCE(SUM(f.amount), 0)
            FROM eval.future_ap_payments f
            JOIN hm.ap_invoices a
                ON a.invoice_id = f.invoice_id AND a.dataset_id = f.dataset_id
            WHERE f.dataset_id = :did
              AND f.date BETWEEN :aod AND :hend
        """), {"did": dataset_id, "aod": as_of, "hend": horizon_end}).scalar())

        eval_p2 = eval_ap_total - eval_p1

    return {
        "eval_ar_total": eval_ar_total,
        "eval_r1": eval_r1,
        "eval_r2": eval_r2,
        "eval_ap_total": eval_ap_total,
        "eval_p1": eval_p1,
        "eval_p2": eval_p2,
    }


def print_report(dataset_id: str, bd: dict, ev: dict, cfg) -> None:
    W = 70
    H = "─" * W

    # ── Annual run-rate expectations ──────────────────────────────────────────
    wk_factor = 13 / 52
    annual_gross_rev = cfg.net_revenue_annual * (1 + cfg.vat_rate)
    r2_runrate = annual_gross_rev * wk_factor
    p2_runrate = cfg.cogs_annual * (1 + cfg.vat_rate) * wk_factor
    p4_net_runrate = cfg.payroll_net_monthly * 3          # Sep/Oct/Nov
    p4_soc_runrate = cfg.payroll_social_monthly * 3       # Oct 15, Nov 15, Dec 15
    p4_rent_runrate = cfg.rent_monthly * 3
    p4_opex_runrate = cfg.opex_fixed_monthly * 3
    p4_tax_runrate = cfg.tax_advance_quarterly * 1        # Dec 10 only
    net_vat_annual = cfg.net_revenue_annual * cfg.vat_rate - cfg.cogs_annual * cfg.vat_rate
    p5_runrate = net_vat_annual * wk_factor
    total_pay_runrate = p2_runrate + p4_net_runrate + p4_soc_runrate + p4_rent_runrate + \
                        p4_opex_runrate + p4_tax_runrate + p5_runrate

    P4 = bd["P4_by_kind"]
    r1, r2 = bd["R1"], bd["R2"]
    p1, p2 = bd["P1"], bd["P2"]
    p4_net = P4.get("payroll_net", 0)
    p4_soc = P4.get("payroll_social", 0)
    p4_rent = P4.get("rent", 0)
    p4_opex = P4.get("opex", 0)
    p4_tax = P4.get("tax_advance", 0)
    p5 = bd["P5"]

    total_receipts = r1 + r2
    total_pay = p1 + p2 + p4_net + p4_soc + p4_rent + p4_opex + p4_tax + p5

    def fmt(v: float, ref: float | None = None) -> str:
        s = f"€{v:>12,.0f}"
        if ref and ref > 0:
            delta = (v - ref) / ref * 100
            s += f"  ({delta:+.0f}% vs run-rate)"
        return s

    print(f"\n{'═'*W}")
    print(f"  {dataset_id}  (engine {ENGINE_VERSION})  [diagnostic only — evaluator view]")
    print(f"  as_of {bd['as_of']}  |  horizon 13 weeks  |  scenario: expected")
    print(f"{'═'*W}")

    print(f"\n{'RECEIPTS':<32} {'Engine 13-wk':>14}  {'Annual×13/52':>14}")
    print(H)
    print(f"  {'R1  open AR (from open invoices at as-of)':<36} {fmt(r1)}")
    print(f"  {'R2  future sales (in-horizon receipts)':<36} {fmt(r2, r2_runrate)}")
    print(f"  {'     R2 note: full 13-wk issue-week net':<36} €{bd['R2_net_all_issues']:>12,.0f}")
    print(f"  {'     (truncation: only ~47% of R2 receipts':<36}")
    print(f"  {'      land in-horizon due to cust terms)':<36}")
    print(H)
    print(f"  {'TOTAL RECEIPTS':<36} {fmt(total_receipts, r2_runrate)}")
    print(f"  {'Open AR at as-of (all, some beyond horizon)':<36} €{bd['open_ar_total']:>12,.0f}")
    print(f"  {'R1 beyond-horizon items':<36}  {bd['beyond_horizon_count']:>12d}")

    print(f"\n{'PAYMENTS':<32} {'Engine 13-wk':>14}  {'Annual×13/52':>14}")
    print(H)
    print(f"  {'P1  open AP (committed at as-of)':<36} {fmt(p1)}")
    print(f"  {'P2  future purchases':<36} {fmt(p2, p2_runrate)}")
    print(f"  {'     P2 note: only issue-wk where supp':<36}")
    print(f"  {'     payment ≤ Dec 27 (correct truncation)':<36}")
    print(f"  {'P4  payroll_net':<36} {fmt(p4_net, p4_net_runrate)}")
    print(f"  {'P4  payroll_social':<36} {fmt(p4_soc, p4_soc_runrate)}")
    print(f"  {'P4  rent':<36} {fmt(p4_rent, p4_rent_runrate)}")
    print(f"  {'P4  opex':<36} {fmt(p4_opex, p4_opex_runrate)}")
    print(f"  {'P4  tax_advance':<36} {fmt(p4_tax, p4_tax_runrate)}")
    print(f"  {'P5  net VAT':<36} {fmt(p5, p5_runrate)}")
    print(H)
    print(f"  {'TOTAL PAYMENTS':<36} {fmt(total_pay, total_pay_runrate)}")
    print(f"  {'Open AP at as-of':<36} €{bd['open_ap_total']:>12,.0f}")

    # P2 / R2_net ratio (key diagnostic)
    r2_net = bd["R2_net_all_issues"]
    ratio = p2 / r2_net if r2_net else 0.0
    print(f"\n  P2 gross / R2 net (all 13 issue-wks) = {ratio:.3f}  "
          f"(expected ≈ 0.43 after fix; <0.36 = P2 bug)")

    # ── Eval comparison ───────────────────────────────────────────────────────
    print(f"\n{'EVAL COMPARISON (hm_evaluator — ground truth)'}")
    print(H)
    fmt2 = lambda eng, ev: f"  engine {eng:>12,.0f}   eval {ev:>12,.0f}   Δ {(eng-ev)/ev*100:+.0f}%" \
        if ev else f"  engine {eng:>12,.0f}   eval {'(none)':>12}"
    print(f"  R1  receipts (open AR paid in horizon) {fmt2(r1, ev['eval_r1'])}")
    print(f"  P1  payments (open AP paid in horizon) {fmt2(p1, ev['eval_p1'])}")
    print(f"  Total AR receipts (R1+R2 engine vs all eval){fmt2(total_receipts, ev['eval_ar_total'])}")
    print(f"  Total AP payments (P1+P2 engine vs all eval){fmt2(p1+p2, ev['eval_ap_total'])}")

    # ── Week 8 detail ─────────────────────────────────────────────────────────
    print(f"\nWEEK 8 (Nov 16–22) PAYMENT DETAIL")
    print(H)
    w8p = bd["week8_pay"]
    if not w8p:
        print("  (no payments)")
    for item in w8p:
        src = item.get("source", "?")
        kind = item.get("kind", item.get("tier", ""))
        amt = float(item["amount"])
        note = f" issue_wk={item.get('issue_week','?')}" if src == "P2" else \
               f" {item.get('due_date','')}" if src == "P1" else \
               f" {item.get('date', '')}"
        print(f"  {src:3}  {kind:<20}  €{amt:>10,.0f}{note}")

    print(f"\nWEEK 8 (Nov 16–22) RECEIPT DETAIL")
    print(H)
    w8r = bd["week8_rec"]
    if not w8r:
        print("  (no receipts)")
    for item in w8r[:6]:
        src = item.get("source", "?")
        amt = float(item["amount"])
        seg = item.get("segment", item.get("cust_code", ""))
        note = f" issue_wk={item.get('issue_week','?')}" if src == "R2" else ""
        print(f"  {src:3}  {seg:<20}  €{amt:>10,.0f}{note}")
    if len(w8r) > 6:
        print(f"  ... and {len(w8r)-6} more R1 items")

    # ── Week 13 detail ────────────────────────────────────────────────────────
    print(f"\nWEEK 13 (Dec 21–27) PAYMENT DETAIL")
    print(H)
    w13p = bd["week13_pay"]
    if not w13p:
        print("  (no payments)")
    for item in w13p:
        src = item.get("source", "?")
        kind = item.get("kind", item.get("tier", ""))
        amt = float(item["amount"])
        note = f" issue_wk={item.get('issue_week','?')}" if src == "P2" else ""
        print(f"  {src:3}  {kind:<20}  €{amt:>10,.0f}{note}")

    print(f"\nWEEK 13 (Dec 21–27) RECEIPT DETAIL")
    print(H)
    w13r = bd["week13_rec"]
    if not w13r:
        print("  (no receipts)")
    for item in w13r[:6]:
        src = item.get("source", "?")
        amt = float(item["amount"])
        seg = item.get("segment", item.get("cust_code", ""))
        note = f" issue_wk={item.get('issue_week','?')}" if src == "R2" else ""
        print(f"  {src:3}  {seg:<20}  €{amt:>10,.0f}{note}")
    if len(w13r) > 6:
        print(f"  ... and {len(w13r)-6} more R1 items")


def main() -> None:
    cfg = load_cfg()
    analyst_eng = sa.create_engine(settings.role_dsn("hm_analyst"), pool_pre_ping=True)
    evaluator_eng = sa.create_engine(settings.role_dsn("hm_evaluator"), pool_pre_ping=True)

    for did in ["S1_normal", "S2_big_customer"]:
        bd = run_component_breakdown(analyst_eng, did)
        ev = eval_comparison(evaluator_eng, analyst_eng, did, bd["as_of"])
        print_report(did, bd, ev, cfg)

    print()


if __name__ == "__main__":
    main()
