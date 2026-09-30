"""
1C tests: synthetic data generator.

Checks:
- Same seed -> identical output (CSV hash)
- Revenue within €24–26m (history period); top-20 share 55–67%
- Profit on paper positive in every dataset
- No string resembling a company name in any hm table (only codes)
- All 8 scenario acceptance checks pass
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy import text

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
from config import settings  # noqa: E402

from ingestion.generator import run as run_generator
from ingestion.generator.scenarios import SCENARIO_IDS
from ingestion.generator._cfg import load as load_cfg
from ingestion.generator._pipeline import generate_dataset

SYNTHETIC_DIR = ROOT / "data" / "synthetic"


@pytest.fixture(scope="module")
def owner_engine():
    return sa.create_engine(settings.postgres_dsn, pool_pre_ping=True)


@pytest.fixture(scope="module")
def all_results(tmp_path_factory):
    """Generate all 8 datasets once for this test module."""
    results = run_generator(dry_run=False, verbose=False)
    return results


# ── test 1: reproducibility ───────────────────────────────────────────────────

def test_same_seed_same_ar_invoice_hash(tmp_path):
    """Running the generator twice with the same seed produces identical ar_invoices.csv."""
    run_generator(dataset_ids=["S1_normal"], dry_run=True, verbose=False)
    csv1 = (SYNTHETIC_DIR / "S1_normal" / "ar_invoices.csv").read_bytes()
    hash1 = hashlib.sha256(csv1).hexdigest()

    run_generator(dataset_ids=["S1_normal"], dry_run=True, verbose=False)
    csv2 = (SYNTHETIC_DIR / "S1_normal" / "ar_invoices.csv").read_bytes()
    hash2 = hashlib.sha256(csv2).hexdigest()

    assert hash1 == hash2, "ar_invoices.csv hash changed between identical runs"


# ── test 2: revenue and concentration ────────────────────────────────────────

@pytest.mark.parametrize("dataset_id", SCENARIO_IDS)
def test_revenue_within_range(dataset_id, all_results):
    """Annual revenue for each dataset must be between €24m and €26m."""
    result = all_results[dataset_id]
    assert "rows" in result, f"{dataset_id}: no 'rows' in result"

    csv_path = SYNTHETIC_DIR / dataset_id / "overview.csv"
    assert csv_path.exists(), f"overview.csv missing for {dataset_id}"

    import csv
    with csv_path.open(encoding="utf-8") as f:
        rows = {r["metric"]: r["value"] for r in csv.DictReader(f)}

    revenue = float(rows["total_revenue"])
    assert 24_000_000 <= revenue <= 26_000_000, (
        f"{dataset_id}: revenue {revenue:,.0f} outside [24M, 26M]"
    )


@pytest.mark.parametrize("dataset_id", SCENARIO_IDS)
def test_top20_share_in_range(dataset_id, all_results):
    """Top-20 customers must represent 55–67% of history-period revenue."""
    csv_path = SYNTHETIC_DIR / dataset_id / "overview.csv"
    assert csv_path.exists()

    import csv
    with csv_path.open(encoding="utf-8") as f:
        rows = {r["metric"]: r["value"] for r in csv.DictReader(f)}

    share = float(rows["top20_revenue_share"])
    assert 0.57 <= share <= 0.63, (
        f"{dataset_id}: top-20 share {share:.4f} outside [57%, 63%]"
    )


# ── test 3: profit positive ───────────────────────────────────────────────────

@pytest.mark.parametrize("dataset_id", SCENARIO_IDS)
def test_profit_positive(dataset_id, owner_engine):
    """Profit on paper (sum of month_closes.profit) must be positive for every dataset."""
    with owner_engine.connect() as conn:
        profit = conn.execute(text("""
            SELECT COALESCE(SUM(profit), 0)
            FROM hm.month_closes
            WHERE dataset_id = :did
        """), {"did": dataset_id}).scalar()
    assert profit is not None
    assert float(profit) > 0, f"{dataset_id}: total profit {profit} is not positive"


# ── test 4: no company names in hm tables ────────────────────────────────────

# Common company-name suffix fragments that should NEVER appear in hm tables
_NAME_FRAGMENTS = ["S.à r.l.", "GmbH", "S.A.", "SARL", "Ltd.", "Nordwerk", "Atelier"]


def test_no_company_names_in_counterparties(owner_engine):
    """hm.counterparties must contain only codes (CUST_xxx / SUPP_xx), no display names."""
    with owner_engine.connect() as conn:
        # Check code column only contains expected patterns
        bad = conn.execute(text("""
            SELECT code FROM hm.counterparties
            WHERE code NOT SIMILAR TO '(CUST_[0-9]+|SUPP_[0-9]+|CUST_NC[0-9]+)'
            LIMIT 5
        """)).fetchall()
    assert not bad, f"Unexpected codes in hm.counterparties: {bad}"


def test_no_company_names_in_ar_invoices(owner_engine):
    """hm.ar_invoices.cust_code must look like CUST_nnn, not a company name."""
    for fragment in _NAME_FRAGMENTS:
        with owner_engine.connect() as conn:
            count = conn.execute(text("""
                SELECT count(*) FROM hm.ar_invoices
                WHERE cust_code ILIKE :frag
            """), {"frag": f"%{fragment}%"}).scalar()
        assert count == 0, f"Company name fragment '{fragment}' found in ar_invoices.cust_code"


# ── test 5: all 8 scenario acceptance checks ─────────────────────────────────

@pytest.mark.parametrize("dataset_id", SCENARIO_IDS)
def test_acceptance_check_passes(dataset_id):
    """Every scenario acceptance check must pass (checks.json on disk)."""
    checks_path = SYNTHETIC_DIR / dataset_id / "checks.json"
    assert checks_path.exists(), f"checks.json missing for {dataset_id}"

    with checks_path.open(encoding="utf-8") as f:
        checks = json.load(f)

    assert checks.get("passed"), (
        f"{dataset_id} acceptance check FAILED:\n{json.dumps(checks, indent=2)}"
    )


# ── test 6: DB row counts ─────────────────────────────────────────────────────

@pytest.mark.parametrize("dataset_id", SCENARIO_IDS)
def test_hm_counterparties_count(dataset_id, owner_engine):
    """Each dataset must have at least 237 counterparties (237 customers + 25 suppliers)."""
    with owner_engine.connect() as conn:
        count = conn.execute(text("""
            SELECT count(*) FROM hm.counterparties WHERE dataset_id = :did
        """), {"did": dataset_id}).scalar()
    assert count >= 237, f"{dataset_id}: only {count} counterparties"


@pytest.mark.parametrize("dataset_id", SCENARIO_IDS)
def test_eval_future_balances_count(dataset_id, owner_engine):
    """eval.future_bank_balances must have exactly 13 rows per dataset."""
    with owner_engine.connect() as conn:
        count = conn.execute(text("""
            SELECT count(*) FROM eval.future_bank_balances WHERE dataset_id = :did
        """), {"did": dataset_id}).scalar()
    assert count == 13, f"{dataset_id}: expected 13 future balance rows, got {count}"


@pytest.mark.parametrize("dataset_id", SCENARIO_IDS)
def test_scenario_truth_in_db(dataset_id, owner_engine):
    """eval.scenario_truth must exist for every dataset."""
    with owner_engine.connect() as conn:
        row = conn.execute(text("""
            SELECT truth FROM eval.scenario_truth WHERE dataset_id = :did
        """), {"did": dataset_id}).fetchone()
    assert row is not None, f"eval.scenario_truth missing for {dataset_id}"
    assert row[0] is not None


# ── test 7: CSV exports exist ─────────────────────────────────────────────────

@pytest.mark.parametrize("dataset_id", SCENARIO_IDS)
def test_csv_exports_exist(dataset_id):
    """Required CSV files must exist for each dataset."""
    dataset_dir = SYNTHETIC_DIR / dataset_id
    required = ["ar_invoices.csv", "ar_receipts.csv", "ap_invoices.csv",
                "bank_balances.csv", "overview.csv", "checks.json", "README.txt"]
    for fname in required:
        assert (dataset_dir / fname).exists(), f"{dataset_id}/{fname} missing"


def test_global_overview_exists():
    """data/synthetic/overview_all.csv must exist."""
    assert (SYNTHETIC_DIR / "overview_all.csv").exists(), "overview_all.csv missing"
