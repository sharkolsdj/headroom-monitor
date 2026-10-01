"""
Forecast components R1, R2, P1–P5.

All functions accept plain Python dicts loaded from the DB (or in-memory for testing).
No DB access here.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from ._grid import date_to_week, last_working_day, week_starts
from ._behaviour import PaymentBehaviourModel


# ── R1: Open receivables ─────────────────────────────────────────────────────

def r1_open_receivables(
    open_ar: list[dict],
    behaviour: PaymentBehaviourModel,
    as_of: date,
    n_weeks: int = 13,
    scenario: str = "expected",
) -> tuple[dict[int, list[dict]], list[dict]]:
    """
    Returns (receipts_by_week, beyond_horizon).

    open_ar: list of {invoice_id, cust_code, due_date, outstanding_amount, ...}
    beyond_horizon: items whose expected receipt falls after week n_weeks.
    """
    receipts_by_week: dict[int, list[dict]] = defaultdict(list)
    beyond: list[dict] = []

    for inv in open_ar:
        cust_code = inv["cust_code"]
        due_date: date = inv["due_date"]
        outstanding: float = float(inv["outstanding_amount"])

        # CFO override: explicit receipt date takes precedence
        if "_override_receipt_date" in inv:
            receipt_date = inv["_override_receipt_date"]
            week = date_to_week(receipt_date, as_of, n_weeks)
            item = {
                "invoice_id": inv["invoice_id"],
                "cust_code": cust_code,
                "due_date": due_date,
                "receipt_date": receipt_date,
                "amount": outstanding,
                "source": "R1",
                "delay_days": (receipt_date - due_date).days,
                "overdue_days": max(0, (as_of - due_date).days),
                "override": True,
            }
            if week is None:
                beyond.append(item)
            else:
                receipts_by_week[week].append(item)
            continue

        if scenario == "on_time":
            delay = 0.0
        else:
            delay = behaviour.expected_delay(cust_code)

        overdue_days = (as_of - due_date).days   # negative if not yet due
        if overdue_days > 0 and overdue_days >= delay:
            # Invoice is genuinely overdue AND has exceeded expected delay →
            # best estimate: as_of + max(7, half the expected delay)
            extra = max(7, round(0.5 * max(0.0, delay)))
            receipt_date = as_of + timedelta(days=extra)
        else:
            receipt_date = due_date + timedelta(days=round(delay))

        week = date_to_week(receipt_date, as_of, n_weeks)
        item = {
            "invoice_id": inv["invoice_id"],
            "cust_code": cust_code,
            "due_date": due_date,
            "receipt_date": receipt_date,
            "amount": outstanding,
            "source": "R1",
            "delay_days": round(delay, 1),
            "overdue_days": max(0, overdue_days),
        }
        if week is None:
            beyond.append(item)
        else:
            receipts_by_week[week].append(item)

    return dict(receipts_by_week), beyond


# ── R2: Future sales not yet invoiced ────────────────────────────────────────

def r2_future_sales(
    history_ar: list[dict],          # {issue_date, amount_net, segment, ...}
    segments: list[dict],             # [{code, payment_terms_days, nace}, ...]
    behaviour: PaymentBehaviourModel,
    as_of: date,
    history_start: date,
    vat_rate: float = 0.17,
    n_weeks: int = 13,
    seasonal_factor_floor: float = 0.6,
    seasonal_factor_cap: float = 1.4,
) -> tuple[dict[int, list[dict]], dict[str, list[float]]]:
    """
    Returns (receipts_by_week, seasonal_factors_by_seg_week).
    seasonal_factors_by_seg_week: {segment_code: [factor_week1..factor_week13]}
    """
    # Annual invoiced net per segment from history
    n_hist_weeks = max(1, (as_of - history_start).days // 7)

    seg_annual: dict[str, float] = defaultdict(float)
    # Weekly invoiced net per segment (keyed by week-start Monday)
    seg_weekly: dict[str, dict[date, float]] = defaultdict(lambda: defaultdict(float))

    for inv in history_ar:
        seg = inv.get("segment", "")
        if not seg:
            continue
        net = float(inv.get("amount_net", 0.0))
        issue: date = inv["issue_date"]
        if issue >= as_of:
            continue
        seg_annual[seg] += net
        # Find the Monday of that week
        week_start = issue - timedelta(days=issue.weekday())
        seg_weekly[seg][week_start] += net

    weeks = week_starts(as_of, n_weeks)
    seg_code_map = {s["code"]: s for s in segments}

    receipts_by_week: dict[int, list[dict]] = defaultdict(list)
    seasonal_factors: dict[str, list[float]] = {}

    for seg_code, seg_def in seg_code_map.items():
        annual = seg_annual.get(seg_code, 0.0)
        annual_weekly_avg = annual / n_hist_weeks if n_hist_weeks > 0 else 0.0
        terms = int(seg_def.get("payment_terms_days", 30))
        delay = behaviour.segment_expected_delay(seg_code)

        seg_sf: list[float] = []
        for k_idx, wk_start in enumerate(weeks):
            k = k_idx + 1
            # Corresponding week start in history (52 weeks ago ± 2 weeks centred)
            hist_centre = wk_start - timedelta(weeks=52)
            nearby_weeks = [hist_centre + timedelta(weeks=delta) for delta in (-1, 0, 1, 2)]
            hist_totals = [seg_weekly[seg_code].get(w, 0.0) for w in nearby_weeks]
            n_valid = sum(1 for w in nearby_weeks if w >= history_start and w < as_of)
            if n_valid >= 2 and annual_weekly_avg > 0:
                hist_avg = sum(hist_totals) / 4.0
                sf = hist_avg / annual_weekly_avg
                sf = max(seasonal_factor_floor, min(seasonal_factor_cap, sf))
            else:
                sf = 1.0
            seg_sf.append(sf)

            if annual_weekly_avg <= 0:
                continue

            forecast_net = annual_weekly_avg * sf
            forecast_gross = forecast_net * (1.0 + vat_rate)

            # Receipt date: issue date = Monday of horizon week k, terms + delay
            receipt_date = wk_start + timedelta(days=terms + round(delay))
            recv_week = date_to_week(receipt_date, as_of, n_weeks)
            if recv_week is None:
                continue

            receipts_by_week[recv_week].append({
                "source": "R2",
                "segment": seg_code,
                "issue_week": k,
                "receipt_date": receipt_date,
                "amount": round(forecast_gross, 2),
                "amount_net": round(forecast_net, 2),
                "seasonal_factor": round(sf, 4),
            })

        seasonal_factors[seg_code] = seg_sf

    return dict(receipts_by_week), seasonal_factors


# ── P1: Open payables ────────────────────────────────────────────────────────

def p1_open_payables(
    open_ap: list[dict],
    as_of: date,
    n_weeks: int = 13,
) -> dict[int, list[dict]]:
    """
    Pay on due_date (company policy). If due_date < as_of, pay in week 1.

    open_ap: {invoice_id, supp_code, due_date, outstanding_amount, ...}
    """
    payments_by_week: dict[int, list[dict]] = defaultdict(list)

    for inv in open_ap:
        due: date = inv["due_date"]
        if due < as_of:
            due = as_of        # already overdue → pay now
        outstanding = float(inv["outstanding_amount"])
        week = date_to_week(due, as_of, n_weeks)
        if week is None:
            continue  # beyond 13-week horizon
        payments_by_week[week].append({
            "invoice_id": inv["invoice_id"],
            "supp_code": inv.get("supp_code", ""),
            "due_date": due,
            "amount": outstanding,
            "source": "P1",
        })

    return dict(payments_by_week)


# ── P2: Future purchases not yet invoiced ────────────────────────────────────

def p2_future_purchases(
    r2_receipts: dict[int, list[dict]],  # output of r2_future_sales
    gross_margin: float,
    vat_rate: float,
    supplier_term_mix: list[dict],       # [{share, payment_terms_days}]
    as_of: date,
    n_weeks: int = 13,
) -> dict[int, list[dict]]:
    """
    Returns payments_by_week for future purchases matching R2 forecast sales.
    """
    # First aggregate R2 net forecast per issue_week
    net_by_week: dict[int, float] = defaultdict(float)
    for week, items in r2_receipts.items():
        for item in items:
            issue_week = item.get("issue_week", week)
            net_by_week[issue_week] += float(item.get("amount_net", 0.0))

    payments_by_week: dict[int, list[dict]] = defaultdict(list)
    weeks = week_starts(as_of, n_weeks)

    for issue_k, net_sales in net_by_week.items():
        if issue_k < 1 or issue_k > n_weeks:
            continue
        issue_wk_start = weeks[issue_k - 1]
        purchase_net = net_sales * (1.0 - gross_margin)

        for tier in supplier_term_mix:
            share = float(tier["share"])
            terms = int(tier["payment_terms_days"])
            tier_net = purchase_net * share
            tier_gross = tier_net * (1.0 + vat_rate)
            due_date = issue_wk_start + timedelta(days=terms)
            pay_week = date_to_week(due_date, as_of, n_weeks)
            if pay_week is None:
                continue
            payments_by_week[pay_week].append({
                "source": "P2",
                "issue_week": issue_k,
                "tier": tier.get("tier", ""),
                "due_date": due_date,
                "amount": round(tier_gross, 2),
                "amount_net": round(tier_net, 2),
            })

    return dict(payments_by_week)


# ── P4: Recurring outflows ───────────────────────────────────────────────────

def p4_recurring(
    recurring_rules: list[dict],   # from hm.recurring_outflows (kind, rule JSONB, amount)
    as_of: date,
    n_weeks: int = 13,
) -> dict[int, list[dict]]:
    """
    Expand recurring-outflow rules into per-week payments.

    Rules supported:
      payroll_net  : {"day": "last_working"}
      payroll_social: {"day_of_month": 15}
      rent         : {"day_of_month": 1}
      opex         : {"day_of_month": 5}
      tax_advance  : {"months": [...], "day": 10}
      vat          : handled separately in P5; skip here
    """
    import calendar as cal_mod

    horizon_end = as_of + timedelta(weeks=n_weeks) - timedelta(days=1)
    payments_by_week: dict[int, list[dict]] = defaultdict(list)

    for rec in recurring_rules:
        kind = rec["kind"]
        if kind == "vat":
            continue  # handled by P5
        rule: dict = rec["rule"]
        amount = float(rec["amount"])

        dates_in_horizon: list[date] = []

        if kind in ("rent", "opex", "payroll_social"):
            dom = int(rule.get("day_of_month", 1))
            following = bool(rule.get("following_month", False))
            # Iterate every month in horizon range
            y, m = as_of.year, as_of.month
            while True:
                try:
                    d = date(y, m, dom)
                except ValueError:
                    # dom > days in month (e.g. 31 in Feb) → skip
                    pass
                else:
                    if as_of <= d <= horizon_end:
                        dates_in_horizon.append(d)
                m += 1
                if m > 12:
                    m = 1
                    y += 1
                if date(y, m, 1) > horizon_end + timedelta(days=31):
                    break

        elif kind == "payroll_net":
            y, m = as_of.year, as_of.month
            while True:
                d = last_working_day(y, m)
                if d > horizon_end:
                    break
                if d >= as_of:
                    dates_in_horizon.append(d)
                m += 1
                if m > 12:
                    m = 1
                    y += 1

        elif kind == "tax_advance":
            tax_months = rule.get("months", [3, 6, 9, 12])
            tax_day = int(rule.get("day", 10))
            y, m = as_of.year, as_of.month
            while True:
                if m in tax_months:
                    try:
                        d = date(y, m, tax_day)
                    except ValueError:
                        pass
                    else:
                        if as_of <= d <= horizon_end:
                            dates_in_horizon.append(d)
                m += 1
                if m > 12:
                    m = 1
                    y += 1
                if date(y, m, 1) > horizon_end + timedelta(days=31):
                    break

        for d in dates_in_horizon:
            week = date_to_week(d, as_of, n_weeks)
            if week is not None:
                payments_by_week[week].append({
                    "source": "P4",
                    "kind": kind,
                    "date": d,
                    "amount": amount,
                })

    return dict(payments_by_week)


# ── P5: VAT payments ─────────────────────────────────────────────────────────

def p5_vat(
    history_ar: list[dict],    # {issue_date, vat, ...}
    history_ap: list[dict],    # {issue_date, vat, ...}
    r2_by_week: dict[int, list[dict]],  # R2 forecast, for forecast months
    p2_by_week: dict[int, list[dict]],  # P2 forecast
    as_of: date,
    vat_return_day: int,
    n_weeks: int = 13,
) -> dict[int, list[dict]]:
    """
    Net VAT due on the 15th of each following month.
    September uses actual invoices; October+ uses actual + forecast.
    """
    horizon_end = as_of + timedelta(weeks=n_weeks) - timedelta(days=1)
    payments_by_week: dict[int, list[dict]] = defaultdict(list)

    # Collect actual VAT per month from history
    ar_vat_by_month: dict[tuple[int, int], float] = defaultdict(float)
    ap_vat_by_month: dict[tuple[int, int], float] = defaultdict(float)

    for inv in history_ar:
        d: date = inv["issue_date"]
        ar_vat_by_month[(d.year, d.month)] += float(inv.get("vat", 0.0))

    for inv in history_ap:
        d = inv["issue_date"]
        ap_vat_by_month[(d.year, d.month)] += float(inv.get("vat", 0.0))

    # Add R2 forecast VAT (for horizon months)
    for _week, items in r2_by_week.items():
        for item in items:
            # R2 items have issue_week; derive issue month from as_of + weeks
            issue_wk = item.get("issue_week", _week)
            issue_date = as_of + timedelta(weeks=issue_wk - 1)
            net = float(item.get("amount_net", 0.0))
            vat = net * 0.17  # approximate; actual rate embedded in amount
            ar_vat_by_month[(issue_date.year, issue_date.month)] += vat

    # Add P2 forecast VAT for horizon months
    for _week, items in p2_by_week.items():
        for item in items:
            issue_wk = item.get("issue_week", _week)
            issue_date = as_of + timedelta(weeks=issue_wk - 1)
            net = float(item.get("amount_net", 0.0))
            vat = net * 0.17
            ap_vat_by_month[(issue_date.year, issue_date.month)] += vat

    # For each month, compute net VAT due on vat_return_day of the following month
    # Cover months that had invoices and whose VAT payment date falls in horizon
    processed_months: set[tuple[int, int]] = set()
    all_months = set(ar_vat_by_month) | set(ap_vat_by_month)

    for (y, m) in sorted(all_months):
        if (y, m) in processed_months:
            continue
        processed_months.add((y, m))

        nm = m + 1
        ny = y + (1 if nm > 12 else 0)
        nm = (nm - 1) % 12 + 1
        try:
            pay_date = date(ny, nm, vat_return_day)
        except ValueError:
            continue

        if pay_date < as_of or pay_date > horizon_end:
            continue

        output_vat = ar_vat_by_month.get((y, m), 0.0)
        input_vat  = ap_vat_by_month.get((y, m), 0.0)
        net_vat = output_vat - input_vat
        if net_vat <= 0:
            continue  # refund or zero — omit (refund handling is deferred to later phase)

        week = date_to_week(pay_date, as_of, n_weeks)
        if week is not None:
            payments_by_week[week].append({
                "source": "P5",
                "vat_month": f"{y}-{m:02d}",
                "pay_date": pay_date,
                "amount": round(net_vat, 2),
            })

    return dict(payments_by_week)


# ── Aggregation ───────────────────────────────────────────────────────────────

def aggregate_weekly(
    opening_balance: float,
    receipts_by_week: dict[int, list[dict]],
    payments_by_week: dict[int, list[dict]],
    as_of: date,
    n_weeks: int = 13,
) -> list[dict]:
    """
    Produce the weekly balance table.

    Returns list of 13 dicts:
      {week, week_start, week_end, opening, receipts, payments, closing,
       receipt_items, payment_items}
    """
    weeks = week_starts(as_of, n_weeks)
    table: list[dict] = []
    balance = opening_balance

    for k_idx, wk_start in enumerate(weeks):
        k = k_idx + 1
        wk_end = wk_start + timedelta(days=6)
        rec_items = receipts_by_week.get(k, [])
        pay_items = payments_by_week.get(k, [])

        receipts_total = sum(float(item["amount"]) for item in rec_items)
        payments_total = sum(float(item["amount"]) for item in pay_items)

        opening_k = balance
        closing_k = opening_k + receipts_total - payments_total
        balance = closing_k

        table.append({
            "week": k,
            "week_start": wk_start,
            "week_end": wk_end,
            "opening": round(opening_k, 2),
            "receipts": round(receipts_total, 2),
            "payments": round(payments_total, 2),
            "closing": round(closing_k, 2),
            "receipt_items": rec_items,
            "payment_items": pay_items,
        })

    return table
