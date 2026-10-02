"""Build the assumptions list for a forecast run."""
from __future__ import annotations

from datetime import date
from typing import Any

from ._behaviour import SimpleBehaviour


def build_assumptions(
    behaviour: SimpleBehaviour,
    seasonal_factors: dict[str, list[float]],
    stress_shocks: list[dict],
    applied_overrides: list[dict],
    as_of: date,
    gross_margin: float,
    vat_rate: float,
    threshold: float,
    supplier_term_mix: list[dict],
    n_top_customers: int = 20,
) -> list[dict]:
    """
    Return a list of assumption dicts.

    Each dict: {id, description, value, source, affects}
    """
    assumptions: list[dict] = []
    aid = 1

    def add(description: str, value: Any, source: str, affects: str) -> None:
        nonlocal aid
        assumptions.append({
            "id": f"A{aid:03d}",
            "description": description,
            "value": value,
            "source": source,
            "affects": affects,
        })
        aid += 1

    # ── Fixed parameters ────────────────────────────────────────────────────────
    add("Gross margin (net sales – COGS) / net sales", gross_margin, "config", "P2, bridge")
    add("VAT rate (output VAT on sales)", vat_rate, "config", "R2, P2, P5")
    add("Safety threshold (€)", threshold, "config", "p_below_threshold")

    # ── Overdue invoice rule ────────────────────────────────────────────────────
    add(
        "Overdue invoice timing rule",
        "If overdue ≥ expected_delay: as_of + conditional_remaining_delay(d). "
        "Else: due_date + expected_delay.",
        "spec",
        "R1",
    )
    add(
        "conditional_remaining_delay fallback",
        "Segment pool when fewer than 5 qualifying observations; minimum 1 day.",
        "spec",
        "R1",
    )

    # ── Supplier term mix ───────────────────────────────────────────────────────
    for tier in supplier_term_mix:
        add(
            f"Supplier term tier '{tier.get('tier', '?')}': share {tier['share']:.0%}, "
            f"{tier['payment_terms_days']} days",
            {"share": tier["share"], "payment_terms_days": tier["payment_terms_days"]},
            "config",
            "P2",
        )

    # ── Seasonal factors (one entry per segment) ─────────────────────────────
    for seg, sfs in sorted(seasonal_factors.items()):
        add(
            f"Seasonal factors for segment '{seg}' (weeks 1–13)",
            [round(sf, 4) for sf in sfs],
            "history",
            "R2",
        )

    # ── Customer payment delays (top N by AR) ────────────────────────────────
    all_cust = behaviour.all_customer_sources()
    sorted_cust = sorted(all_cust.items(), key=lambda kv: -kv[1][0])
    top_n = sorted_cust[:n_top_customers]

    for cust_code, (exp_delay, src) in top_n:
        add(
            f"Expected payment delay — {cust_code}",
            round(exp_delay, 1),
            src,
            "R1",
        )

    # ── Segment expected delays ─────────────────────────────────────────────
    segs_seen: set[str] = set()
    if hasattr(behaviour, "_seg_pools"):
        for seg in behaviour._seg_pools:  # type: ignore[attr-defined]
            if seg not in segs_seen:
                segs_seen.add(seg)
                seg_delay = behaviour.segment_expected_delay(seg)
                add(
                    f"Segment pool expected delay — {seg}",
                    round(seg_delay, 1),
                    "history",
                    "R1, R2",
                )

    # ── Stress shocks ───────────────────────────────────────────────────────
    for shock in stress_shocks:
        stype = shock.get("type", "")
        if stype == "customer_delay":
            add(
                f"Stress shock — customer_delay '{shock['code']}' +{shock['extra_days']} days",
                shock["extra_days"],
                "config",
                "stress scenario",
            )
        elif stype == "segment_delay":
            add(
                f"Stress shock — segment_delay '{shock['segment']}' +{shock['extra_days']} days",
                shock["extra_days"],
                "config",
                "stress scenario",
            )
        elif stype == "customer_default":
            add(
                f"Stress shock — customer_default '{shock['code']}' (all receipts zeroed)",
                True,
                "config",
                "stress scenario",
            )

    # ── Active CFO overrides ─────────────────────────────────────────────────
    for ov in applied_overrides:
        add(
            f"CFO override — {ov['target_type']} '{ov['target_id']}' field '{ov['field']}'",
            ov["new_value"],
            "CFO override",
            f"{ov['target_type']}",
        )

    return assumptions
