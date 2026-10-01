"""Acceptance checks for the 8 scenario datasets."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import sqlalchemy as sa

from ._cfg import Cfg
from .simulation import SimResult


def run_checks(result: SimResult, cfg: Cfg) -> dict:
    """Run the acceptance check for the given dataset and return a result dict."""
    checker = _CHECKERS.get(result.dataset_id, _check_always_pass)
    return checker(result, cfg)


def _check_s1(result: SimResult, cfg: Cfg) -> dict:
    """S1: balance >= threshold in ALL 13 forecast weeks."""
    threshold = cfg.safety_threshold
    violations = []
    for week_start, bal in sorted(result.weekly_balances.items()):
        if week_start >= cfg.as_of_date:
            if bal < threshold:
                violations.append({"week": str(week_start), "balance": round(bal, 2)})
    if violations:
        return {
            "passed": False,
            "check": "S1: all 13 weeks above threshold",
            "threshold": round(threshold, 2),
            "violations": violations,
        }
    return {"passed": True, "check": "S1: all 13 weeks above threshold",
            "threshold": round(threshold, 2)}


def _check_s2(result: SimResult, cfg: Cfg) -> dict:
    """S2: actual balance < threshold in weeks 6–9; contractual above."""
    threshold = cfg.safety_threshold
    forecast_weeks = _forecast_weekly_balances(result, cfg)

    dips = [w for w in range(6, 10) if w <= len(forecast_weeks)
            and forecast_weeks[w - 1][1] < threshold]

    if not dips:
        return {
            "passed": False,
            "check": "S2: balance dips below threshold in weeks 6–9",
            "threshold": round(threshold, 2),
            "forecast_balances": [(str(d), round(b, 2)) for d, b in forecast_weeks[:9]],
        }

    return {
        "passed": True,
        "check": "S2: balance dips below threshold in weeks 6–9",
        "threshold": round(threshold, 2),
        "dip_weeks": dips,
    }


def _check_s3(result: SimResult, cfg: Cfg) -> dict:
    """S3: balance dips below threshold in weeks 7–11; no single affected customer > 20% of cohort AR."""
    threshold = cfg.safety_threshold
    forecast_weeks = _forecast_weekly_balances(result, cfg)

    # Check 1: balance dips in weeks 7-11
    dips = [w for w in range(7, 12) if w <= len(forecast_weeks)
            and forecast_weeks[w - 1][1] < threshold]

    if not dips:
        return {
            "passed": False,
            "check": "S3: balance dips below threshold in weeks 7–11",
            "threshold": round(threshold, 2),
            "forecast_balances": [(str(d), round(b, 2)) for d, b in forecast_weeks[:11]],
        }

    # Check 2: concentration — no single customer > 20% of affected cohort's history revenue
    from collections import defaultdict
    affected = set(result.scenario_truth.get("affected_codes", []))
    hist_invoices = [inv for inv in result.ar_invoices
                     if inv["issue_date"] < result.as_of_date
                     and inv.get("cust_code", "") in affected]

    cust_rev: dict[str, float] = defaultdict(float)
    for inv in hist_invoices:
        cust_rev[inv["cust_code"]] += float(inv["amount_net"])

    cohort_total = sum(cust_rev.values())
    max_share = max(cust_rev.values()) / cohort_total if cohort_total > 0 else 0.0
    concentration_ok = max_share <= 0.20

    return {
        "passed": concentration_ok,
        "check": "S3: balance dips in weeks 7-11 AND no single customer > 20% of cohort AR",
        "dip_weeks": dips,
        "threshold": round(threshold, 2),
        "affected_customer_count": len(cust_rev),
        "max_customer_cohort_share": round(max_share, 4),
        "concentration_ok": concentration_ok,
    }


def _check_s4(result: SimResult, cfg: Cfg) -> dict:
    """S4: balance < threshold in week 7 AND recovers to >= threshold by week 8.

    The extraordinary supplier bill falls in week 7.  Week 8 has net-positive
    AR inflows that restore the balance above threshold before end of that week.
    (Week 8→9 coincides with SUPP_01 monthly + payroll, so a week-8 spike cannot
    recover in week 9 for this seed; week 7 is the structurally correct slot.)
    """
    threshold = cfg.safety_threshold
    forecast_weeks = _forecast_weekly_balances(result, cfg)

    if len(forecast_weeks) < 8:
        return {"passed": False, "check": "S4: insufficient forecast weeks"}

    week7_bal = forecast_weeks[6][1]
    week8_bal = forecast_weeks[7][1]

    week7_ok = week7_bal < threshold
    week8_ok = week8_bal >= threshold

    return {
        "passed": week7_ok and week8_ok,
        "check": "S4: balance below threshold in week 7, recovers by week 8",
        "week_7_balance": round(week7_bal, 2),
        "week_8_balance": round(week8_bal, 2),
        "week_7_below_threshold": week7_ok,
        "week_8_recovers": week8_ok,
        "threshold": round(threshold, 2),
    }


def _check_s5(result: SimResult, cfg: Cfg) -> dict:
    """S5: December receipts >= 15% below November receipts."""
    as_of = cfg.as_of_date
    all_receipts = result.ar_receipts_hist + result.future_ar_receipts

    dec_rcpts = sum(float(r["amount"]) for r in all_receipts
                    if r["date"].month == 12 and r["date"].year == as_of.year)
    nov_rcpts = sum(float(r["amount"]) for r in all_receipts
                    if r["date"].month == 11 and r["date"].year == as_of.year)

    if nov_rcpts == 0:
        return {"passed": False, "check": "S5: November receipts = 0", "november": 0}

    pct_change = (dec_rcpts - nov_rcpts) / nov_rcpts
    passed = pct_change <= -0.15

    return {
        "passed": passed,
        "check": "S5: December receipts >= 15% below November",
        "november_receipts": round(nov_rcpts, 2),
        "december_receipts": round(dec_rcpts, 2),
        "pct_change": round(pct_change, 4),
    }


def _check_s6(result: SimResult, cfg: Cfg) -> dict:
    """S6: new customer payments arrive >= 15 days after due date."""
    all_receipts = result.ar_receipts_hist + result.future_ar_receipts

    nc_invoices = [inv for inv in result.ar_invoices
                   if inv.get("cust_code") == "CUST_NC1"]
    if not nc_invoices:
        return {"passed": False, "check": "S6: no new customer invoices found"}

    violations = []
    for inv in nc_invoices:
        matching = [r for r in all_receipts if r["invoice_id"] == inv["invoice_id"]]
        for r in matching:
            delay = (r["date"] - inv["due_date"]).days
            if delay < 15:
                violations.append({
                    "invoice_id": inv["invoice_id"],
                    "due_date": str(inv["due_date"]),
                    "receipt_date": str(r["date"]),
                    "actual_delay_days": delay,
                })

    return {
        "passed": len(violations) == 0,
        "check": "S6: new customer payments >= 15 days late",
        "violations": violations,
    }


def _check_s7(result: SimResult, cfg: Cfg) -> dict:
    """S7: partial receipts exist and sum to invoice amount for affected invoices."""
    all_receipts = result.ar_receipts_hist + result.future_ar_receipts

    # Find invoices with more than one receipt
    from collections import defaultdict
    receipts_by_inv: dict[str, list[dict]] = defaultdict(list)
    for r in all_receipts:
        receipts_by_inv[r["invoice_id"]].append(r)

    split_invoices = {inv_id: recs for inv_id, recs in receipts_by_inv.items()
                      if len(recs) > 1}

    if not split_invoices:
        return {"passed": False, "check": "S7: no split invoices found"}

    # Verify sums match invoice amounts
    failures = []
    for inv_id, recs in split_invoices.items():
        inv = next((i for i in result.ar_invoices if i["invoice_id"] == inv_id), None)
        if inv is None:
            continue
        total_received = sum(float(r["amount"]) for r in recs)
        expected = float(inv["amount_gross"])
        if abs(total_received - expected) > 0.02:
            failures.append({
                "invoice_id": inv_id,
                "expected": expected,
                "received": round(total_received, 2),
            })

    return {
        "passed": len(failures) == 0 and len(split_invoices) >= 3,
        "check": "S7: partial receipts exist and sum to invoice",
        "split_invoice_count": len(split_invoices),
        "sum_failures": failures,
    }


def _check_s8(result: SimResult, cfg: Cfg) -> dict:
    """S8: month_closes populated; Sep close has adjustments; booked revenue differs from invoiced."""
    closes = result.month_closes
    adjs = result.close_adjustments

    # Find Sep close
    sep_close = next(
        (c for c in closes if c["month"].month == 9 and c["month"].year == cfg.as_of_date.year),
        None
    )
    sep_adjs = [a for a in adjs if a["month"].month == 9]

    checks = {
        "month_closes_populated": len(closes) > 0,
        "sep_close_found": sep_close is not None,
        "sep_adjustments_found": len(sep_adjs) >= 1,
        "late_close_dates": all(
            (c["close_booked_on"] - date(c["month"].year, c["month"].month,
                                         _days_in_month(c["month"].year, c["month"].month))
             ).days >= 10
            for c in closes
        ),
    }

    passed = all(checks.values())
    return {
        "passed": passed,
        "check": "S8: month closes with late booking and Sep adjustments",
        **checks,
    }


def _check_always_pass(result: SimResult, cfg: Cfg) -> dict:
    return {"passed": True, "check": "no specific check"}


_CHECKERS = {
    "S1_normal":          _check_s1,
    "S2_big_customer":    _check_s2,
    "S3_sector_crisis":   _check_s3,
    "S4_outflow_spike":   _check_s4,
    "S5_seasonality":     _check_s5,
    "S6_new_customer":    _check_s6,
    "S7_partial_payments": _check_s7,
    "S8_month_end_close": _check_s8,
}


# ── helpers ───────────────────────────────────────────────────────────────────

def _forecast_weekly_balances(result: SimResult, cfg: Cfg) -> list[tuple[date, float]]:
    as_of = cfg.as_of_date
    return sorted(
        [(ws, bal) for ws, bal in result.weekly_balances.items() if ws >= as_of],
        key=lambda x: x[0]
    )


def _days_in_month(year: int, month: int) -> int:
    import calendar
    return calendar.monthrange(year, month)[1]


# ── Engine on-time check (single source of truth for contractual projection) ──

def engine_on_time_check(dataset_id: str, cfg: Cfg, analyst_engine: sa.Engine) -> dict:
    """
    Run the engine on_time scenario from DB data.

    This is the authoritative "contractual projection" check: if customers pay
    exactly on due_date with no delay, does the balance stay above the threshold?
    Called after write_to_db so the engine reads real loaded data.
    """
    from engine._forecast import run_forecast
    results = run_forecast(dataset_id, analyst_engine, scenarios=["on_time"])
    r = results["on_time"]
    threshold = cfg.safety_threshold
    violations = [w for w in r.weeks if w["closing"] < threshold]
    return {
        "passed": len(violations) == 0,
        "check": "engine on_time: all 13 weeks >= safety_threshold",
        "threshold": round(threshold, 2),
        "min_balance": round(min(w["closing"] for w in r.weeks), 2),
        "weeks_below": [v["week"] for v in violations],
    }
