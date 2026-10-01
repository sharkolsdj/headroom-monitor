"""
Main forecast runner: load data → apply overrides → run components → aggregate.

Produces `expected` and `on_time` scenarios for Phase 2A.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
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

# Supplier term mix matches config/company.yaml tiers
_SUPPLIER_TERM_MIX = [
    {"tier": "major", "share": 0.35, "payment_terms_days": 60},
    {"tier": "mid",   "share": 0.35, "payment_terms_days": 45},
    {"tier": "small", "share": 0.30, "payment_terms_days": 30},
]

ENGINE_VERSION = "2A.1"


@dataclass
class ForecastResult:
    dataset_id: str
    as_of: date
    scenario: str
    weeks: list[dict]                # output of aggregate_weekly
    beyond_horizon: list[dict]       # R1 items falling after week 13
    seasonal_factors: dict           # seg_code → [float × 13]
    applied_overrides: list[dict]


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
) -> dict[str, ForecastResult]:
    """
    Load data, apply overrides, run requested scenarios, return results dict.

    scenarios defaults to ["expected", "on_time"].
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

    return results
