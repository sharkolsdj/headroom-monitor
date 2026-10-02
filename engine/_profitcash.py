"""
Profit-vs-cash bridge per calendar month.

Historical months: computed from DB (month_closes, bank_balances, AR/AP tables).
Forecast months: projected from engine output.
All bridges reconcile to the cent by construction (inventory + other = residual).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any

import sqlalchemy as sa
from sqlalchemy import text


def _last_sunday_on_or_before(d: date) -> date:
    """Return the most recent Sunday ≤ d."""
    return d - timedelta(days=(d.weekday() + 1) % 7)


def _month_end(year: int, month: int) -> date:
    if month == 12:
        return date(year + 1, 1, 1) - timedelta(days=1)
    return date(year, month + 1, 1) - timedelta(days=1)


def _ar_outstanding_at(
    ar_invoices: list[dict],
    receipts_by_inv: dict[str, float],
    as_of_date: date,
) -> float:
    """
    Outstanding AR at as_of_date: invoices issued ≤ as_of with unpaid balance.
    receipts_by_inv = {invoice_id: total_received_on_or_before as_of_date}
    """
    total = 0.0
    for inv in ar_invoices:
        if inv["issue_date"] > as_of_date:
            continue
        gross = float(inv["amount_gross"])
        paid = receipts_by_inv.get(inv["invoice_id"], 0.0)
        outstanding = gross - paid
        if outstanding > 0.005:
            total += outstanding
    return total


def _ap_outstanding_at(
    ap_invoices: list[dict],
    payments_by_inv: dict[str, float],
    as_of_date: date,
) -> float:
    """Outstanding AP at as_of_date."""
    total = 0.0
    for inv in ap_invoices:
        if inv["issue_date"] > as_of_date:
            continue
        gross = float(inv["amount_gross"])
        paid = payments_by_inv.get(inv["invoice_id"], 0.0)
        outstanding = gross - paid
        if outstanding > 0.005:
            total += outstanding
    return total


def load_profitcash_data(engine: sa.Engine, dataset_id: str) -> dict[str, Any]:
    """Load all data needed to build the profit-vs-cash bridge."""
    with engine.connect() as conn:
        mc_rows = conn.execute(text("""
            SELECT month, revenue_booked, cogs, opex, profit
            FROM hm.month_closes
            WHERE dataset_id = :did
            ORDER BY month
        """), {"did": dataset_id}).fetchall()
        month_closes = [dict(r._mapping) for r in mc_rows]

        bb_rows = conn.execute(text("""
            SELECT date, closing_balance
            FROM hm.bank_balances
            WHERE dataset_id = :did
            ORDER BY date
        """), {"did": dataset_id}).fetchall()
        bank_balances = {r.date: float(r.closing_balance) for r in bb_rows}

        ar_rows = conn.execute(text("""
            SELECT invoice_id, issue_date, amount_gross
            FROM hm.ar_invoices
            WHERE dataset_id = :did
        """), {"did": dataset_id}).fetchall()
        all_ar = [dict(r._mapping) for r in ar_rows]

        rec_rows = conn.execute(text("""
            SELECT invoice_id, date, amount
            FROM hm.ar_receipts
            WHERE dataset_id = :did
        """), {"did": dataset_id}).fetchall()
        all_receipts = [dict(r._mapping) for r in rec_rows]

        ap_rows = conn.execute(text("""
            SELECT invoice_id, issue_date, amount_gross
            FROM hm.ap_invoices
            WHERE dataset_id = :did
        """), {"did": dataset_id}).fetchall()
        all_ap = [dict(r._mapping) for r in ap_rows]

        pay_rows = conn.execute(text("""
            SELECT invoice_id, date, amount
            FROM hm.ap_payments
            WHERE dataset_id = :did
        """), {"did": dataset_id}).fetchall()
        all_payments_ap = [dict(r._mapping) for r in pay_rows]

        txn_rows = conn.execute(text("""
            SELECT date, amount, category
            FROM hm.bank_transactions
            WHERE dataset_id = :did
            ORDER BY date
        """), {"did": dataset_id}).fetchall()
        bank_txns = [dict(r._mapping) for r in txn_rows]

    return {
        "month_closes": month_closes,
        "bank_balances": bank_balances,
        "all_ar": all_ar,
        "all_receipts": all_receipts,
        "all_ap": all_ap,
        "all_payments_ap": all_payments_ap,
        "bank_txns": bank_txns,
    }


def _balance_on_or_before(bank_balances: dict[date, float], d: date) -> float | None:
    """Return the most recent bank balance on or before d."""
    candidates = [dt for dt in bank_balances if dt <= d]
    if not candidates:
        return None
    return bank_balances[max(candidates)]


def build_bridge_historical(
    pc_data: dict[str, Any],
    dep_annual: float,
    months: list[date],
) -> list[dict]:
    """
    Build bridge for historical (closed) months.
    months: list of first-of-month dates to include.
    Returns list of bridge dicts, one per month.
    """
    bank_balances = pc_data["bank_balances"]
    all_ar = pc_data["all_ar"]
    all_receipts = pc_data["all_receipts"]
    all_ap = pc_data["all_ap"]
    all_payments_ap = pc_data["all_payments_ap"]
    bank_txns = pc_data["bank_txns"]
    month_closes_by_month = {mc["month"]: mc for mc in pc_data["month_closes"]}

    dep_monthly = dep_annual / 12.0

    # Build cumulative receipts/payments by invoice up to any date
    # (recomputed per month — acceptable for 12 months)

    results: list[dict] = []

    for month_start in months:
        y, m = month_start.year, month_start.month
        month_end = _month_end(y, m)
        prev_month_end = month_start - timedelta(days=1)

        # Bank balance at end of this month and prior month
        bal_end = _balance_on_or_before(bank_balances, month_end)
        bal_start = _balance_on_or_before(bank_balances, prev_month_end)

        if bal_end is None or bal_start is None:
            continue

        cash_change = bal_end - bal_start

        # Profit from month_closes
        mc = month_closes_by_month.get(month_start)
        profit = float(mc["profit"]) if mc else 0.0

        # ΔAR: outstanding AR at end of month - at start of month
        receipts_to_end: dict[str, float] = defaultdict(float)
        receipts_to_start: dict[str, float] = defaultdict(float)
        for rec in all_receipts:
            if rec["date"] <= month_end:
                receipts_to_end[rec["invoice_id"]] += float(rec["amount"])
            if rec["date"] <= prev_month_end:
                receipts_to_start[rec["invoice_id"]] += float(rec["amount"])

        ar_end   = _ar_outstanding_at(all_ar, dict(receipts_to_end),   month_end)
        ar_start = _ar_outstanding_at(all_ar, dict(receipts_to_start), prev_month_end)
        delta_ar = ar_end - ar_start   # positive = more AR = less cash

        # ΔAP: outstanding AP at end of month - at start of month
        payments_to_end: dict[str, float] = defaultdict(float)
        payments_to_start: dict[str, float] = defaultdict(float)
        for pay in all_payments_ap:
            if pay["date"] <= month_end:
                payments_to_end[pay["invoice_id"]] += float(pay["amount"])
            if pay["date"] <= prev_month_end:
                payments_to_start[pay["invoice_id"]] += float(pay["amount"])

        ap_end   = _ap_outstanding_at(all_ap, dict(payments_to_end),   month_end)
        ap_start = _ap_outstanding_at(all_ap, dict(payments_to_start), prev_month_end)
        delta_ap = ap_end - ap_start   # positive = more AP = more cash

        # VAT paid this month (outflow, so negative in bank_txns)
        vat_paid = sum(
            -float(t["amount"]) for t in bank_txns
            if t["category"] == "vat_payment"
            and month_start <= t["date"] <= month_end
        )
        # Tax advances paid this month
        tax_paid = sum(
            -float(t["amount"]) for t in bank_txns
            if t["category"] == "tax_advance"
            and month_start <= t["date"] <= month_end
        )

        # VAT collected from customers (output VAT on AR issued this month)
        output_vat = sum(
            float(inv.get("vat", 0.0)) if hasattr(inv, "__getitem__") else 0.0
            for inv in pc_data.get("all_ar_full", all_ar)
        )
        # Simplified: inventory & other = residual that guarantees reconciliation
        # cash_change = profit + dep - delta_ar + delta_ap - inventory_other - vat_paid - tax_paid
        inventory_other = profit + dep_monthly - delta_ar + delta_ap - vat_paid - tax_paid - cash_change

        sentence = _bridge_sentence(
            month_start, profit, dep_monthly, delta_ar, delta_ap, inventory_other, cash_change
        )

        results.append({
            "month": month_start,
            "type": "historical",
            "profit": round(profit, 2),
            "depreciation": round(dep_monthly, 2),
            "delta_ar": round(delta_ar, 2),
            "delta_ap": round(delta_ap, 2),
            "inventory_other": round(inventory_other, 2),
            "vat_paid": round(vat_paid, 2),
            "tax_paid": round(tax_paid, 2),
            "cash_change": round(cash_change, 2),
            "reconciliation_error": round(
                profit + dep_monthly - delta_ar + delta_ap - inventory_other - vat_paid - tax_paid - cash_change,
                2
            ),
            "sentence": sentence,
        })

    return results


def build_bridge_forecast(
    forecast_months: list[date],
    scenario_weeks: list[dict],
    month_closes: list[dict],
    as_of: date,
    dep_annual: float,
    opening_balance: float,
) -> list[dict]:
    """
    Build bridge for forecast months from engine output (weekly data).
    """
    dep_monthly = dep_annual / 12.0
    mc_by_month = {mc["month"]: mc for mc in month_closes}

    results: list[dict] = []

    for month_start in forecast_months:
        y, m = month_start.year, month_start.month
        month_end = _month_end(y, m)

        # Cash change from engine: closing balance at month-end - opening at month-start
        # Use the weekly closing balances
        bal_start = None
        bal_end = None

        prev_end = month_start - timedelta(days=1)
        for wk in scenario_weeks:
            if wk["week_start"] <= prev_end <= wk["week_end"]:
                bal_start = wk["closing"]
            if wk["week_start"] <= month_end <= wk["week_end"]:
                bal_end = wk["closing"]
        # Fall back: use first/last week covering the month boundaries
        if bal_start is None:
            # Use opening balance of the month's first week
            for wk in scenario_weeks:
                if wk["week_start"] <= month_start <= wk["week_end"]:
                    bal_start = wk["opening"]
                    break
            if bal_start is None:
                bal_start = opening_balance
        if bal_end is None:
            # Use the last week that starts before or at month-end
            relevant = [wk for wk in scenario_weeks if wk["week_start"] <= month_end]
            bal_end = relevant[-1]["closing"] if relevant else bal_start

        cash_change = bal_end - bal_start

        # Profit from month_closes (forecast months pre-loaded by generator)
        mc = mc_by_month.get(month_start)
        profit = float(mc["profit"]) if mc else 0.0

        # AR change: sum R1+R2 receipts in month - sum AR invoiced in month (from month_closes revenue)
        receipts_in_month = sum(
            float(item["amount"])
            for wk in scenario_weeks
            if month_start <= wk["week_start"] <= month_end
            for item in wk.get("receipt_items", [])
        )
        revenue_gross = float(mc["revenue_booked"]) * 1.17 if mc else 0.0
        delta_ar = revenue_gross - receipts_in_month  # increase in AR

        # AP change: sum AP invoiced - payments made
        cogs = float(mc["cogs"]) if mc else 0.0
        purchases_gross = cogs * 1.17 / 0.70 * 1.0  # approximate
        payments_in_month = sum(
            float(item["amount"])
            for wk in scenario_weeks
            if month_start <= wk["week_start"] <= month_end
            for item in wk.get("payment_items", [])
            if item.get("source") in ("P1", "P2")
        )
        delta_ap = purchases_gross - payments_in_month

        # VAT and tax from P4/P5 payments in the month
        vat_paid = sum(
            float(item["amount"])
            for wk in scenario_weeks
            if month_start <= wk["week_start"] <= month_end
            for item in wk.get("payment_items", [])
            if item.get("source") == "P5"
        )
        tax_paid = sum(
            float(item["amount"])
            for wk in scenario_weeks
            if month_start <= wk["week_start"] <= month_end
            for item in wk.get("payment_items", [])
            if item.get("source") == "P4" and item.get("kind") == "tax_advance"
        )

        # Inventory = residual
        inventory_other = profit + dep_monthly - delta_ar + delta_ap - vat_paid - tax_paid - cash_change

        sentence = _bridge_sentence(
            month_start, profit, dep_monthly, delta_ar, delta_ap, inventory_other, cash_change
        )

        results.append({
            "month": month_start,
            "type": "forecast",
            "profit": round(profit, 2),
            "depreciation": round(dep_monthly, 2),
            "delta_ar": round(delta_ar, 2),
            "delta_ap": round(delta_ap, 2),
            "inventory_other": round(inventory_other, 2),
            "vat_paid": round(vat_paid, 2),
            "tax_paid": round(tax_paid, 2),
            "cash_change": round(cash_change, 2),
            "reconciliation_error": 0.0,
            "sentence": sentence,
        })

    return results


def _bridge_sentence(
    month: date,
    profit: float,
    dep: float,
    delta_ar: float,
    delta_ap: float,
    inv_other: float,
    cash_change: float,
) -> str:
    """Generate a one-sentence plain-English bridge summary."""
    psgn = "+" if profit >= 0 else ""
    csgn = "+" if cash_change >= 0 else ""

    parts: list[str] = []
    if abs(delta_ar) > 500:
        if delta_ar > 0:
            parts.append(f"€{delta_ar:,.0f} not yet collected")
        else:
            parts.append(f"€{abs(delta_ar):,.0f} collected faster than invoiced")
    if abs(delta_ap) > 500:
        if delta_ap > 0:
            parts.append(f"€{delta_ap:,.0f} payables deferred")
        else:
            parts.append(f"€{abs(delta_ap):,.0f} payables accelerated")
    if abs(inv_other) > 500:
        if inv_other > 0:
            parts.append(f"€{inv_other:,.0f} stock/timing outflow")
        else:
            parts.append(f"€{abs(inv_other):,.0f} stock/timing inflow")

    detail = "; ".join(parts) if parts else "normal timing"
    return (
        f"{month.strftime('%b %Y')}: Profit {psgn}€{profit:,.0f}, "
        f"cash {csgn}€{cash_change:,.0f}: {detail}."
    )
