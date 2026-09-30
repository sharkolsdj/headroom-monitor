"""
1B tests: public reference data ingestion and sector stress index.
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
    _load_statec_manual,
    _compute_stress_indices,
    run as run_ingestion,
)


@pytest.fixture(scope="module")
def owner_engine():
    return sa.create_engine(settings.postgres_dsn, pool_pre_ping=True)


@pytest.fixture(scope="module", autouse=True)
def ingest(owner_engine):
    """Run the ingestion once for this test module."""
    run_ingestion(dry_run=False, verbose=False)


# ── test 1: manual CSV has the verified figures ───────────────────────────────

def test_manual_csv_verified_figures():
    """Known STATEC figures must be present and correct in the manual CSV."""
    rows, _ = _load_statec_manual()
    by_key = {(r.series_id.split("_")[-1], int(r.period)): r.value for r in rows}
    # F 2025 = 165, F 2024 = 197
    assert by_key.get(("F", 2025)) == 165.0, "F 2025 should be 165"
    assert by_key.get(("F", 2024)) == 197.0, "F 2024 should be 197"
    # ALL 2025 = 1187
    assert by_key.get(("ALL", 2025)) == 1187.0, "ALL 2025 should be 1187"


# ── test 2: FILL_IN rows are detected and reported ────────────────────────────

def test_manual_csv_fill_in_warnings():
    """FILL_IN values must not be loaded as rows but must appear as warnings."""
    rows, warnings = _load_statec_manual()
    assert warnings, "Expected at least one FILL_IN warning from the manual CSV"
    # All loaded rows must have numeric values
    for r in rows:
        assert isinstance(r.value, float), f"Non-numeric value loaded: {r}"


# ── test 3: stress index is computable from partial data ──────────────────────

def test_stress_index_computed():
    """Stress index for section F must be computed (F 2024 and 2025 both present)."""
    rows, _ = _load_statec_manual()
    stress = _compute_stress_indices(rows)
    stress_f = [r for r in stress if "stress_index_F" in r.series_id]
    assert stress_f, "No stress_index_F row produced"
    idx = stress_f[0]
    # With only F 2025=165 / avg([2024=197]) = 0.837...
    assert 0.0 < idx.value < 10.0, f"Stress index out of plausible range: {idx.value}"


# ── test 4: public_series rows written to DB ──────────────────────────────────

def test_public_series_has_statec_rows(owner_engine):
    """hm.public_series must contain at least the 2 known STATEC rows."""
    with owner_engine.connect() as conn:
        count = conn.execute(text("""
            SELECT count(*) FROM hm.public_series
            WHERE source = 'STATEC'
        """)).scalar()
    assert count >= 2, f"Expected ≥2 STATEC rows in hm.public_series, got {count}"


def test_public_series_has_stress_index(owner_engine):
    """hm.public_series must contain at least one stress_index row."""
    with owner_engine.connect() as conn:
        count = conn.execute(text("""
            SELECT count(*) FROM hm.public_series
            WHERE series_id LIKE 'stress_index_%'
        """)).scalar()
    assert count >= 1, "Expected at least one stress_index row in hm.public_series"


def test_public_series_stress_index_has_source_url_or_null(owner_engine):
    """Derived stress index rows may have NULL source_url (they are computed)."""
    with owner_engine.connect() as conn:
        row = conn.execute(text("""
            SELECT source_url FROM hm.public_series
            WHERE series_id LIKE 'stress_index_%'
            LIMIT 1
        """)).fetchone()
    assert row is not None
    # source_url is None for derived rows — that is expected
    assert row.source_url is None or isinstance(row.source_url, str)


# ── test 5: ingestion is idempotent ──────────────────────────────────────────

def test_ingestion_idempotent(owner_engine):
    """Running ingestion twice must not duplicate rows."""
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
        f"Row count changed from {before} to {after} on second run — "
        "ON CONFLICT DO NOTHING must prevent duplicates"
    )
    assert result["inserted"] == 0, (
        f"Second run inserted {result['inserted']} rows; expected 0"
    )
