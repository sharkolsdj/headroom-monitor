"""
Phase 2C: run all 8 datasets, write DB + JSON, generate charts.

Usage: python scripts/run_2c.py
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import matplotlib
matplotlib.use("Agg")
import sqlalchemy as sa

from config import settings
from engine._forecast import run_forecast, ENGINE_VERSION
from engine._writer import write_forecast_to_db, export_forecast_json
from engine._loader import load_dataset
from ingestion.generator.scenarios import SCENARIO_IDS
from scripts.chart_s2 import make_chart

THRESHOLD = 509_538.0
DEP_ANNUAL = 250_000.0
GROSS_MARGIN = 0.30
VAT_RATE = 0.17
MC_N_RUNS = 1_000


def run_all() -> None:
    eng = sa.create_engine(settings.role_dsn("hm_analyst"), pool_pre_ping=True)

    for did in SCENARIO_IDS:
        print(f"\n── {did} ──────────────────────────────────────────")
        data = load_dataset(eng, did)
        opening = data["opening_balance"]

        results = run_forecast(
            did, eng,
            scenarios=["expected", "on_time", "stress"],
            include_mc=True,
            include_stress=True,
            include_assumptions=(did == "S2_big_customer"),
            include_bridge=(did == "S2_big_customer"),
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
        print(f"  DB run_id={run_id}   JSON: {json_path.relative_to(ROOT)}")

        chart_path = ROOT / "docs" / "img" / f"{did}_forecast.png"
        try:
            make_chart(did, chart_path)
        except Exception as exc:
            print(f"  Chart error: {exc}", file=sys.stderr)

    print("\n── S2 Illustrative Dataset ──────────────────────────────")
    from scripts.gen_illustrative_s2 import generate
    readme = generate()
    print(f"  {readme.relative_to(ROOT)}")

    print("\n── Backtest ─────────────────────────────────────────────")
    from tracker.backtest import run_backtest, write_csv
    rows = run_backtest()
    csv_path = write_csv(rows)
    print(f"\n  Accuracy summary: {csv_path.relative_to(ROOT)}")


if __name__ == "__main__":
    run_all()
