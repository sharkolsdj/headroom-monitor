"""Regenerate S8_month_end_close forecast.json."""
import io, sys
from pathlib import Path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import sqlalchemy as sa
from config import settings
from engine._forecast import run_forecast, ENGINE_VERSION
from engine._writer import write_forecast_to_db, export_forecast_json
from engine._loader import load_dataset

THRESHOLD = 509_538.0
eng = sa.create_engine(settings.role_dsn("hm_analyst"), pool_pre_ping=True)
did = "S8_month_end_close"
data = load_dataset(eng, did)
results = run_forecast(
    did, eng,
    scenarios=["expected", "on_time", "stress"],
    include_mc=True, include_stress=True, include_collections=True,
    threshold=THRESHOLD, gross_margin=0.30, vat_rate=0.17, mc_n_runs=1000,
)
run_id = write_forecast_to_db(eng, did, data["as_of"], ENGINE_VERSION, results, THRESHOLD)
json_path = export_forecast_json(did, data["as_of"], ENGINE_VERSION, results, THRESHOLD, data["opening_balance"])
print(f"S8 done: run_id={run_id} {json_path.relative_to(ROOT)}")
