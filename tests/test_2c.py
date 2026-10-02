"""Phase 2C tests: DB writer, JSON export, accuracy backtest."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy import text

ROOT = Path(__file__).parent.parent

DEMO_DIR = ROOT / "data" / "demo"
DATASETS = [
    "S1_normal",
    "S2_big_customer",
    "S3_sector_crisis",
    "S4_outflow_spike",
    "S5_seasonality",
    "S6_new_customer",
    "S7_partial_payments",
    "S8_month_end_close",
]


# ── Writer tests ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("dataset_id", DATASETS)
def test_forecast_json_exists(dataset_id):
    path = DEMO_DIR / dataset_id / "forecast.json"
    assert path.exists(), f"forecast.json missing for {dataset_id}"


@pytest.mark.parametrize("dataset_id", DATASETS)
def test_forecast_json_structure(dataset_id):
    path = DEMO_DIR / dataset_id / "forecast.json"
    if not path.exists():
        pytest.skip("forecast.json not yet generated")
    doc = json.loads(path.read_text(encoding="utf-8"))

    assert doc["dataset_id"] == dataset_id
    assert "scenarios" in doc
    assert "expected" in doc["scenarios"]
    assert "on_time" in doc["scenarios"]
    assert "stress" in doc["scenarios"]

    exp_weeks = doc["scenarios"]["expected"]["weeks"]
    assert len(exp_weeks) == 13

    for wk in exp_weeks:
        assert "week" in wk
        assert "closing" in wk
        assert "receipts_by_source" in wk
        assert "payments_by_source" in wk


@pytest.mark.parametrize("dataset_id", DATASETS)
def test_forecast_json_balance_conservation(dataset_id):
    path = DEMO_DIR / dataset_id / "forecast.json"
    if not path.exists():
        pytest.skip("forecast.json not yet generated")
    doc = json.loads(path.read_text(encoding="utf-8"))
    opening = doc["opening_balance"]

    for scenario in ("expected", "on_time", "stress"):
        weeks = doc["scenarios"][scenario]["weeks"]
        prev_close = opening
        for wk in weeks:
            expected_close = prev_close + wk["receipts"] - wk["payments"]
            assert abs(wk["closing"] - expected_close) < 1.0, (
                f"{dataset_id}/{scenario} week {wk['week']}: "
                f"balance conservation violated"
            )
            prev_close = wk["closing"]


def test_mc_band_in_s2_json():
    path = DEMO_DIR / "S2_big_customer" / "forecast.json"
    if not path.exists():
        pytest.skip("forecast.json not yet generated")
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc.get("mc_band") is not None
    band = doc["mc_band"]
    assert len(band) == 13
    for k, b in band.items():
        assert b["p10"] <= b["p50"] <= b["p90"], f"Band ordering violated at week {k}"


def test_bridge_in_s2_json():
    path = DEMO_DIR / "S2_big_customer" / "forecast.json"
    if not path.exists():
        pytest.skip("forecast.json not yet generated")
    doc = json.loads(path.read_text(encoding="utf-8"))
    bridge = doc.get("bridge")
    assert bridge is not None and len(bridge) > 0
    for row in bridge:
        assert abs(row["reconciliation_error"]) < 0.01, (
            f"Bridge reconciliation error {row['reconciliation_error']} in {row['month']}"
        )


def test_assumptions_in_s2_json():
    path = DEMO_DIR / "S2_big_customer" / "forecast.json"
    if not path.exists():
        pytest.skip("forecast.json not yet generated")
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc.get("assumptions") is not None
    assert len(doc["assumptions"]) >= 10


# ── DB tests ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def analyst_engine():
    from config import settings
    return sa.create_engine(settings.role_dsn("hm_analyst"), pool_pre_ping=True)


@pytest.fixture(scope="module")
def written_run_ids(analyst_engine):
    """Write S1 and S2 forecasts to DB; return {dataset_id: run_id}."""
    from engine._forecast import run_forecast, ENGINE_VERSION
    from engine._writer import write_forecast_to_db
    from engine._loader import load_dataset

    run_ids: dict[str, int] = {}
    for did in ["S1_normal", "S2_big_customer"]:
        data = load_dataset(analyst_engine, did)
        results = run_forecast(did, analyst_engine, scenarios=["expected", "on_time", "stress"],
                               include_stress=True, threshold=509_538.0)
        run_id = write_forecast_to_db(analyst_engine, did, data["as_of"],
                                      ENGINE_VERSION, results, 509_538.0)
        run_ids[did] = run_id
    return run_ids


def test_forecast_runs_in_db(analyst_engine, written_run_ids):
    run_id_list = list(written_run_ids.values())
    with analyst_engine.connect() as conn:
        count = conn.execute(text(
            "SELECT COUNT(*) FROM hm.forecast_runs WHERE run_id = ANY(:ids)"
        ), {"ids": run_id_list}).scalar()
    assert count == len(written_run_ids), (
        f"Expected {len(written_run_ids)} runs in DB, found {count}"
    )


def test_forecast_lines_in_db(analyst_engine, written_run_ids):
    run_id_list = list(written_run_ids.values())
    with analyst_engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT fl.scenario, COUNT(*) AS n
            FROM hm.forecast_lines fl
            WHERE fl.run_id = ANY(:ids)
            GROUP BY fl.scenario
        """), {"ids": run_id_list}).fetchall()
    scenarios = {r.scenario: r.n for r in rows}
    n_datasets = len(written_run_ids)
    for scen in ("expected", "on_time", "stress"):
        assert scen in scenarios, f"Scenario {scen} missing in DB"
        assert scenarios[scen] == 13 * n_datasets, (
            f"Expected {13 * n_datasets} {scen} lines, got {scenarios[scen]}"
        )


# ── Accuracy summary tests ────────────────────────────────────────────────────

def test_accuracy_summary_exists():
    path = DEMO_DIR / "accuracy_summary.csv"
    assert path.exists(), "accuracy_summary.csv not found"


def test_accuracy_summary_columns():
    import csv
    path = DEMO_DIR / "accuracy_summary.csv"
    if not path.exists():
        pytest.skip("accuracy_summary.csv not yet generated")
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    assert len(rows) == len(DATASETS)
    required = {"dataset_id", "error_w1_eur", "error_w1_pct", "band_coverage_pct"}
    assert required.issubset(set(rows[0].keys()))


# ── Illustrative dataset ──────────────────────────────────────────────────────

def test_s2_illustrative_readme_exists():
    path = ROOT / "data" / "illustrative" / "S2" / "README.md"
    assert path.exists(), "S2 illustrative README.md missing"


def test_s2_illustrative_readme_has_sections():
    path = ROOT / "data" / "illustrative" / "S2" / "README.md"
    if not path.exists():
        pytest.skip("README.md not yet generated")
    content = path.read_text(encoding="utf-8")
    for section in ("Opening position", "Top 10 customers", "Open invoices",
                     "Planned payments", "Recurring outflows"):
        assert section in content, f"Missing section: {section}"
