"""Scenario definitions for the 8 synthetic datasets."""
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

SCENARIO_DESCRIPTIONS = {
    "S1_normal":          "Base behaviour only — no shortfall expected",
    "S2_big_customer":    "Top-3 customer drifts +10→+45 days; major supplier bill in week 6",
    "S3_sector_crisis":   "25 F41 general contractors add +15–25 days (correlated shock)",
    "S4_outflow_spike":   "Extraordinary supplier bill + moved tax advance + VAT in week 8",
    "S5_seasonality":     "History shows August and December slowdowns",
    "S6_new_customer":    "New F43 customer onboarded 6 weeks ago; true archetype slow",
    "S7_partial_payments": "3 customers pay 50–70% on time, remainder 3–6 weeks later",
    "S8_month_end_close": "Fiduciaire closes 15–20 days late; Sep close has adjustments",
}

# Per-dataset seed = base_seed + offset
# S4 intentionally uses offset=0 (same counterparty base as S1) so its base trajectory
# stays above threshold and only the extraordinary spike pushes week 8 below threshold.
SEED_OFFSETS: dict[str, int] = {
    "S1_normal":          0,
    "S2_big_customer":    1,
    "S3_sector_crisis":   2,
    "S4_outflow_spike":   0,   # same counterparty seed as S1
    "S5_seasonality":     4,
    "S6_new_customer":    5,
    "S7_partial_payments": 6,
    "S8_month_end_close": 7,
}


@dataclass
class ScenarioParams:
    dataset_id: str
    seed_offset: int = 0
    # S2
    big_customer_drift: dict = field(default_factory=dict)
    extraordinary_ap: list[dict] = field(default_factory=list)
    # S3
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


def build_params(dataset_id: str, as_of_date: date) -> ScenarioParams:
    p = ScenarioParams(
        dataset_id=dataset_id,
        seed_offset=SEED_OFFSETS[dataset_id],
    )

    if dataset_id == "S2_big_customer":
        # Drift starts 4 months before as_of (~2026-05-28)
        drift_start = date(as_of_date.year, as_of_date.month, as_of_date.day) - timedelta(days=120)
        p.big_customer_drift = {
            "drift_start": drift_start,
            "delay_from": 10,    # extra days at drift start
            "delay_to": 45,      # extra days at drift end (as_of)
        }
        # Extraordinary SUPP_01 AP invoice due in forecast week 6
        week6_start = as_of_date + timedelta(weeks=5)
        p.extraordinary_ap = [{
            "supp_code": "SUPP_01",
            "amount_net": 1_400_000.00,
            "issue_date": week6_start - timedelta(days=60),
            "due_date": week6_start + timedelta(days=2),
            "note": "S2_large_bill",
        }]

    elif dataset_id == "S3_sector_crisis":
        # Shock starts 3 months before as_of; severe enough (+45–70 days) to cause shortfall
        shock_start = as_of_date - timedelta(days=90)
        p.sector_crisis = {
            "shock_start": shock_start,
            "n_affected": 25,
            "extra_delay_min": 45,
            "extra_delay_max": 70,
        }

    elif dataset_id == "S4_outflow_spike":
        # Week 8 starts as_of + 7 weeks
        week8_start = as_of_date + timedelta(weeks=7)
        # Bill sized so that week 8 closing balance dips below threshold.
        # S4 uses same seed as S1; with the suppressed Dec tax advance,
        # the net extra outflow = amount_net (VAT portion cancels with Oct VAT savings).
        # Observed S4 week 8 with 690k bill = 629k; need < 510k → increase by ~130k.
        p.outflow_spike = {
            "supp_code": "SUPP_01",
            "amount_net": 820_000.00,
            "due_date": week8_start + timedelta(days=1),  # Tue of week 8
            "extra_tax_advance_date": week8_start + timedelta(days=2),  # Wed of week 8
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

    return p
