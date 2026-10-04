"""Quick smoke test for Phase 3.2 on S7_partial_payments."""
import sys
from pathlib import Path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import sqlalchemy as sa
from config import settings
from engine._forecast import run_forecast

eng = sa.create_engine(settings.role_dsn("hm_analyst"), pool_pre_ping=True)
try:
    results = run_forecast(
        "S7_partial_payments", eng,
        include_mc=True, include_stress=False,
        threshold=509538.0,
    )
    exp = results["expected"]
    w1 = exp.p50_weeks[0]
    print(f"S7 W1 P50: {w1['closing']:,.0f}")
    print(f"S7 sector_alerts: {exp.sector_alerts}")
    print("S7 PASS")
except Exception as e:
    import traceback
    traceback.print_exc()
    print(f"S7 FAIL: {e}")
