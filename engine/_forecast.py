"""
Main forecast runner: load data → apply overrides → run components → aggregate.

Phase 2A: expected and on_time scenarios.
Phase 2B: stress scenario, Monte Carlo band, assumptions list, profit-vs-cash bridge.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import sqlalchemy as sa

from ._behaviour import SimpleBehaviour
from ._components import (
    aggregate_weekly,
    p1_open_payables,
    p2_future_purchases,
    p4_recurring,
    p5_vat,
    r1_open_receivables,
    r2_future_sales,
)
from ._loader import analyst_engine, load_dataset
from ._overrides import apply_overrides, load_active_overrides
from ._stress import (
    StressBehaviour,
    filter_defaulted_open_ar,
    load_shocks,
)
from ._montecarlo import run_montecarlo, check_band_contains_expected, MC_SEED, N_RUNS
from ._assumptions import build_assumptions
from ._profitcash import load_profitcash_data, build_bridge_historical, build_bridge_forecast

# Supplier term mix matches config/company.yaml tiers
_SUPPLIER_TERM_MIX = [
    {"tier": "major", "share": 0.35, "payment_terms_days": 60},
    {"tier": "mid",   "share": 0.35, "payment_terms_days": 45},
    {"tier": "small", "share": 0.30, "payment_terms_days": 30},
]

ENGINE_VERSION = "2B.0"


@dataclass
class ForecastResult:
    dataset_id: str
    as_of: date
    scenario: str
    weeks: list[dict]                # output of aggregate_weekly
    beyond_horizon: list[dict]       # R1 items falling after week 13
    seasonal_factors: dict           # seg_code → [float × 13]
    applied_overrides: list[dict]
    mc_band: dict[int, dict] | None = None        # {week: {p10, p50, p90, p_below}}
    mc_weeks_outside_band: list[int] | None = None
    assumptions: list[dict] | None = None
    bridge: list[dict] | None = None


def run_scenario(
    data: dict[str, Any],
    scenario: str,
    behaviour: SimpleBehaviour,
    vat_rate: float = 0.17,
    vat_return_day: int = 15,
    gross_margin: float = 0.30,
    n_weeks: int = 13,
) -> ForecastResult:
    """
    Run one scenario (expected | on_time) on a pre-loaded data dict.
    `data` is the output of _loader.load_dataset, optionally post-processed
    by apply_overrides.
    """
    as_of: date = data["as_of"]
    opening_balance: float = data["opening_balance"]
    history_start: date = data["history_start"]

    # ── Receipt components ──────────────────────────────────────────────────
    r1_by_week, beyond = r1_open_receivables(
        data["open_ar"], behaviour, as_of, n_weeks, scenario
    )

    r2_by_week, seasonal_factors, r2_net_by_issue_week = r2_future_sales(
        data["history_ar"], data["segments"], behaviour, as_of,
        history_start, vat_rate, n_weeks,
    )

    # ── Payment components ──────────────────────────────────────────────────
    p1_by_week = p1_open_payables(data["open_ap"], as_of, n_weeks)

    p2_by_week = p2_future_purchases(
        r2_net_by_issue_week, gross_margin, vat_rate, _SUPPLIER_TERM_MIX, as_of, n_weeks
    )

    p4_by_week = p4_recurring(data["recurring"], as_of, n_weeks)

    p5_by_week = p5_vat(
        data["history_ar"], data["history_ap"],
        r2_by_week, p2_by_week,
        as_of, vat_return_day, n_weeks,
        r2_net_by_issue_week=r2_net_by_issue_week,
        gross_margin=gross_margin,
        vat_rate=vat_rate,
    )

    # ── Merge all components ────────────────────────────────────────────────
    from collections import defaultdict

    all_receipts: dict[int, list[dict]] = defaultdict(list)
    for wk, items in r1_by_week.items():
        all_receipts[wk].extend(items)
    for wk, items in r2_by_week.items():
        all_receipts[wk].extend(items)

    all_payments: dict[int, list[dict]] = defaultdict(list)
    for wk, items in p1_by_week.items():
        all_payments[wk].extend(items)
    for wk, items in p2_by_week.items():
        all_payments[wk].extend(items)
    for wk, items in p4_by_week.items():
        all_payments[wk].extend(items)
    for wk, items in p5_by_week.items():
        all_payments[wk].extend(items)

    weeks = aggregate_weekly(opening_balance, dict(all_receipts), dict(all_payments),
                             as_of, n_weeks)

    return ForecastResult(
        dataset_id=data["dataset_id"],
        as_of=as_of,
        scenario=scenario,
        weeks=weeks,
        beyond_horizon=beyond,
        seasonal_factors=seasonal_factors,
        applied_overrides=data.get("applied_overrides", []),
    )


def run_forecast(
    dataset_id: str,
    sa_engine: sa.Engine,
    scenarios: list[str] | None = None,
    vat_rate: float = 0.17,
    vat_return_day: int = 15,
    gross_margin: float = 0.30,
    n_weeks: int = 13,
    include_mc: bool = False,
    include_stress: bool = False,
    include_assumptions: bool = False,
    include_bridge: bool = False,
    threshold: float = 0.0,
    dep_annual: float = 250_000.0,
    stress_config_path: Path | None = None,
    mc_seed: int = MC_SEED,
    mc_n_runs: int = N_RUNS,
) -> dict[str, ForecastResult]:
    """
    Load data, apply overrides, run requested scenarios, return results dict.

    scenarios defaults to ["expected", "on_time"].
    Set include_stress=True to add a "stress" scenario.
    Set include_mc=True to attach Monte Carlo band to the "expected" result.
    """
    if scenarios is None:
        scenarios = ["expected", "on_time"]

    data = load_dataset(sa_engine, dataset_id)
    as_of = data["as_of"]

    overrides = load_active_overrides(sa_engine, dataset_id)
    data = apply_overrides(data, overrides)

    behaviour = SimpleBehaviour(sa_engine, dataset_id, as_of)

    results: dict[str, ForecastResult] = {}
    for scenario in scenarios:
        results[scenario] = run_scenario(
            data, scenario, behaviour, vat_rate, vat_return_day, gross_margin, n_weeks
        )

    # ── Stress scenario ───────────────────────────────────────────────────────
    shocks: list[dict] = []
    if include_stress:
        shocks = load_shocks(stress_config_path)
        stress_beh = StressBehaviour(behaviour, shocks, data["open_ar"])
        stress_data = dict(data)
        if stress_beh.defaulted_customers:
            stress_data["open_ar"] = filter_defaulted_open_ar(
                data["open_ar"], stress_beh.defaulted_customers
            )
        results["stress"] = run_scenario(
            stress_data, "stress", stress_beh, vat_rate, vat_return_day, gross_margin, n_weeks
        )

    # ── Monte Carlo band (attached to "expected") ─────────────────────────────
    if include_mc and "expected" in results:
        exp_result = results["expected"]
        mc_band = run_montecarlo(
            data=data,
            behaviour=behaviour,
            seasonal_factors=exp_result.seasonal_factors,
            threshold=threshold,
            n_runs=mc_n_runs,
            seed=mc_seed,
            vat_rate=vat_rate,
            vat_return_day=vat_return_day,
            gross_margin=gross_margin,
            n_weeks=n_weeks,
        )
        outside = check_band_contains_expected(mc_band, exp_result.weeks)
        results["expected"] = ForecastResult(
            dataset_id=exp_result.dataset_id,
            as_of=exp_result.as_of,
            scenario=exp_result.scenario,
            weeks=exp_result.weeks,
            beyond_horizon=exp_result.beyond_horizon,
            seasonal_factors=exp_result.seasonal_factors,
            applied_overrides=exp_result.applied_overrides,
            mc_band=mc_band,
            mc_weeks_outside_band=outside,
        )

    # ── Assumptions list ──────────────────────────────────────────────────────
    if include_assumptions and "expected" in results:
        exp_result = results["expected"]
        assumptions = build_assumptions(
            behaviour=behaviour,
            seasonal_factors=exp_result.seasonal_factors,
            stress_shocks=shocks,
            applied_overrides=exp_result.applied_overrides,
            as_of=as_of,
            gross_margin=gross_margin,
            vat_rate=vat_rate,
            threshold=threshold,
            supplier_term_mix=_SUPPLIER_TERM_MIX,
        )
        results["expected"] = ForecastResult(
            dataset_id=results["expected"].dataset_id,
            as_of=results["expected"].as_of,
            scenario=results["expected"].scenario,
            weeks=results["expected"].weeks,
            beyond_horizon=results["expected"].beyond_horizon,
            seasonal_factors=results["expected"].seasonal_factors,
            applied_overrides=results["expected"].applied_overrides,
            mc_band=results["expected"].mc_band,
            mc_weeks_outside_band=results["expected"].mc_weeks_outside_band,
            assumptions=assumptions,
        )

    # ── Profit-vs-cash bridge ─────────────────────────────────────────────────
    if include_bridge and "expected" in results:
        from datetime import timedelta
        from calendar import monthrange
        pc_data = load_profitcash_data(sa_engine, dataset_id)
        mc_list = pc_data["month_closes"]

        # Last 3 closed months before as_of
        hist_months = sorted(
            {mc["month"] for mc in mc_list if mc["month"] < as_of},
            reverse=True,
        )[:3]
        hist_months = list(reversed(hist_months))

        bridge_hist = build_bridge_historical(pc_data, dep_annual, hist_months)

        # Forecast months: start from the month after as_of (current month is historical)
        horizon_months: list[date] = []
        _nm = as_of.month + 1
        _ny = as_of.year + (1 if _nm > 12 else 0)
        d = date(_ny, (_nm - 1) % 12 + 1, 1)
        horizon_end = as_of + timedelta(weeks=n_weeks)
        while d <= horizon_end:
            horizon_months.append(d)
            m = d.month + 1
            y = d.year + (1 if m > 12 else 0)
            d = date(y, (m - 1) % 12 + 1, 1)

        bridge_fcst = build_bridge_forecast(
            forecast_months=horizon_months,
            scenario_weeks=results["expected"].weeks,
            month_closes=mc_list,
            as_of=as_of,
            dep_annual=dep_annual,
            opening_balance=data["opening_balance"],
        )

        full_bridge = bridge_hist + bridge_fcst
        exp = results["expected"]
        results["expected"] = ForecastResult(
            dataset_id=exp.dataset_id,
            as_of=exp.as_of,
            scenario=exp.scenario,
            weeks=exp.weeks,
            beyond_horizon=exp.beyond_horizon,
            seasonal_factors=exp.seasonal_factors,
            applied_overrides=exp.applied_overrides,
            mc_band=exp.mc_band,
            mc_weeks_outside_band=exp.mc_weeks_outside_band,
            assumptions=exp.assumptions,
            bridge=full_bridge,
        )

    return results
