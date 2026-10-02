"""Monte Carlo uncertainty band for the expected scenario."""
from __future__ import annotations

import math
import random
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from ._behaviour import PaymentBehaviourModel
from ._grid import date_to_week, week_starts
from ._components import (
    aggregate_weekly,
    p1_open_payables,
    p2_future_purchases,
    p4_recurring,
    p5_vat,
)

N_RUNS = 1_000
MC_SEED = 42

# Supplier term mix — must match _forecast.py
_SUPPLIER_TERM_MIX = [
    {"tier": "major", "share": 0.35, "payment_terms_days": 60},
    {"tier": "mid",   "share": 0.35, "payment_terms_days": 45},
    {"tier": "small", "share": 0.30, "payment_terms_days": 30},
]


def _estimate_r2_sigma(
    history_ar: list[dict],
    segments: list[dict],
    as_of: date,
    history_start: date,
    seasonal_factors: dict[str, list[float]],
    n_weeks: int = 13,
) -> float:
    """
    Estimate log-normal sigma from history residuals of weekly invoicing vs seasonal forecast.
    Returns a pooled sigma across all segments.
    """
    seg_codes = {s["code"] for s in segments}
    n_hist_weeks = max(1, (as_of - history_start).days // 7)

    seg_annual: dict[str, float] = defaultdict(float)
    seg_weekly_actual: dict[str, dict[date, float]] = defaultdict(lambda: defaultdict(float))

    for inv in history_ar:
        seg = inv.get("segment", "")
        if seg not in seg_codes:
            continue
        net = float(inv.get("amount_net", 0.0))
        issue: date = inv["issue_date"]
        if issue >= as_of:
            continue
        seg_annual[seg] += net
        wk_start = issue - timedelta(days=issue.weekday())
        seg_weekly_actual[seg][wk_start] += net

    log_residuals: list[float] = []

    for seg in seg_codes:
        annual = seg_annual.get(seg, 0.0)
        if annual <= 0:
            continue
        annual_weekly_avg = annual / n_hist_weeks
        sfs = seasonal_factors.get(seg, [])

        for wk_start, actual_net in seg_weekly_actual[seg].items():
            if actual_net <= 0:
                continue
            # Find which horizon week this maps to (for seasonal factor)
            weeks = week_starts(as_of, n_weeks)
            # Find the corresponding horizon week index for the seasonal factor
            # Use the week's position in the year relative to the as_of anchor
            days_diff = (wk_start - (as_of - timedelta(weeks=52))).days
            k_idx = days_diff // 7
            if 0 <= k_idx < len(sfs):
                sf = sfs[k_idx]
            else:
                sf = 1.0
            forecast = annual_weekly_avg * sf
            if forecast <= 0:
                continue
            log_residuals.append(math.log(actual_net / forecast))

    if len(log_residuals) < 4:
        return 0.15  # default fallback

    mean_lr = sum(log_residuals) / len(log_residuals)
    variance = sum((x - mean_lr) ** 2 for x in log_residuals) / len(log_residuals)
    return math.sqrt(variance)


def _r1_sample(
    open_ar: list[dict],
    behaviour: PaymentBehaviourModel,
    as_of: date,
    n_weeks: int,
    rng: random.Random,
) -> tuple[dict[int, list[dict]], list[dict]]:
    """R1 with bootstrapped delays for one MC run."""
    receipts_by_week: dict[int, list[dict]] = defaultdict(list)
    beyond: list[dict] = []

    for inv in open_ar:
        cust_code = inv["cust_code"]
        due_date: date = inv["due_date"]
        outstanding = float(inv["outstanding_amount"])

        if "_override_receipt_date" in inv:
            receipt_date = inv["_override_receipt_date"]
        else:
            overdue_days = (as_of - due_date).days

            if overdue_days <= 0:
                # Not yet due: bootstrap from delay_sample
                sample = behaviour.delay_sample(cust_code)
                delay = rng.choice(sample) if sample else 0.0
                receipt_date = due_date + timedelta(days=max(0, round(delay)))
            else:
                expected = behaviour.expected_delay(cust_code)
                if overdue_days >= expected:
                    # Bootstrap from conditional remaining sample
                    sample = behaviour.delay_sample(cust_code)
                    cond = [x - overdue_days for x in sample if x > overdue_days]
                    remaining = rng.choice(cond) if cond else 1.0
                    receipt_date = as_of + timedelta(days=max(1, round(remaining)))
                else:
                    # Within expected delay window — bootstrap but cap at due+delay
                    sample = behaviour.delay_sample(cust_code)
                    delay = rng.choice(sample) if sample else expected
                    receipt_date = due_date + timedelta(days=max(0, round(delay)))

        week = date_to_week(receipt_date, as_of, n_weeks)
        item = {
            "invoice_id": inv["invoice_id"],
            "cust_code": cust_code,
            "amount": outstanding,
            "source": "R1",
        }
        if week is None:
            beyond.append(item)
        else:
            receipts_by_week[week].append(item)

    return dict(receipts_by_week), beyond


def _r2_sample(
    segments: list[dict],
    behaviour: PaymentBehaviourModel,
    as_of: date,
    history_start: date,
    vat_rate: float,
    n_weeks: int,
    seasonal_factors: dict[str, list[float]],
    seg_annual: dict[str, float],
    n_hist_weeks: int,
    sigma: float,
    rng: random.Random,
) -> tuple[dict[int, list[dict]], dict[int, float]]:
    """R2 with log-normal volume noise for one MC run."""
    receipts_by_week: dict[int, list[dict]] = defaultdict(list)
    r2_net_by_issue_week: dict[int, float] = defaultdict(float)
    weeks = week_starts(as_of, n_weeks)

    for seg_def in segments:
        seg_code = seg_def["code"]
        annual = seg_annual.get(seg_code, 0.0)
        if annual <= 0:
            continue
        annual_weekly_avg = annual / n_hist_weeks
        terms = int(seg_def.get("payment_terms_days", 30))
        delay = behaviour.segment_expected_delay(seg_code)
        sfs = seasonal_factors.get(seg_code, [1.0] * n_weeks)

        for k_idx, wk_start in enumerate(weeks):
            k = k_idx + 1
            sf = sfs[k_idx] if k_idx < len(sfs) else 1.0
            # Log-normal multiplier: mean-preserving, sigma estimated from history
            z = rng.gauss(0.0, 1.0)
            multiplier = math.exp(z * sigma - 0.5 * sigma * sigma)
            forecast_net = annual_weekly_avg * sf * multiplier
            forecast_gross = forecast_net * (1.0 + vat_rate)

            r2_net_by_issue_week[k] += forecast_net

            receipt_date = wk_start + timedelta(days=terms + round(delay))
            recv_week = date_to_week(receipt_date, as_of, n_weeks)
            if recv_week is None:
                continue
            receipts_by_week[recv_week].append({
                "source": "R2",
                "amount": round(forecast_gross, 2),
                "amount_net": round(forecast_net, 2),
            })

    return dict(receipts_by_week), dict(r2_net_by_issue_week)


def run_montecarlo(
    data: dict[str, Any],
    behaviour: PaymentBehaviourModel,
    seasonal_factors: dict[str, list[float]],
    threshold: float = 0.0,
    n_runs: int = N_RUNS,
    seed: int = MC_SEED,
    vat_rate: float = 0.17,
    vat_return_day: int = 15,
    gross_margin: float = 0.30,
    n_weeks: int = 13,
) -> dict[int, dict]:
    """
    Run N_RUNS Monte Carlo simulations and return per-week band statistics.

    Returns {week: {p10, p50, p90, p_below_threshold}}
    """
    rng = random.Random(seed)
    as_of: date = data["as_of"]
    opening_balance = float(data["opening_balance"])
    history_start: date = data["history_start"]

    # Pre-compute segment annual averages for R2 sampling
    n_hist_weeks = max(1, (as_of - history_start).days // 7)
    seg_annual: dict[str, float] = defaultdict(float)
    for inv in data["history_ar"]:
        seg = inv.get("segment", "")
        net = float(inv.get("amount_net", 0.0))
        if inv["issue_date"] < as_of and seg:
            seg_annual[seg] += net
    seg_annual_dict = dict(seg_annual)

    # Estimate R2 volume noise sigma
    sigma = _estimate_r2_sigma(
        data["history_ar"], data["segments"], as_of, history_start,
        seasonal_factors, n_weeks,
    )

    # Deterministic components: P1, P4 (no uncertainty in payments)
    p1_by_week = p1_open_payables(data["open_ap"], as_of, n_weeks)
    p4_by_week = p4_recurring(data["recurring"], as_of, n_weeks)

    # Accumulate closing balances per week across all runs
    runs_by_week: list[list[float]] = [[] for _ in range(n_weeks)]

    for _ in range(n_runs):
        r1_by_week, _ = _r1_sample(data["open_ar"], behaviour, as_of, n_weeks, rng)
        r2_by_week, r2_net_by_issue_week = _r2_sample(
            data["segments"], behaviour, as_of, history_start, vat_rate,
            n_weeks, seasonal_factors, seg_annual_dict, n_hist_weeks, sigma, rng,
        )

        p2_by_week = p2_future_purchases(
            r2_net_by_issue_week, gross_margin, vat_rate, _SUPPLIER_TERM_MIX, as_of, n_weeks
        )
        p5_by_week = p5_vat(
            data["history_ar"], data["history_ap"],
            r2_by_week, p2_by_week,
            as_of, vat_return_day, n_weeks,
            r2_net_by_issue_week=r2_net_by_issue_week,
            gross_margin=gross_margin,
            vat_rate=vat_rate,
        )

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

        weeks_data = aggregate_weekly(
            opening_balance, dict(all_receipts), dict(all_payments), as_of, n_weeks
        )

        for k_idx, wk in enumerate(weeks_data):
            runs_by_week[k_idx].append(wk["closing"])

    # Compute percentiles per week
    result: dict[int, dict] = {}
    for k_idx in range(n_weeks):
        closings = sorted(runs_by_week[k_idx])
        n = len(closings)
        p10 = closings[max(0, int(0.10 * n) - 1)]
        p50 = closings[max(0, int(0.50 * n) - 1)]
        p90 = closings[min(n - 1, int(0.90 * n))]
        p_below = sum(1 for c in closings if c < threshold) / n
        result[k_idx + 1] = {
            "p10": round(p10, 2),
            "p50": round(p50, 2),
            "p90": round(p90, 2),
            "p_below_threshold": round(p_below, 4),
        }

    return result


def check_band_contains_expected(
    mc_band: dict[int, dict],
    expected_weeks: list[dict],
) -> list[int]:
    """Return list of weeks where expected closing falls outside [P10, P90]."""
    outside: list[int] = []
    for wk in expected_weeks:
        k = wk["week"]
        band = mc_band.get(k)
        if band is None:
            continue
        closing = wk["closing"]
        if closing < band["p10"] or closing > band["p90"]:
            outside.append(k)
    return outside
