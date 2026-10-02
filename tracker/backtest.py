"""
Phase 2C accuracy backtest — connects as hm_evaluator.

Compares the expected-scenario forecast (from data/demo/<id>/forecast.json)
against actual weekly balances in eval.future_bank_balances.

Outputs:
  data/demo/accuracy_summary.csv  — one row per dataset
  Prints week-1 component breakdown for all datasets
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import sqlalchemy as sa
from sqlalchemy import text

from config import settings

DATASET_IDS = [
    "S1_normal",
    "S2_big_customer",
    "S3_sector_crisis",
    "S4_outflow_spike",
    "S5_seasonality",
    "S6_new_customer",
    "S7_partial_payments",
    "S8_month_end_close",
]

EVAL_WEEKS = {1, 4, 13}


def _load_forecast(dataset_id: str) -> dict:
    path = ROOT / "data" / "demo" / dataset_id / "forecast.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _week1_component_breakdown(
    conn: sa.Connection,
    dataset_id: str,
    forecast: dict,
) -> dict:
    """
    Compare week-1 forecast components vs eval actuals.

    R1/R2 split: receipts for invoices issued ≤ as_of = R1; others = R2.
    P1/P2 split: payments for invoices issued ≤ as_of = P1; others = P2.
    P4+P5 = residual (total actual payments - P1_actual - P2_actual).
    """
    as_of_str = forecast["as_of"]
    exp_weeks = forecast["scenarios"]["expected"]["weeks"]
    if not exp_weeks:
        return {}
    w1 = exp_weeks[0]
    week_start = w1["week_start"]
    week_end = w1["week_end"]

    # Forecast components from JSON
    r_by_src = w1.get("receipts_by_source", {})
    p_by_src = w1.get("payments_by_source", {})
    r1_fcst = r_by_src.get("R1", 0.0)
    r2_fcst = r_by_src.get("R2", 0.0)
    p1_fcst = p_by_src.get("P1", 0.0)
    p2_fcst = p_by_src.get("P2", 0.0)
    p4_fcst = p_by_src.get("P4", 0.0)
    p5_fcst = p_by_src.get("P5", 0.0)

    # Open AR invoice IDs at as_of (same logic as loader, but via hm_evaluator)
    open_ar_ids = set(
        row[0] for row in conn.execute(text("""
            SELECT i.invoice_id
            FROM hm.ar_invoices i
            LEFT JOIN hm.ar_receipts r
                ON r.invoice_id = i.invoice_id AND r.dataset_id = i.dataset_id
            WHERE i.dataset_id = :did
              AND i.issue_date <= :as_of
            GROUP BY i.invoice_id, i.amount_gross
            HAVING i.amount_gross - COALESCE(SUM(r.amount), 0.0) > 0.005
        """), {"did": dataset_id, "as_of": as_of_str}).fetchall()
    )

    # Open AP invoice IDs at as_of
    open_ap_ids = set(
        row[0] for row in conn.execute(text("""
            SELECT i.invoice_id
            FROM hm.ap_invoices i
            LEFT JOIN hm.ap_payments p
                ON p.invoice_id = i.invoice_id AND p.dataset_id = i.dataset_id
            WHERE i.dataset_id = :did
              AND i.issue_date <= :as_of
            GROUP BY i.invoice_id, i.amount_gross
            HAVING i.amount_gross - COALESCE(SUM(p.amount), 0.0) > 0.005
        """), {"did": dataset_id, "as_of": as_of_str}).fetchall()
    )

    # Actual AR receipts in week 1
    ar_rows = conn.execute(text("""
        SELECT invoice_id, amount FROM eval.future_ar_receipts
        WHERE dataset_id = :did AND date >= :ws AND date <= :we
    """), {"did": dataset_id, "ws": week_start, "we": week_end}).fetchall()

    r1_actual = sum(float(r.amount) for r in ar_rows if r.invoice_id in open_ar_ids)
    r2_actual = sum(float(r.amount) for r in ar_rows if r.invoice_id not in open_ar_ids)

    # Actual AP payments in week 1
    ap_rows = conn.execute(text("""
        SELECT invoice_id, amount FROM eval.future_ap_payments
        WHERE dataset_id = :did AND date >= :ws AND date <= :we
    """), {"did": dataset_id, "ws": week_start, "we": week_end}).fetchall()

    p1_actual = sum(float(r.amount) for r in ap_rows if r.invoice_id in open_ap_ids)
    p2_actual = sum(float(r.amount) for r in ap_rows if r.invoice_id not in open_ap_ids)

    # Actual closing balance from eval
    actual_bal = conn.execute(text("""
        SELECT closing_balance FROM eval.future_bank_balances
        WHERE dataset_id = :did AND week_start = :ws
        LIMIT 1
    """), {"did": dataset_id, "ws": week_start}).scalar()

    opening = float(forecast["opening_balance"])
    actual_total_receipts = r1_actual + r2_actual
    actual_total_payments_known = p1_actual + p2_actual
    # Residual = opening + total_receipts - closing = total_payments
    if actual_bal is not None:
        actual_total_payments = opening + actual_total_receipts - float(actual_bal)
        p4p5_actual = actual_total_payments - actual_total_payments_known
    else:
        actual_total_payments = None
        p4p5_actual = None

    p4p5_fcst = p4_fcst + p5_fcst

    return {
        "R1": (r1_fcst, r1_actual),
        "R2": (r2_fcst, r2_actual),
        "P1": (p1_fcst, p1_actual),
        "P2": (p2_fcst, p2_actual),
        "P4+P5": (p4p5_fcst, p4p5_actual),
        "total_receipts": (r1_fcst + r2_fcst, actual_total_receipts),
        "total_payments": (p1_fcst + p2_fcst + p4p5_fcst, actual_total_payments),
    }


def run_backtest() -> list[dict]:
    eng = sa.create_engine(settings.role_dsn("hm_evaluator"), pool_pre_ping=True)
    rows: list[dict] = []

    print("=== Accuracy Backtest (Phase 2C) ===\n")

    with eng.connect() as conn:
        for did in DATASET_IDS:
            try:
                forecast = _load_forecast(did)
            except FileNotFoundError:
                print(f"  SKIP {did}: forecast.json not found")
                continue

            exp_weeks = forecast["scenarios"]["expected"]["weeks"]
            mc_band = forecast.get("mc_band") or {}
            threshold = forecast["threshold"]

            # Actual closing balances from eval
            actual_rows = conn.execute(text("""
                SELECT week_start, closing_balance
                FROM eval.future_bank_balances
                WHERE dataset_id = :did
                ORDER BY week_start
            """), {"did": did}).fetchall()
            actual_by_ws = {str(r.week_start): float(r.closing_balance) for r in actual_rows}

            # Map forecast weeks by week number
            fcst_by_week: dict[int, dict] = {w["week"]: w for w in exp_weeks}

            errors: dict[int, float | None] = {}
            pcts: dict[int, float | None] = {}
            for wk_num in (1, 4, 13):
                wk = fcst_by_week.get(wk_num)
                if wk is None:
                    errors[wk_num] = None
                    pcts[wk_num] = None
                    continue
                actual = actual_by_ws.get(wk["week_start"])
                if actual is None:
                    errors[wk_num] = None
                    pcts[wk_num] = None
                    continue
                err = wk["closing"] - actual
                errors[wk_num] = round(err, 2)
                pcts[wk_num] = round(100.0 * err / actual, 2) if actual != 0 else None

            # Band coverage: share of weeks where actual in [P10, P90]
            inside = 0
            total_w_band = 0
            for wk in exp_weeks:
                ws = wk["week_start"]
                k_str = str(wk["week"])
                actual = actual_by_ws.get(ws)
                band = mc_band.get(k_str)
                if actual is not None and band:
                    total_w_band += 1
                    if band["p10"] <= actual <= band["p90"]:
                        inside += 1
            coverage = round(100.0 * inside / total_w_band, 1) if total_w_band > 0 else None

            # First week below threshold (P50 forecast vs actual)
            fcst_thr_wk = next(
                (w["week"] for w in exp_weeks if w["closing"] < threshold), None
            )
            actual_thr_wk = None
            for wk in exp_weeks:
                actual = actual_by_ws.get(wk["week_start"])
                if actual is not None and actual < threshold:
                    actual_thr_wk = wk["week"]
                    break

            # False alarms: P50 below threshold while actual is above
            false_alarm = sum(
                1 for wk in exp_weeks
                if wk["closing"] < threshold
                and (actual_by_ws.get(wk["week_start"]) or float("inf")) >= threshold
            )

            rows.append({
                "dataset_id": did,
                "error_w1_eur": errors.get(1),
                "error_w1_pct": pcts.get(1),
                "error_w4_eur": errors.get(4),
                "error_w4_pct": pcts.get(4),
                "error_w13_eur": errors.get(13),
                "error_w13_pct": pcts.get(13),
                "band_coverage_pct": coverage,
                "threshold_week_forecast": fcst_thr_wk,
                "threshold_week_actual": actual_thr_wk,
                "false_alarm_weeks": false_alarm,
            })

            print(
                f"  {did:28s}  W1={errors.get(1):>10,.0f} ({pcts.get(1):>+6.1f}%)  "
                f"W4={errors.get(4):>10,.0f} ({pcts.get(4):>+6.1f}%)  "
                f"W13={errors.get(13):>10,.0f} ({pcts.get(13):>+6.1f}%)  "
                f"cov={coverage:>5.1f}%"
                if all(v is not None for v in [errors.get(1), errors.get(4), errors.get(13), coverage])
                else f"  {did}: incomplete eval data"
            )

        print()
        print("=== Week-1 Component Breakdown ===")
        hdr = f"{'Dataset':28s}  {'R1_f':>10}  {'R1_a':>10}  {'R2_f':>10}  {'R2_a':>10}  {'P1_f':>10}  {'P1_a':>10}  {'P2_f':>10}  {'P2_a':>10}  {'P4+P5_f':>10}  {'P4+P5_a':>10}"
        print(hdr)
        print("-" * len(hdr))
        for did in DATASET_IDS:
            try:
                forecast = _load_forecast(did)
            except FileNotFoundError:
                continue
            bd = _week1_component_breakdown(conn, did, forecast)
            if not bd:
                continue
            def _fmt(val):
                if val is None:
                    return f"{'n/a':>10}"
                return f"{val:>10,.0f}"

            print(
                f"  {did:28s}"
                f"  {_fmt(bd['R1'][0])}  {_fmt(bd['R1'][1])}"
                f"  {_fmt(bd['R2'][0])}  {_fmt(bd['R2'][1])}"
                f"  {_fmt(bd['P1'][0])}  {_fmt(bd['P1'][1])}"
                f"  {_fmt(bd['P2'][0])}  {_fmt(bd['P2'][1])}"
                f"  {_fmt(bd['P4+P5'][0])}  {_fmt(bd['P4+P5'][1])}"
            )

    return rows


def write_csv(rows: list[dict]) -> Path:
    out_dir = ROOT / "data" / "demo"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "accuracy_summary.csv"
    fields = [
        "dataset_id",
        "error_w1_eur", "error_w1_pct",
        "error_w4_eur", "error_w4_pct",
        "error_w13_eur", "error_w13_pct",
        "band_coverage_pct",
        "threshold_week_forecast", "threshold_week_actual",
        "false_alarm_weeks",
    ]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    return out_path


if __name__ == "__main__":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    rows = run_backtest()
    path = write_csv(rows)
    print(f"\nWrote {path}")
