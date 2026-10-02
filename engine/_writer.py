"""
Write forecast results to hm.forecast_runs / hm.forecast_lines (as hm_analyst)
and export data/demo/<dataset_id>/forecast.json.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy import text

ROOT = Path(__file__).parent.parent


def _date_serial(obj: Any) -> str:
    if isinstance(obj, date):
        return obj.isoformat()
    raise TypeError(f"Not JSON serializable: {type(obj)}")


def _summarise_items(items: list[dict]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for item in items:
        src = item.get("source", "other")
        totals[src] = totals.get(src, 0.0) + float(item["amount"])
    return {k: round(v, 2) for k, v in totals.items()}


def _weeks_for_json(weeks: list[dict]) -> list[dict]:
    out = []
    for wk in weeks:
        row: dict[str, Any] = {
            "week": wk["week"],
            "week_start": wk["week_start"],
            "week_end": wk["week_end"],
            "opening": wk["opening"],
            "receipts": wk["receipts"],
            "payments": wk["payments"],
            "closing": wk["closing"],
            "receipts_by_source": _summarise_items(wk.get("receipt_items", [])),
            "payments_by_source": _summarise_items(wk.get("payment_items", [])),
        }
        out.append(row)
    return out


def write_forecast_to_db(
    sa_engine: sa.Engine,
    dataset_id: str,
    as_of: date,
    engine_version: str,
    results: dict,
    threshold: float,
) -> int:
    """Insert into hm.forecast_runs + hm.forecast_lines. Returns run_id."""
    exp = results.get("expected")
    mc_band = exp.mc_band if exp else None

    params_doc = json.dumps({"threshold": threshold})
    with sa_engine.begin() as conn:
        run_id = conn.execute(text("""
            INSERT INTO hm.forecast_runs (dataset_id, as_of, engine_version, params)
            VALUES (:did, :as_of, :ver, CAST(:params AS JSONB))
            RETURNING run_id
        """), {"did": dataset_id, "as_of": as_of, "ver": engine_version,
               "params": params_doc}).scalar()

        for scenario, result in results.items():
            for wk in result.weeks:
                k = wk["week"]
                band = (mc_band or {}).get(k, {}) if scenario == "expected" else {}
                comp = {
                    "receipts_by_source": _summarise_items(wk.get("receipt_items", [])),
                    "payments_by_source": _summarise_items(wk.get("payment_items", [])),
                }
                conn.execute(text("""
                    INSERT INTO hm.forecast_lines
                        (run_id, week_start, scenario, value,
                         p10, p50, p90, p_below_threshold, components)
                    VALUES
                        (:run_id, :ws, :scen, :val,
                         :p10, :p50, :p90, :pbt, CAST(:comp AS JSONB))
                """), {
                    "run_id": run_id,
                    "ws": wk["week_start"],
                    "scen": scenario,
                    "val": round(wk["closing"], 2),
                    "p10": round(band.get("p10", wk["closing"]), 2),
                    "p50": round(band.get("p50", wk["closing"]), 2),
                    "p90": round(band.get("p90", wk["closing"]), 2),
                    "pbt": round(band.get("p_below_threshold", 0.0), 6),
                    "comp": json.dumps(comp),
                })

    return run_id


def export_forecast_json(
    dataset_id: str,
    as_of: date,
    engine_version: str,
    results: dict,
    threshold: float,
    opening_balance: float,
) -> Path:
    """Export data/demo/<dataset_id>/forecast.json. Returns path."""
    out_dir = ROOT / "data" / "demo" / dataset_id
    out_dir.mkdir(parents=True, exist_ok=True)

    exp = results.get("expected")
    mc_band_doc = None
    if exp and exp.mc_band:
        mc_band_doc = {str(k): v for k, v in exp.mc_band.items()}

    doc: dict[str, Any] = {
        "dataset_id": dataset_id,
        "as_of": as_of.isoformat(),
        "engine_version": engine_version,
        "generated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "threshold": threshold,
        "opening_balance": opening_balance,
        "scenarios": {
            scen: {
                "weeks": _weeks_for_json(res.weeks),
                "beyond_horizon_count": len(res.beyond_horizon),
                "applied_overrides_count": len(res.applied_overrides),
            }
            for scen, res in results.items()
        },
        "mc_band": mc_band_doc,
        "bridge": exp.bridge if exp else None,
        "assumptions": exp.assumptions if exp else None,
        "applied_overrides": exp.applied_overrides if exp else [],
    }

    out_path = out_dir / "forecast.json"
    out_path.write_text(json.dumps(doc, default=_date_serial, indent=2), encoding="utf-8")
    return out_path
