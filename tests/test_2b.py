"""
Phase 2B tests.

1. test_mc_reproducible: same seed produces identical output.
2. test_mc_bands: P10 ≤ P50 ≤ P90 for all weeks across all datasets.
3. test_bridge_reconciles: |reconciliation_error| < 0.01 for all historical months.
4. test_stress_customer_default: customer_default removes exactly that customer's receipts.
"""
from __future__ import annotations

import pytest
import sqlalchemy as sa
from datetime import date, timedelta
from pathlib import Path
import sys

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from config import settings
from scripts.migrate import apply_migrations
from engine._behaviour import SimpleBehaviour
from engine._forecast import run_forecast
from engine._montecarlo import run_montecarlo, MC_SEED, N_RUNS
from engine._stress import StressBehaviour, filter_defaulted_open_ar
from engine._loader import load_dataset
from engine._overrides import apply_overrides, load_active_overrides
from engine._profitcash import load_profitcash_data, build_bridge_historical


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session", autouse=True)
def run_migrations():
    apply_migrations(verbose=False)


@pytest.fixture(scope="session")
def analyst_engine():
    return sa.create_engine(settings.role_dsn("hm_analyst"), pool_pre_ping=True)


DATASETS = [
    "S1_normal", "S2_big_customer", "S3_sector_crisis", "S4_outflow_spike",
    "S5_seasonality", "S6_new_customer", "S7_partial_payments", "S8_month_end_close",
]


# ── 1. MC reproducible ─────────────────────────────────────────────────────────

def test_mc_reproducible(analyst_engine):
    """Two runs with the same seed must return identical P10/P50/P90."""
    data = load_dataset(analyst_engine, "S2_big_customer")
    overrides = load_active_overrides(analyst_engine, "S2_big_customer")
    data = apply_overrides(data, overrides)
    behaviour = SimpleBehaviour(analyst_engine, "S2_big_customer", data["as_of"])

    results_1 = run_forecast(
        "S2_big_customer", analyst_engine,
        scenarios=["expected"],
        include_mc=True,
        mc_seed=MC_SEED,
        mc_n_runs=200,
    )
    results_2 = run_forecast(
        "S2_big_customer", analyst_engine,
        scenarios=["expected"],
        include_mc=True,
        mc_seed=MC_SEED,
        mc_n_runs=200,
    )

    band1 = results_1["expected"].mc_band
    band2 = results_2["expected"].mc_band
    assert band1 is not None and band2 is not None

    for wk in range(1, 14):
        assert band1[wk]["p10"] == band2[wk]["p10"], f"Week {wk} P10 differs"
        assert band1[wk]["p50"] == band2[wk]["p50"], f"Week {wk} P50 differs"
        assert band1[wk]["p90"] == band2[wk]["p90"], f"Week {wk} P90 differs"


# ── 2. MC bands ordered ────────────────────────────────────────────────────────

@pytest.mark.parametrize("dataset_id", DATASETS)
def test_mc_bands(analyst_engine, dataset_id):
    """P10 ≤ P50 ≤ P90 for every week in every dataset."""
    results = run_forecast(
        dataset_id, analyst_engine,
        scenarios=["expected"],
        include_mc=True,
        mc_seed=MC_SEED,
        mc_n_runs=200,
    )
    band = results["expected"].mc_band
    assert band is not None, f"{dataset_id}: mc_band is None"

    for wk in range(1, 14):
        b = band[wk]
        assert b["p10"] <= b["p50"], f"{dataset_id} W{wk}: P10={b['p10']} > P50={b['p50']}"
        assert b["p50"] <= b["p90"], f"{dataset_id} W{wk}: P50={b['p50']} > P90={b['p90']}"
        assert 0.0 <= b["p_below_threshold"] <= 1.0, (
            f"{dataset_id} W{wk}: p_below_threshold out of [0,1]"
        )


# ── 3. Bridge reconciles ───────────────────────────────────────────────────────

@pytest.mark.parametrize("dataset_id", DATASETS)
def test_bridge_reconciles(analyst_engine, dataset_id):
    """
    For every historical month in the bridge, |reconciliation_error| < 0.01.
    Reconciliation is guaranteed by construction (inventory = residual),
    so a non-zero error indicates a bug in the arithmetic.
    """
    pc_data = load_profitcash_data(analyst_engine, dataset_id)
    mc_list = pc_data["month_closes"]

    data = load_dataset(analyst_engine, dataset_id)
    as_of = data["as_of"]

    # Last 3 closed months
    hist_months = sorted(
        {mc["month"] for mc in mc_list if mc["month"] < as_of},
        reverse=True,
    )[:3]
    hist_months = list(reversed(hist_months))

    if not hist_months:
        pytest.skip(f"{dataset_id}: no historical months available")

    bridge = build_bridge_historical(pc_data, dep_annual=250_000.0, months=hist_months)

    assert bridge, f"{dataset_id}: empty bridge"
    for row in bridge:
        err = abs(row["reconciliation_error"])
        assert err < 0.01, (
            f"{dataset_id} {row['month']}: reconciliation_error={row['reconciliation_error']:.4f}"
        )


# ── 4. Stress customer_default removes exactly that customer's receipts ────────

def test_stress_customer_default(analyst_engine):
    """
    When a customer_default shock is applied, that customer's open AR
    receipts are completely removed from the engine output.
    """
    dataset_id = "S2_big_customer"
    data = load_dataset(analyst_engine, dataset_id)
    overrides = load_active_overrides(analyst_engine, dataset_id)
    data = apply_overrides(data, overrides)
    behaviour = SimpleBehaviour(analyst_engine, dataset_id, data["as_of"])

    # Find the largest customer
    totals: dict[str, float] = {}
    for inv in data["open_ar"]:
        c = inv["cust_code"]
        totals[c] = totals.get(c, 0.0) + float(inv["outstanding_amount"])
    largest = max(totals, key=lambda k: totals[k])
    largest_ar_total = totals[largest]

    # Apply a customer_default shock for the largest customer
    shocks = [{"type": "customer_default", "code": largest}]
    stress_beh = StressBehaviour(behaviour, shocks, data["open_ar"])
    assert largest in stress_beh.defaulted_customers

    filtered_ar = filter_defaulted_open_ar(data["open_ar"], stress_beh.defaulted_customers)

    # After filtering, the largest customer has no open AR
    remaining_ar = sum(
        float(inv["outstanding_amount"])
        for inv in filtered_ar
        if inv["cust_code"] == largest
    )
    assert remaining_ar == 0.0, (
        f"Expected 0 AR for defaulted customer {largest}, got {remaining_ar}"
    )

    # Total filtered AR is less than original by exactly the defaulted customer's AR
    total_filtered = sum(float(inv["outstanding_amount"]) for inv in filtered_ar)
    total_original = sum(float(inv["outstanding_amount"]) for inv in data["open_ar"])
    diff = total_original - total_filtered
    assert abs(diff - largest_ar_total) < 0.01, (
        f"Filtered AR diff {diff:.2f} ≠ defaulted customer AR {largest_ar_total:.2f}"
    )
