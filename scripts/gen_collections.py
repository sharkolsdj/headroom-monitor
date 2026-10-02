"""
Generate customers.json and collections.json for all datasets
using existing forecast.json for the MC band (no re-run).

Usage: python scripts/gen_collections.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import sqlalchemy as sa

from config import settings
from engine._behaviour import RecencyBehaviour
from engine._collections import (
    build_customers_json,
    build_collections_json,
    write_customers_json,
    write_collections_json,
)
from engine._forecast import ENGINE_VERSION
from engine._loader import load_dataset
from engine._sector import detect_sector_trends, load_statec_stress
from ingestion.generator.scenarios import SCENARIO_IDS

THRESHOLD = 509_538.0


def _load_mc_band(dataset_id: str) -> dict[int, dict] | None:
    path = ROOT / "data" / "demo" / dataset_id / "forecast.json"
    if not path.exists():
        return None
    doc = json.loads(path.read_text(encoding="utf-8"))
    mc = doc.get("mc_band")
    if not mc:
        return None
    return {int(k): v for k, v in mc.items()}


def run_all() -> None:
    eng = sa.create_engine(settings.role_dsn("hm_analyst"), pool_pre_ping=True)
    statec_stress = load_statec_stress()

    for did in SCENARIO_IDS:
        print(f"{did}...", end="", flush=True)
        data = load_dataset(eng, did)
        as_of = data["as_of"]

        beh_pass1 = RecencyBehaviour(eng, did, as_of)
        _slowing, _shift, _ = detect_sector_trends(
            cust_worsening=beh_pass1.cust_worsening,
            cust_recent_mean=beh_pass1.cust_recent_mean,
            cust_longrun_mean=beh_pass1.cust_longrun_mean,
            cust_seg=beh_pass1.cust_seg,
            seg_pool_entries=beh_pass1.seg_pool_entries,
            as_of=as_of,
            statec_stress=statec_stress,
        )
        behaviour = RecencyBehaviour(eng, did, as_of, sector_slowing=_slowing, sector_shift=_shift)

        mc_band = _load_mc_band(did)
        demo_dir = ROOT / "data" / "demo" / did

        customers = build_customers_json(
            open_ar=data["open_ar"],
            history_ar=data["history_ar"],
            behaviour=behaviour,
            as_of=as_of,
            mc_band=mc_band,
            mc_threshold=THRESHOLD,
        )
        collections = build_collections_json(
            open_ar=data["open_ar"],
            behaviour=behaviour,
            as_of=as_of,
            mc_band=mc_band,
            mc_threshold=THRESHOLD,
        )
        write_customers_json(customers, demo_dir / "customers.json")
        write_collections_json(collections, demo_dir / "collections.json")
        print(f" {len(customers)} customers, {len(collections)} collections")


if __name__ == "__main__":
    run_all()
