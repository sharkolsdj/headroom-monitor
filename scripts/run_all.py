"""
Regenerate ALL demo outputs from a clean state.

Steps:
  1. run_3.py  — all 8 forecast.json + customers.json + collections.json + accuracy_summary.csv
  2. chart_all.py — all charts

Usage: python scripts/run_all.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
PY = sys.executable


def _run(script: str) -> None:
    print(f"\n{'='*60}\n  {script}\n{'='*60}", flush=True)
    result = subprocess.run(
        [PY, str(ROOT / "scripts" / script)],
        cwd=str(ROOT),
    )
    if result.returncode != 0:
        sys.exit(result.returncode)


if __name__ == "__main__":
    _run("run_3.py")
    _run("chart_all.py")
    print("\nrun_all complete.")
