"""Per-invoice predictions, customers.json and collections.json (Phase 3)."""
from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from ._behaviour import RecencyBehaviour, snap_to_month_end
from ._grid import date_to_week

# Reminder rule constants (pre-registered in PHASE3_PREREG.md)
_REMIND_DAYS_BEFORE_DUE = 7
_TYPICAL_SLOW_THRESHOLD = 20.0


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = max(0, min(len(s) - 1, int(p * len(s))))
    return s[idx]


def predict_invoice(
    inv: dict,
    behaviour: RecencyBehaviour,
    as_of: date,
    mc_threshold: float = 0.0,
    mc_band: dict[int, dict] | None = None,
    n_weeks: int = 13,
) -> dict:
    """
    Compute per-invoice payment prediction.

    Returns dict with:
        p50_date, p10_date, p90_date, remind_by, reason_code, priority_score,
        weeks_until_due, predicted_week
    """
    cust_code = inv["cust_code"]
    due_date: date = inv["due_date"]
    outstanding = float(inv["outstanding_amount"])
    overdue_days = max(0, (as_of - due_date).days)
    days_until_due = max(0, (due_date - as_of).days)

    sample = behaviour.delay_sample(cust_code)
    if not sample:
        sample = [behaviour.expected_delay(cust_code)]

    if overdue_days <= 0:
        # Not yet due: receipt = due_date + delay
        receipt_days = [max(0, round(d)) for d in sample]
        receipt_dates = [due_date + timedelta(days=d) for d in receipt_days]
        if hasattr(behaviour, 'is_month_end_payer') and behaviour.is_month_end_payer(cust_code):
            receipt_dates = [snap_to_month_end(d, d) for d in receipt_dates]
    else:
        # Overdue: receipt = as_of + (delay - overdue_days) for delays > overdue_days
        cond = [d - overdue_days for d in sample if d > overdue_days]
        if not cond:
            cond = [1.0]
        receipt_dates = [as_of + timedelta(days=max(1, round(r))) for r in cond]
        if hasattr(behaviour, 'is_month_end_payer') and behaviour.is_month_end_payer(cust_code):
            earliest = as_of + timedelta(days=1)
            receipt_dates = [snap_to_month_end(d, earliest) for d in receipt_dates]
    receipt_dates_sorted = sorted(receipt_dates)
    n = len(receipt_dates_sorted)
    p10_date = receipt_dates_sorted[max(0, int(0.10 * n))]
    p50_date = receipt_dates_sorted[max(0, int(0.50 * n) - 1)]
    p90_date = receipt_dates_sorted[min(n - 1, int(0.90 * n))]

    predicted_week = date_to_week(p50_date, as_of, n_weeks)

    # Reminder rule
    reason_code = "ok"
    if overdue_days > 0:
        reason_code = "overdue"
        remind_by = as_of
    elif behaviour.is_worsening(cust_code):
        reason_code = "worsening"
        remind_by = due_date - timedelta(days=_REMIND_DAYS_BEFORE_DUE)
    elif behaviour.is_slow(cust_code):
        reason_code = "slow"
        remind_by = due_date - timedelta(days=_REMIND_DAYS_BEFORE_DUE)
    elif mc_band and predicted_week is not None:
        band = mc_band.get(predicted_week, {})
        if band.get("p50", 1.0) < mc_threshold:
            reason_code = "threshold"
            remind_by = due_date - timedelta(days=_REMIND_DAYS_BEFORE_DUE)
        else:
            remind_by = due_date
    else:
        remind_by = due_date

    remind_by = max(remind_by, as_of)

    # Priority score: amount × P(pays after first critical week) × (1 / max(1, weeks_until_due))
    weeks_until_due = max(1, math.ceil(days_until_due / 7))
    if mc_band:
        # P(pays after first critical week) = fraction of scenarios where receipt is after week 1
        critical_weeks = [k for k, v in mc_band.items() if v.get("p50", 1.0) < mc_threshold]
        if critical_weeks:
            first_critical = min(critical_weeks)
            critical_end = as_of + timedelta(weeks=first_critical)
            p_after = sum(1 for d in receipt_dates if d > critical_end) / n
        else:
            p_after = 1.0
    else:
        p_after = 1.0

    priority_score = outstanding * p_after * (1.0 / weeks_until_due)

    return {
        "invoice_id": inv["invoice_id"],
        "cust_code": cust_code,
        "outstanding": round(outstanding, 2),
        "due_date": due_date.isoformat(),
        "overdue_days": overdue_days,
        "days_until_due": days_until_due,
        "p50_date": p50_date.isoformat(),
        "p10_date": p10_date.isoformat(),
        "p90_date": p90_date.isoformat(),
        "predicted_week": predicted_week,
        "remind_by": remind_by.isoformat(),
        "reason_code": reason_code,
        "priority_score": round(priority_score, 2),
        "weeks_until_due": weeks_until_due,
    }


def _cust_sentence(
    cust_code: str,
    typical_d: float,
    recent_d: float,
    trend: str,
    n_recent: int,
) -> str:
    """Template sentence for customers.json — no LLM."""
    td = round(typical_d)
    rd = round(recent_d)
    if trend == "worsening":
        return (
            f"Usually pays {td} days late; "
            f"in the last 3 months {rd} days late: worsening."
        )
    if td >= int(_TYPICAL_SLOW_THRESHOLD):
        return f"Consistently pays late (typical {td} days after due date)."
    if n_recent == 0:
        return f"No recent invoices; historical typical delay {td} days."
    return f"Typically pays {td} days late; recent payments on track."


