"""
Phase 3: run all 8 datasets with RecencyBehaviour, generate all demo files.

Generates per dataset:
  data/demo/<id>/forecast.json
  data/demo/<id>/customers.json
  data/demo/<id>/collections.json

Usage: python scripts/run_3.py
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import sqlalchemy as sa

from config import settings
from engine._forecast import run_forecast, ENGINE_VERSION
from engine._writer import write_forecast_to_db, export_forecast_json
from engine._loader import load_dataset
from ingestion.generator.scenarios import SCENARIO_IDS

THRESHOLD = 509_538.0
DEP_ANNUAL = 250_000.0
GROSS_MARGIN = 0.30
VAT_RATE = 0.17
MC_N_RUNS = 1_000


def run_all() -> None:
    eng = sa.create_engine(settings.role_dsn("hm_analyst"), pool_pre_ping=True)

    for did in SCENARIO_IDS:
        print(f"\n{did}")
        data = load_dataset(eng, did)
        opening = data["opening_balance"]

        results = run_forecast(
            did, eng,
            scenarios=["expected", "on_time", "stress"],
            include_mc=True,
            include_stress=True,
            include_assumptions=True,
            include_bridge=True,
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

    print("\nBacktest")
    from tracker.backtest import run_backtest, write_csv
    rows = run_backtest()
    csv_path = write_csv(rows)
    print(f"  Accuracy: {csv_path.relative_to(ROOT)}")


if __name__ == "__main__":
    run_all()
