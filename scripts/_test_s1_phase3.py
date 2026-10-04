"""Quick smoke test for Phase 3.2 RecencyBehaviour on S1_normal."""
import sys
from pathlib import Path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import sqlalchemy as sa
from config import settings
from engine._forecast import run_forecast
from engine._loader import load_dataset

eng = sa.create_engine(settings.role_dsn("hm_analyst"), pool_pre_ping=True)
data = load_dataset(eng, "S1_normal")
results = run_forecast(
    "S1_normal", eng,
    include_mc=True, include_stress=False, include_collections=True,
    threshold=509538.0,
)
exp = results["expected"]
w1 = exp.p50_weeks[0]
print(f"W1 P50 closing: {w1['closing']:,.0f}")
print(f"Sector alerts:  {exp.sector_alerts}")
import os
demo_dir = ROOT / "data" / "demo" / "S1_normal"
print(f"customers.json: {(demo_dir / 'customers.json').stat().st_size} bytes")
print(f"collections.json: {(demo_dir / 'collections.json').stat().st_size} bytes")
print("PASS")
