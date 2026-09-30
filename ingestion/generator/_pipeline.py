"""Orchestrate one dataset: load cfg → build counterparties → simulate → check → write."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from config import settings  # noqa: E402
import sqlalchemy as sa

from ._cfg import load as load_cfg
from .counterparties import build_customers, build_suppliers
from .simulation import simulate
from .scenarios import build_params
from .checks import run_checks
from .writer import write_to_db, export_csvs


def generate_dataset(dataset_id: str, dry_run: bool = False,
                     verbose: bool = True) -> dict:
    # 1. Load config
    cfg = load_cfg()
    seed = cfg.seed + _SEED_OFFSETS[dataset_id]

    # 2. Build scenario params
    params = build_params(dataset_id, cfg.as_of_date)

    # 3. Load stress indices from DB
    stress_map = _load_stress_map(cfg)

    # 4. Build counterparties (deterministic)
    import numpy as np
    rng = np.random.default_rng(seed)
    customers = build_customers(cfg, rng, cfg.history_start, stress_map)
    suppliers = build_suppliers(cfg, rng)

    # 4b. S3: inject excluded top-5 codes and stress index BEFORE simulation
    if dataset_id == "S3_sector_crisis" and params.sector_crisis:
        top5_codes = {c.code for c in
                      sorted(customers, key=lambda c: c.annual_revenue, reverse=True)[:5]}
        params.sector_crisis["excluded_top5"] = top5_codes
        # Use DB stress index for F41 if available; fall back to YAML default
        db_stress = stress_map.get("F41", params.sector_crisis.get("stress_index", 1.16))
        params.sector_crisis["stress_index"] = db_stress

    # 5. Simulate
    result = simulate(cfg, dataset_id, seed, customers, suppliers, params)

    # 6. Run acceptance checks
    checks_result = run_checks(result, cfg)
    if verbose:
        status = "PASS" if checks_result.get("passed") else "FAIL"
        print(f"  Acceptance check: {status} — {checks_result.get('check', '')}")
        if not checks_result.get("passed"):
            print(f"  Details: {checks_result}")

    # 7. Write to DB and export CSVs
    row_counts: dict = {}
    if not dry_run:
        row_counts = write_to_db(result, verbose=verbose)

    export_csvs(result, checks_result, verbose=verbose)

    # as_of balance = balance at end of history_end (last Sunday before as_of Monday)
    from datetime import timedelta
    history_end_monday = cfg.as_of_date - timedelta(weeks=1)
    as_of_bal = result.weekly_balances.get(history_end_monday, 0.0)

    return {
        "checks": checks_result,
        "rows": row_counts,
        "passed": checks_result.get("passed", False),
        "dataset_id": dataset_id,
        "opening_balance": round(result.opening_balance, 2),
        "as_of_balance": round(as_of_bal, 2),
    }


def _load_stress_map(cfg) -> dict[str, float]:
    """Load stress indices from hm.public_series; fall back to 1.0."""
    try:
        from ingestion.public_data import SEGMENT_NACE_MAP, get_stress_index
        engine = sa.create_engine(settings.postgres_dsn, pool_pre_ping=True)
        return {nace: get_stress_index(nace, engine) for nace in SEGMENT_NACE_MAP}
    except Exception:
        return {}


from .scenarios import SEED_OFFSETS as _SEED_OFFSETS