def build_customers_json(
    open_ar: list[dict],
    history_ar: list[dict],
    behaviour: RecencyBehaviour,
    as_of: date,
    mc_band: dict[int, dict] | None = None,
    mc_threshold: float = 0.0,
    n_weeks: int = 13,
) -> list[dict]:
    """
    Build the customers export list (one entry per customer with open invoices).
    """
    # Group open invoices by customer
    cust_invoices: dict[str, list[dict]] = defaultdict(list)
    for inv in open_ar:
        cust_invoices[inv["cust_code"]].append(inv)

    # Per-customer historical paid invoices (for paid history list)
    cust_history: dict[str, list[dict]] = defaultdict(list)
    for inv in history_ar:
        cust_history[inv["cust_code"]].append(inv)

    # Compute per-invoice predictions
    inv_preds: dict[str, dict] = {}
    for inv in open_ar:
        pred = predict_invoice(inv, behaviour, as_of, mc_threshold, mc_band, n_weeks)
        inv_preds[inv["invoice_id"]] = pred

    # Sort customers by total priority score descending
    cust_priority: dict[str, float] = {}
    for cust, invs in cust_invoices.items():
        cust_priority[cust] = sum(
            inv_preds[i["invoice_id"]]["priority_score"] for i in invs
        )

    ranked_custs = sorted(cust_priority, key=lambda c: -cust_priority[c])

    customers: list[dict] = []
    for rank, cust_code in enumerate(ranked_custs, start=1):
        invs = cust_invoices[cust_code]
        total_owed = sum(float(i["outstanding_amount"]) for i in invs)
        overdue_amount = sum(
            float(i["outstanding_amount"])
            for i in invs
            if (as_of - i["due_date"]).days > 0
        )
        seg = invs[0].get("segment", "") if invs else ""

        typical_d = behaviour.typical_delay(cust_code)
        recent_d = behaviour.recent_delay(cust_code)
        trend = behaviour.trend_label(cust_code)
        n_recent = behaviour._recent_count.get(cust_code, 0)

        open_inv_list = []
        for inv in sorted(invs, key=lambda x: x["due_date"]):
            pred = inv_preds[inv["invoice_id"]]
            days_od = pred["overdue_days"]
            days_to = pred["days_until_due"]
            open_inv_list.append({
                "invoice_id": inv["invoice_id"],
                "due_date": inv["due_date"].isoformat(),
                "outstanding": round(float(inv["outstanding_amount"]), 2),
                "days_overdue": days_od if days_od > 0 else None,
                "days_to_due": days_to if days_od == 0 else None,
                "p50_date": pred["p50_date"],
                "p10_date": pred["p10_date"],
                "p90_date": pred["p90_date"],
                "remind_by": pred["remind_by"],
                "reason_code": pred["reason_code"],
            })

        customers.append({
            "cust_code": cust_code,
            "segment": seg,
            "priority_rank": rank,
            "total_owed": round(total_owed, 2),
            "overdue_amount": round(overdue_amount, 2),
            "typical_delay_days": round(typical_d, 1),
            "recent_delay_days": round(recent_d, 1),
            "trend": trend,
            "source": behaviour.source(cust_code),
            "sentence": _cust_sentence(cust_code, typical_d, recent_d, trend, n_recent),
            "open_invoices": open_inv_list,
        })

    return customers


def build_collections_json(
    open_ar: list[dict],
    behaviour: RecencyBehaviour,
    as_of: date,
    mc_band: dict[int, dict] | None = None,
    mc_threshold: float = 0.0,
    n_weeks: int = 13,
) -> list[dict]:
    """
    Build the collections list: customers ordered by priority, with amount at stake.
    """
    inv_preds: dict[str, dict] = {}
    for inv in open_ar:
        pred = predict_invoice(inv, behaviour, as_of, mc_threshold, mc_band, n_weeks)
        inv_preds[inv["invoice_id"]] = pred

    # Aggregate by customer
    cust_data: dict[str, dict] = defaultdict(lambda: {
        "total_owed": 0.0,
        "priority_score": 0.0,
        "soonest_remind_by": None,
        "overdue_amount": 0.0,
        "invoices": [],
    })

    for inv in open_ar:
        cc = inv["cust_code"]
        pred = inv_preds[inv["invoice_id"]]
        amt = float(inv["outstanding_amount"])
        cust_data[cc]["total_owed"] += amt
        cust_data[cc]["priority_score"] += pred["priority_score"]
        if pred["overdue_days"] > 0:
            cust_data[cc]["overdue_amount"] += amt
        remind = date.fromisoformat(pred["remind_by"])
        if cust_data[cc]["soonest_remind_by"] is None or remind < cust_data[cc]["soonest_remind_by"]:
            cust_data[cc]["soonest_remind_by"] = remind
        cust_data[cc]["invoices"].append(pred)

    sorted_custs = sorted(cust_data.items(), key=lambda x: -x[1]["priority_score"])

    result = []
    for rank, (cust_code, data) in enumerate(sorted_custs, start=1):
        seg = ""
        for inv in open_ar:
            if inv["cust_code"] == cust_code:
                seg = inv.get("segment", "")
                break
        result.append({
            "priority_rank": rank,
            "cust_code": cust_code,
            "segment": seg,
            "total_owed": round(data["total_owed"], 2),
            "overdue_amount": round(data["overdue_amount"], 2),
            "priority_score": round(data["priority_score"], 2),
            "remind_by": data["soonest_remind_by"].isoformat() if data["soonest_remind_by"] else as_of.isoformat(),
            "trend": behaviour.trend_label(cust_code),
            "n_invoices": len(data["invoices"]),
        })

    return result


def write_customers_json(
    customers: list[dict],
    path: Path,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(customers, indent=2, default=str), encoding="utf-8")


def write_collections_json(
    collections: list[dict],
    path: Path,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(collections, indent=2, default=str), encoding="utf-8")
