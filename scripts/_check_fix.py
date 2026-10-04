"""Quick check: S1_normal week-1 before/after the two bug fixes."""
import sys
from pathlib import Path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import sqlalchemy as sa
from engine._forecast import run_forecast
from config import settings

eng = sa.create_engine(settings.role_dsn("hm_analyst"), pool_pre_ping=True)
result = run_forecast(
    "S1_normal", eng,
    include_mc=True, include_stress=False,
    include_assumptions=False, include_bridge=False
)
exp = result["expected"]
w1 = exp.p50_weeks[0]
actual_closing = 1185842.95 + 224750.09  # from accuracy_summary.csv: error = -224750
print(f"W1 P50 closing (after fix): {w1['closing']:,.0f}")
print(f"Actual closing (from backtest): {actual_closing:,.0f}")
print(f"Error EUR: {w1['closing'] - actual_closing:,.0f}")
print(f"Error pct: {100*(w1['closing'] - actual_closing)/actual_closing:+.1f}%")
print(f"(Before: -224750 EUR, -15.9%)")
