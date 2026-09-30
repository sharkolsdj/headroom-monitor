"""
1B tests: public reference data ingestion and sector stress index.

Data source: LUSTAT/STATEC DF_D1312 (2016-2025, all NACE sections).
ECB: deposit facility rate + Euribor 3M (optional).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy import text

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
from config import settings  # noqa: E402
from ingestion.public_data import (
    _load_lustat_csv,
    _compute_stress_indices,
    _parse_lustat_response,
    get_stress_index,
    LUSTAT_SOURCE_URL,
    SEGMENT_NACE_MAP,
    run as run_ingestion,
)

LUSTAT_RAW_CSV = ROOT / "data" / "public" / "raw" / "statec_bankruptcies_lustat_2016_2025.csv"


@pytest.fixture(scope="module")
def owner_engine():
    return sa.create_engine(settings.postgres_dsn, pool_pre_ping=True)


@pytest.fixture(scope="module", autouse=True)
def ingest(owner_engine):
    """Run ingestion once for this module (idempotent on re-run)."""
    run_ingestion(dry_run=False, verbose=False)


# ── test 1: LUSTAT CSV parses correctly ───────────────────────────────────────

def test_lustat_csv_loads_all_sectors():
    """Raw CSV must produce 150 rows (15 NACE codes × 10 years)."""
    rows = _load_lustat_csv()
    assert len(rows) == 150, f"Expected 150 LUSTAT rows, got {len(rows)}"


def test_lustat_csv_correct_source():
    """All rows must carry the LUSTAT source URL."""
    rows = _load_lustat_csv()
    for r in rows:
        assert r.source == "LUSTAT"
        assert r.source_url == LUSTAT_SOURCE_URL


def test_lustat_csv_known_values():
    """Spot-check known figures from the LUSTAT table."""
    rows = _load_lustat_csv()
    by_key = {(r.series_id, r.period): r.value for r in rows}
    assert by_key[("bankruptcies_F",   "2025")] == 164.0, "F 2025 should be 164"
    assert by_key[("bankruptcies_F",   "2024")] == 200.0, "F 2024 should be 200"
    assert by_key[("bankruptcies_L",   "2025")] == 61.0,  "L 2025 should be 61"
    assert by_key[("bankruptcies_G47", "2025")] == 81.0,  "G47 2025 should be 81"
    assert by_key[("bankruptcies_G46", "2025")] == 87.0,  "G46 2025 should be 87"
    assert by_key[("bankruptcies_TOT_X_O_T_U", "2025")] == 1153.0, "TOT 2025 should be 1153"


# ── test 2: stress indices — arithmetic ───────────────────────────────────────

_STRESS_CHECKS = {
    "stress_index_F":           (1.16, 0.01, "Construction"),
    "stress_index_L":           (1.61, 0.01, "Real estate"),
    "stress_index_G47":         (0.99, 0.01, "Retail"),
    "stress_index_TOT_X_O_T_U": (1.07, 0.01, "Total"),
}


@pytest.mark.parametrize("series_id,expected,tol,label", [
    (sid, exp, tol, lbl)
    for sid, (exp, tol, lbl) in _STRESS_CHECKS.items()
])
def test_stress_index_within_tolerance(series_id, expected, tol, label):
    """Stress indices must match expected values within ±0.01."""
    rows = _load_lustat_csv()
    stress = _compute_stress_indices(rows)
    by_id = {r.series_id: r.value for r in stress}
    assert series_id in by_id, f"Missing {series_id}"
    actual = by_id[series_id]
    assert abs(actual - expected) <= tol, (
        f"{label} ({series_id}): expected ~{expected}, got {actual:.6f} "
        f"(diff {abs(actual - expected):.6f} > {tol})"
    )


def test_stress_index_O_is_fixed_one():
    """Public-sector stress index must be the fixed value 1.0."""
    rows = _load_lustat_csv()
    stress = _compute_stress_indices(rows)
    by_id = {r.series_id: r.value for r in stress}
    assert by_id["stress_index_O"] == 1.0, "O (public entities) must be fixed at 1.0"


# ── test 3: segment mapping ───────────────────────────────────────────────────

def test_segment_nace_map_covers_all_customer_segments():
    """SEGMENT_NACE_MAP must cover all 5 customer-segment NACE sub-codes."""
    required = {"F41", "F43", "L68", "G47", "G46.73", "G46.74", "O84"}
    missing = required - set(SEGMENT_NACE_MAP.keys())
    assert not missing, f"Missing NACE sub-codes in SEGMENT_NACE_MAP: {missing}"


def test_get_stress_index_returns_float(owner_engine):
    """get_stress_index must return a float for every mapped segment."""
    for nace_sub in SEGMENT_NACE_MAP:
        val = get_stress_index(nace_sub, owner_engine)
        assert isinstance(val, float), f"Expected float for {nace_sub}, got {type(val)}"
        assert 0.0 < val < 20.0, f"Stress index out of range for {nace_sub}: {val}"


# ── test 4: DB state ──────────────────────────────────────────────────────────

def test_public_series_lustat_row_count(owner_engine):
    """hm.public_series must contain exactly 150 LUSTAT rows."""
    with owner_engine.connect() as conn:
        count = conn.execute(text(
            "SELECT count(*) FROM hm.public_series WHERE source = 'LUSTAT'"
        )).scalar()
    assert count == 150, f"Expected 150 LUSTAT rows, got {count}"


def test_public_series_no_old_statec_rows(owner_engine):
    """Old STATEC (manual CSV) rows must be gone after migration to LUSTAT."""
    with owner_engine.connect() as conn:
        count = conn.execute(text(
            "SELECT count(*) FROM hm.public_series WHERE source = 'STATEC'"
        )).scalar()
    assert count == 0, f"Expected 0 old STATEC rows, found {count}"


def test_public_series_stress_indices_in_db(owner_engine):
    """hm.public_series must contain all 16 derived stress index rows."""
    with owner_engine.connect() as conn:
        count = conn.execute(text("""
            SELECT count(*) FROM hm.public_series
            WHERE source = 'derived' AND series_id LIKE 'stress_index_%'
        """)).scalar()
    assert count >= 16, f"Expected >=16 stress index rows, got {count}"


@pytest.mark.parametrize("series_id,expected,tol", [
    (sid, exp, tol)
    for sid, (exp, tol, _) in _STRESS_CHECKS.items()
])
def test_stress_index_values_in_db(owner_engine, series_id, expected, tol):
    """Stress index values in DB must match expected (within ±0.01)."""
    with owner_engine.connect() as conn:
        val = conn.execute(text("""
            SELECT value FROM hm.public_series
            WHERE source = 'derived' AND series_id = :sid
            ORDER BY period DESC LIMIT 1
        """), {"sid": series_id}).scalar()
    assert val is not None, f"{series_id} not found in hm.public_series"
    assert abs(float(val) - expected) <= tol, (
        f"{series_id}: expected ~{expected}, got {float(val):.6f}"
    )


# ── test 5: idempotency ───────────────────────────────────────────────────────

def test_ingestion_idempotent(owner_engine):
    """Running ingestion twice must not change the total row count."""
    with owner_engine.connect() as conn:
        before = conn.execute(text(
            "SELECT count(*) FROM hm.public_series"
        )).scalar()

    result = run_ingestion(dry_run=False, verbose=False)

    with owner_engine.connect() as conn:
        after = conn.execute(text(
            "SELECT count(*) FROM hm.public_series"
        )).scalar()

    assert after == before, (
        f"Row count changed {before} -> {after} on second run; "
        "ingestion must be idempotent"
    )
    assert result["inserted"] == 0, (
        f"Second run inserted {result['inserted']} new rows; expected 0"
    )
