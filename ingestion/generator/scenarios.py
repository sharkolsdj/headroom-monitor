"""Scenario definitions for the 8 synthetic datasets + 2 hold-out datasets."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

SCENARIO_IDS = [
    "S1_normal",
    "S2_big_customer",
    "S3_sector_crisis",
    "S4_outflow_spike",
    "S5_seasonality",
    "S6_new_customer",
    "S7_partial_payments",
    "S8_month_end_close",
]

HOLDOUT_IDS = [
    "H1_drift",
    "H2_sector",
]

SCENARIO_DESCRIPTIONS = {
    "S1_normal":          "Base behaviour only — no shortfall expected",
    "S2_big_customer":    "Top-3 customer drifts +10→+45 days; major supplier bill in week 6",
    "S3_sector_crisis":   "All F41+F43 customers (exc. top-5) hit by construction-sector stress; 2 bankruptcies in horizon",
    "S4_outflow_spike":   "Extraordinary supplier bill + moved tax advance + VAT in week 8",
    "S5_seasonality":     "History shows August and December slowdowns",
    "S6_new_customer":    "New F43 customer onboarded 6 weeks ago; true archetype slow",
    "S7_partial_payments": "3 customers pay 50–70% on time, remainder 3–6 weeks later",
    "S8_month_end_close": "Fiduciaire closes 15–20 days late; Sep close has adjustments",
    # Hold-out (Phase 3.4) — drawn with numpy.random.default_rng(4242)
    "H1_drift":    "Hold-out: one top-5 customer drifts +49d from 5 months before as-of; ~€969k bill in W5",
    "H2_sector":   "Hold-out: specialised_installers slows +40.8d over 3 months; 3 small customers bankrupt in horizon",
}

# Per-dataset seed = base_seed + offset
# S4 intentionally uses offset=0 (same counterparty base as S1) so its base trajectory
# stays above threshold and only the extraordinary spike pushes week 8 below threshold.
# H1/H2 use offset=4200 → simulation seed = 42 + 4200 = 4242.
SEED_OFFSETS: dict[str, int] = {
    "S1_normal":          0,
    "S2_big_customer":    0,   # same counterparty base as S1 so inventory exclusion is the only P&L driver
    "S3_sector_crisis":   2,
    "S4_outflow_spike":   0,   # same counterparty seed as S1
    "S5_seasonality":     4,
    "S6_new_customer":    5,
    "S7_partial_payments": 6,
    "S8_month_end_close": 7,
    "H1_drift":           4200,  # seed = 4242
    "H2_sector":          4200,  # seed = 4242 — same counterparty base as H1
}


@dataclass
class ScenarioParams:
    dataset_id: str
    seed_offset: int = 0
    # S2 / H1
    big_customer_drift: dict = field(default_factory=dict)
    extraordinary_ap: list[dict] = field(default_factory=list)
    # S3 / H2
    sector_crisis: dict = field(default_factory=dict)
    # S4
    outflow_spike: dict = field(default_factory=dict)
    # S5 — no extra params (seasonality is always in the base simulation)
    # S6
    new_customer: dict = field(default_factory=dict)
    # S7
    partial_payments: dict = field(default_factory=dict)
    # S8
    late_close: bool = False
    close_adjustments_sep: list[dict] = field(default_factory=list)
    # H1 / H2 — pre-drawn parameters (seed 4242), recorded in scenario_truth
    holdout_draws: dict = field(default_factory=dict)


def build_params(dataset_id: str, as_of_date: date) -> ScenarioParams:
    p = ScenarioParams(
        dataset_id=dataset_id,
        seed_offset=SEED_OFFSETS[dataset_id],
    )

    if dataset_id == "S2_big_customer":
        # Drift starts 4 months before as_of (~2026-05-28).
        # delay_to=60 deepens the expected dip in W6-9 enough to keep it below threshold
        # even after the bill is reduced from €1.4M to €950k (which is needed so that
        # on_time W10-13 stays above threshold+€100k).
        drift_start = date(as_of_date.year, as_of_date.month, as_of_date.day) - timedelta(days=120)
        p.big_customer_drift = {
            "drift_start": drift_start,
            "delay_from": 10,    # extra days at drift start
            "delay_to": 60,      # extra days at drift end (as_of); was 45
        }
        # Extraordinary SUPP_01 AP invoice due in forecast week 6.
        # Reduced from €1.4M to €950k so that on_time W10-13 min >= threshold+€100k.
        week6_start = as_of_date + timedelta(weeks=5)
        p.extraordinary_ap = [{
            "supp_code": "SUPP_01",
            "amount_net": 950_000.00,
            "issue_date": week6_start - timedelta(days=60),
            "due_date": week6_start + timedelta(days=2),
            "note": "S2_large_bill",
        }]

    elif dataset_id == "S3_sector_crisis":
        # Shock starts 3 months before as_of and continues in horizon.
        # Affected cohort: ALL F41+F43 except top-5 globally by revenue.
        # excluded_top5 and stress_index are injected by _pipeline after customers are built.
        shock_start = as_of_date - timedelta(days=90)
        p.sector_crisis = {
            "shock_start": shock_start,
            "nace_codes": ["F41", "F43"],
            "excluded_top5": set(),   # populated by _pipeline.generate_dataset
            "extra_delay_min": 30,
            "extra_delay_max": 50,
            "stress_index": 1.16,     # STATEC construction stress index (overridden by DB value)
            "n_bankrupt": 2,
        }

    elif dataset_id == "S4_outflow_spike":
        # Pure timing problem: SUPP_01 switches to quarterly billing for Q4 2026,
        # consolidating all 3 horizon monthly invoices (~3 months, ~€1.3M net) into
        # ONE invoice due in W7 (Nov 10) instead of the normal monthly cadence.
        # The quarterly tax advance (moved from Dec 10 to W7) and Oct VAT payment
        # (due Nov 15 = W7) also land in the same week — a calendar pile-up.
        # Total 13-week outflows = S1 ±0% (same invoices, different due dates).
        # W8-W13 recover fully: the W9 and W13 regular payments are already in W7.
        week7_start = as_of_date + timedelta(weeks=6)
        p.outflow_spike = {
            "supp_code": "SUPP_01",
            "due_date": week7_start + timedelta(days=1),  # Tue of W7 = Nov 10
            "extra_tax_advance_date": week7_start + timedelta(days=2),  # Wed of W7
            "extra_tax_advance_amount": 40_000.00,
        }

    elif dataset_id == "S6_new_customer":
        # New F43 customer onboarded 6 weeks before as_of
        onboard = as_of_date - timedelta(weeks=6)
        inv1_due = as_of_date + timedelta(weeks=3)   # due in horizon week 3
        inv2_due = as_of_date + timedelta(weeks=7)   # due in horizon week 7
        p.new_customer = {
            "onboarded_on": onboard,
            "nace": "F43",
            "archetype": "slow",
            "invoice_1_due": inv1_due,
            "invoice_1_amount": 75_000.00,
            "invoice_2_due": inv2_due,
            "invoice_2_amount": 75_000.00,
        }

    elif dataset_id == "S7_partial_payments":
        # 3 customers with split payments; identified after counterparties are built
        p.partial_payments = {"n_customers": 3, "part_ratio_min": 0.50, "part_ratio_max": 0.70}

    elif dataset_id == "S8_month_end_close":
        p.late_close = True
        # September close (booked ~18 Oct): cancel one €60k invoice, add €25k credit notes
        p.close_adjustments_sep = [
            {"kind": "invoice_cancel",  "amount": -60_000.00, "note": "Sep close: cancelled invoice"},
            {"kind": "credit_note",     "amount":  25_000.00, "note": "Sep close: credit notes added"},
        ]

    elif dataset_id == "H1_drift":
        # Hold-out: random top-5 customer drifts +30-70 days from 2-5 months before as-of;
        # inventory bill 0.7-1.1m net in weeks 5-8.
        # Draws: numpy.random.default_rng(4242) — delay_to=49, months_back=5, bill_net=969k, bill_week=5, top5_idx=1
        import numpy as _np
        _rng = _np.random.default_rng(4242)
        delay_to     = int(_rng.integers(30, 71))         # +49d
        months_back  = int(_rng.integers(2, 6))           # 5 months
        bill_net_eur = float(_rng.uniform(700_000, 1_100_000))  # ~969k
        bill_week    = int(_rng.integers(5, 9))           # W5
        top5_idx     = int(_rng.integers(0, 5))           # idx 1 (0=largest)

        drift_start = as_of_date - timedelta(days=months_back * 30)
        p.big_customer_drift = {
            "drift_start": drift_start,
            "delay_from": 0,
            "delay_to": delay_to,
            "top5_idx": top5_idx,
        }
        week_start = as_of_date + timedelta(weeks=bill_week - 1)
        p.extraordinary_ap = [{
            "supp_code": "SUPP_01",
            "amount_net": round(bill_net_eur, 2),
            "issue_date": week_start - timedelta(days=60),
            "due_date":   week_start + timedelta(days=2),
            "note": "H1_inventory_bill",
        }]
        p.holdout_draws = {
            "seed": 4242,
            "delay_to": delay_to,
            "months_back": months_back,
            "bill_net_eur": round(bill_net_eur, 2),
            "bill_week": bill_week,
            "top5_idx": top5_idx,
        }

    elif dataset_id == "H2_sector":
        # Hold-out: one random segment from F41/F43/L68 slows +20-50 days over last 3 months;
        # 1-3 small customers of that segment go bankrupt in horizon.
        # Draws: numpy.random.default_rng(4242) — seg=specialised_installers, extra=40.8d, n_bankrupt=3
        import numpy as _np
        _rng = _np.random.default_rng(4242)
        _seg_candidates = ["general_contractors", "specialised_installers", "property_developers"]
        _nace_map = {
            "general_contractors": "F41",
            "specialised_installers": "F43",
            "property_developers": "L68",
        }
        seg_idx     = int(_rng.integers(0, 3))         # 1 → specialised_installers
        extra_delay = float(_rng.uniform(20, 51))      # ~40.8d
        n_bankrupt  = int(_rng.integers(1, 4))         # 3

        seg_code = _seg_candidates[seg_idx]
        nace     = _nace_map[seg_code]
        shock_start = as_of_date - timedelta(days=90)
        p.sector_crisis = {
            "shock_start": shock_start,
            "nace_codes": [nace],
            "excluded_top5": set(),   # all customers of this segment are affected
            "extra_delay_min": round(extra_delay, 1),
            "extra_delay_max": round(extra_delay, 1),
            "stress_index": 1.0,
            "n_bankrupt": n_bankrupt,
            "seg_code": seg_code,
        }
        p.holdout_draws = {
            "seed": 4242,
            "seg_idx": seg_idx,
            "seg_code": seg_code,
            "nace": nace,
            "extra_delay_days": round(extra_delay, 1),
            "n_bankrupt": n_bankrupt,
        }

    return p
