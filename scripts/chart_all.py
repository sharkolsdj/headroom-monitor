"""
Generate review charts for all 8 datasets → docs/img/<id>_forecast.png
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import matplotlib
matplotlib.use("Agg")

import sqlalchemy as sa
from config import settings
from scripts.chart_s2 import make_chart
from ingestion.generator.scenarios import SCENARIO_IDS


def main() -> None:
    for did in SCENARIO_IDS:
        out = ROOT / "docs" / "img" / f"{did}_forecast.png"
        try:
            make_chart(did, out)
        except Exception as exc:
            print(f"ERROR {did}: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
