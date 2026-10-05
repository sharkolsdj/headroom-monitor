"""
Export data/demo/<id>/actual.json for S1-S8, H1, H2.

Output per dataset:
  { "dataset_id": "...", "as_of": "YYYY-MM-DD",
    "weeks": [ {"week": N, "week_start": "YYYY-MM-DD", "closing_balance": X}, ... ] }

Connects as hm_evaluator (read-only access to eval schema).
Week numbers are taken from the matching forecast.json so the numbering
is consistent with forecast outputs.

Usage: python scripts/export_actuals.py
"""
from __future__ import annotations

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
from ingestion.generator.scenarios import HOLDOUT_IDS, SCENARIO_IDS

ALL_IDS = SCENARIO_IDS + HOLDOUT_IDS
DEMO = ROOT / "data" / "demo"


def _load_forecast(did: str) -> dict:
    path = DEMO / did / "forecast.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def export_actuals() -> None:
    eng = sa.create_engine(settings.role_dsn("hm_evaluator"), pool_pre_ping=True)

    with eng.connect() as conn:
        for did in ALL_IDS:
            try:
                forecast = _load_forecast(did)
            except FileNotFoundError:
                print(f"  SKIP {did}: forecast.json not found")
                continue

            as_of = forecast["as_of"]
            exp_weeks = forecast["scenarios"]["expected"]["weeks"]
            week_num_by_ws = {w["week_start"]: w["week"] for w in exp_weeks}

            rows = conn.execute(text("""
                SELECT week_start, closing_balance
                FROM eval.future_bank_balances
                WHERE dataset_id = :did
                ORDER BY week_start
            """), {"did": did}).fetchall()

            weeks = []
            for r in rows:
                ws = str(r.week_start)
                week_num = week_num_by_ws.get(ws)
                if week_num is None:
                    continue
                weeks.append({
                    "week": week_num,
                    "week_start": ws,
                    "closing_balance": round(float(r.closing_balance), 2),
                })

            out = {
                "dataset_id": did,
                "as_of": as_of,
                "weeks": weeks,
            }

            out_path = DEMO / did / "actual.json"
            out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
            print(f"  {did:28s}  {len(weeks):2d} weeks → {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    print("=== Export actuals (hm_evaluator) ===\n")
    export_actuals()
    print("\nDone.")
