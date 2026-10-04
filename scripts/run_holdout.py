"""
Phase 3.4 hold-out test: generate H1_drift and H2_sector, run frozen engine, report.

Writes:
  data/demo/H1_drift/forecast.json  (+ customers.json, collections.json)
  data/demo/H2_sector/forecast.json (+ customers.json, collections.json)
  data/demo/holdout_accuracy.csv    — H1 and H2 backtest metrics only
                                      (does NOT overwrite accuracy_summary.csv)

Usage: python scripts/run_holdout.py
"""
from __future__ import annotations

import csv
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import sqlalchemy as sa
from sqlalchemy import text

from config import settings
from engine._behaviour import RecencyBehaviour
from engine._forecast import run_forecast, ENGINE_VERSION
from engine._loader import load_dataset
from engine._writer import write_forecast_to_db, export_forecast_json
from ingestion.generator._pipeline import generate_dataset
from ingestion.generator.scenarios import HOLDOUT_IDS

THRESHOLD   = 509_538.0
DEP_ANNUAL  = 250_000.0
GROSS_MARGIN = 0.30
VAT_RATE    = 0.17
MC_N_RUNS   = 1_000
DEMO        = ROOT / "data" / "demo"


# ── 1. Generate H1 and H2 ────────────────────────────────────────────────────

def generate_holdouts() -> None:
    print("\n=== Phase 3.4 Hold-out: Generating datasets ===\n")
    eng = sa.create_engine(settings.postgres_dsn, pool_pre_ping=True)
    for did in HOLDOUT_IDS:
        print(f"\n{did}")
        result = generate_dataset(did, dry_run=False, verbose=True,
                                  csv_out_dir=ROOT / "data" / "synthetic")
        print(f"  opened_balance={result['opening_balance']:,.0f}  passed={result['passed']}")
        ot = result.get("on_time_check", {})
        if not ot.get("passed", True):
            print(f"  WARNING: on_time check FAILED — {ot.get('weeks_below')}")


# ── 2. Run frozen engine on H1 and H2 ────────────────────────────────────────

def run_engine() -> None:
    print("\n=== Running frozen engine (ENGINE_VERSION={}) ===\n".format(ENGINE_VERSION))
    eng = sa.create_engine(settings.role_dsn("hm_analyst"), pool_pre_ping=True)

    for did in HOLDOUT_IDS:
        print(f"\n{did}")
        data = load_dataset(eng, did)
        opening = data["opening_balance"]

        results = run_forecast(
            did, eng,
            scenarios=["expected", "on_time", "stress"],
            include_mc=True,
            include_stress=True,
            include_assumptions=False,
            include_bridge=False,
            include_collections=True,
            threshold=THRESHOLD,
            dep_annual=DEP_ANNUAL,
            gross_margin=GROSS_MARGIN,
            vat_rate=VAT_RATE,
            mc_n_runs=MC_N_RUNS,
        )

        run_id = write_forecast_to_db(
            eng, did, data["as_of"], ENGINE_VERSION, results, THRESHOLD
        )
        json_path = export_forecast_json(
            did, data["as_of"], ENGINE_VERSION, results, THRESHOLD, opening
        )

        exp = results.get("expected")
        alerts = exp.sector_alerts or [] if exp else []
        w1_closing = exp.p50_weeks[0]["closing"] if exp and exp.p50_weeks else 0
        print(
            f"  run_id={run_id}  W1={w1_closing:,.0f}"
            f"  sector_alerts={len(alerts)}"
            f"  JSON={json_path.relative_to(ROOT)}"
        )
        if alerts:
            for a in alerts:
                print(f"    {a['segment']:24s}  reason={a['reason']:10s}  shift={a['shift_days']:.1f}d")


# ── 3. Hold-out backtest ──────────────────────────────────────────────────────

def _load_forecast(did: str) -> dict:
    path = DEMO / did / "forecast.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def run_holdout_backtest() -> list[dict]:
    print("\n=== Hold-out backtest ===\n")
    eng = sa.create_engine(settings.role_dsn("hm_evaluator"), pool_pre_ping=True)
    rows: list[dict] = []

    with eng.connect() as conn:
        for did in HOLDOUT_IDS:
            try:
                forecast = _load_forecast(did)
            except FileNotFoundError:
                print(f"  SKIP {did}: forecast.json not found")
                continue

            exp_weeks = forecast["scenarios"]["expected"]["weeks"]
            mc_band   = forecast.get("mc_band") or {}
            threshold = forecast["threshold"]
            as_of_str = forecast["as_of"]

            actual_rows = conn.execute(text("""
                SELECT week_start, closing_balance
                FROM eval.future_bank_balances
                WHERE dataset_id = :did
                ORDER BY week_start
            """), {"did": did}).fetchall()
            actual_by_ws = {str(r.week_start): float(r.closing_balance) for r in actual_rows}

            fcst_by_week = {w["week"]: w for w in exp_weeks}

            errors: dict = {}
            pcts: dict   = {}
            for wk_num in (1, 4, 13):
                wk = fcst_by_week.get(wk_num)
                if wk is None:
                    errors[wk_num] = None; pcts[wk_num] = None; continue
                actual = actual_by_ws.get(wk["week_start"])
                if actual is None:
                    errors[wk_num] = None; pcts[wk_num] = None; continue
                err = wk["closing"] - actual
                errors[wk_num] = round(err, 2)
                pcts[wk_num]   = round(100.0 * err / actual, 2) if actual != 0 else None

            inside = 0
            total_w_band = 0
            for wk in exp_weeks:
                ws   = wk["week_start"]
                actual = actual_by_ws.get(ws)
                band   = mc_band.get(str(wk["week"]))
                if actual is not None and band:
                    total_w_band += 1
                    if band["p10"] <= actual <= band["p90"]:
                        inside += 1
            coverage = round(100.0 * inside / total_w_band, 1) if total_w_band > 0 else None

            fcst_thr_wk = next(
                (w["week"] for w in exp_weeks if w["closing"] < threshold), None
            )
            actual_thr_wk = None
            for wk in exp_weeks:
                actual = actual_by_ws.get(wk["week_start"])
                if actual is not None and actual < threshold:
                    actual_thr_wk = wk["week"]
                    break

            false_alarm = sum(
                1 for wk in exp_weeks
                if wk["closing"] < threshold
                and (actual_by_ws.get(wk["week_start"]) or float("inf")) >= threshold
            )

            rows.append({
                "dataset_id": did,
                "error_w1_eur":          errors.get(1),
                "error_w1_pct":          pcts.get(1),
                "error_w4_eur":          errors.get(4),
                "error_w4_pct":          pcts.get(4),
                "error_w13_eur":         errors.get(13),
                "error_w13_pct":         pcts.get(13),
                "band_coverage_pct":     coverage,
                "threshold_week_forecast": fcst_thr_wk,
                "threshold_week_actual":   actual_thr_wk,
                "false_alarm_weeks":     false_alarm,
            })

            print(
                f"  {did:16s}  W1={errors.get(1):>10,.0f} ({pcts.get(1):>+6.1f}%)"
                f"  W4={errors.get(4):>10,.0f} ({pcts.get(4):>+6.1f}%)"
                f"  W13={errors.get(13):>10,.0f} ({pcts.get(13):>+6.1f}%)"
                f"  cov={coverage:>5.1f}%"
                f"  thr_fcst={fcst_thr_wk}  thr_act={actual_thr_wk}"
                f"  fa={false_alarm}"
                if all(v is not None for v in [errors.get(1), errors.get(4), errors.get(13), coverage])
                else f"  {did}: incomplete eval data"
            )

    return rows


# ── 4. Check H1 worsening flag and H2 sector alert ───────────────────────────

def report_flags() -> None:
    print("\n=== H1: is the drifting customer flagged worsening? ===\n")
    analyst_eng = sa.create_engine(settings.role_dsn("hm_analyst"), pool_pre_ping=True)
    eval_eng    = sa.create_engine(settings.role_dsn("hm_evaluator"), pool_pre_ping=True)
    data = load_dataset(analyst_eng, "H1_drift")
    beh  = RecencyBehaviour(analyst_eng, "H1_drift", data["as_of"])

    # Read scenario_truth from DB to find target customer
    with eval_eng.connect() as conn:
        truth_row = conn.execute(text("""
            SELECT truth FROM eval.scenario_truth
            WHERE dataset_id = 'H1_drift'
            ORDER BY created_at DESC LIMIT 1
        """)).fetchone()
    target = None
    if truth_row and truth_row[0]:
        truth = truth_row[0] if isinstance(truth_row[0], dict) else json.loads(truth_row[0])
        target = truth.get("target_customer")

    if target:
        flagged = beh.is_worsening(target)
        typ = beh.typical_delay(target)
        rec = beh.recent_delay(target)
        print(f"  target={target}  worsening={flagged}  typical={typ:.1f}d  recent={rec:.1f}d  delta={rec-typ:+.1f}d")
    else:
        # fallback: check all worsening customers
        worsening = [(cc, beh.typical_delay(cc), beh.recent_delay(cc))
                     for cc, flag in beh.cust_worsening.items() if flag]
        print(f"  (target not in truth, showing all {len(worsening)} worsening)")
        for cc, typ, rec in sorted(worsening, key=lambda x: -(x[2]-x[1]))[:5]:
            print(f"  {cc}  typical={typ:.1f}d  recent={rec:.1f}d  delta={rec-typ:+.1f}d")

    print("\n=== H2: sector alert ===\n")
    h2_path = DEMO / "H2_sector" / "forecast.json"
    if h2_path.exists():
        doc     = json.loads(h2_path.read_text(encoding="utf-8"))
        alerts  = doc.get("sector_alerts") or []
        if alerts:
            for a in alerts:
                print(
                    f"  segment={a['segment']}  n_worsening={a['n_worsening']}"
                    f"  n_customers={a['n_customers']}  reason={a['reason']}"
                    f"  shift={a['shift_days']:.1f}d  statec%={a['statec_stress_pct']:.1f}%"
                )
        else:
            print("  (no sector alerts in forecast.json)")
    else:
        print("  forecast.json not found")


# ── 5. Write holdout_accuracy.csv ────────────────────────────────────────────

def write_holdout_csv(rows: list[dict]) -> Path:
    out = DEMO / "holdout_accuracy.csv"
    fields = [
        "dataset_id",
        "error_w1_eur", "error_w1_pct",
        "error_w4_eur", "error_w4_pct",
        "error_w13_eur", "error_w13_pct",
        "band_coverage_pct",
        "threshold_week_forecast", "threshold_week_actual",
        "false_alarm_weeks",
    ]
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    return out


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    generate_holdouts()
    run_engine()
    rows = run_holdout_backtest()
    report_flags()
    csv_path = write_holdout_csv(rows)
    print(f"\nWrote {csv_path.relative_to(ROOT)}")
    print("\n=== Phase 3.4 complete. Do not tune after this point. ===")
