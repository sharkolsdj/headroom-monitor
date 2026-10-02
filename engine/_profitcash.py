"""
Profit-vs-cash bridge per calendar month.

Historical months: computed from DB (month_closes, bank_transactions, AR/AP tables).
Forecast months: projected from engine output.

cash_change = sum(bank_transactions) for the calendar month — aligned with accrual
items (delta_ar, delta_ap) which are also calendar-month based.
Inventory & other = residual; VAT paid and tax paid are shown as explicit lines.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any

import sqlalchemy as sa
from sqlalchemy import text


def _month_end(year: int, month: int) -> date:
    if month == 12:
        return date(year + 1, 1, 1) - timedelta(days=1)
    return date(year, month + 1, 1) - timedelta(days=1)


def _ar_outstanding_at(
    ar_invoices: list[dict],
    receipts_by_inv: dict[str, float],
    as_of_date: date,
) -> float:
    """Outstanding AR balance at as_of_date (gross, issued ≤ date, unpaid)."""
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
    """Outstanding AP balance at as_of_date."""
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
            FROM hm.month_closes WHERE dataset_id = :did ORDER BY month
        """), {"did": dataset_id}).fetchall()
        month_closes = [dict(r._mapping) for r in mc_rows]

        bb_rows = conn.execute(text("""
            SELECT date, closing_balance FROM hm.bank_balances
            WHERE dataset_id = :did ORDER BY date
        """), {"did": dataset_id}).fetchall()
        bank_balances = {r.date: float(r.closing_balance) for r in bb_rows}

        ar_rows = conn.execute(text("""
            SELECT invoice_id, issue_date, amount_gross FROM hm.ar_invoices
            WHERE dataset_id = :did
        """), {"did": dataset_id}).fetchall()
        all_ar = [dict(r._mapping) for r in ar_rows]

        rec_rows = conn.execute(text("""
            SELECT invoice_id, date, amount FROM hm.ar_receipts WHERE dataset_id = :did
        """), {"did": dataset_id}).fetchall()
        all_receipts = [dict(r._mapping) for r in rec_rows]

        ap_rows = conn.execute(text("""
            SELECT invoice_id, issue_date, amount_gross FROM hm.ap_invoices
            WHERE dataset_id = :did
        """), {"did": dataset_id}).fetchall()
        all_ap = [dict(r._mapping) for r in ap_rows]

        pay_rows = conn.execute(text("""
            SELECT invoice_id, date, amount FROM hm.ap_payments WHERE dataset_id = :did
        """), {"did": dataset_id}).fetchall()
        all_payments_ap = [dict(r._mapping) for r in pay_rows]

        txn_rows = conn.execute(text("""
            SELECT date, amount, category FROM hm.bank_transactions
            WHERE dataset_id = :did ORDER BY date
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


def build_bridge_historical(
    pc_data: dict[str, Any],
    dep_annual: float,
    months: list[date],
) -> list[dict]:
    """
    Build bridge for historical (closed) months.
    cash_change = sum(bank_transactions) in the calendar month.
    """
    all_ar = pc_data["all_ar"]
    all_receipts = pc_data["all_receipts"]
    all_ap = pc_data["all_ap"]
    all_payments_ap = pc_data["all_payments_ap"]
    bank_txns = pc_data["bank_txns"]
    month_closes_by_month = {mc["month"]: mc for mc in pc_data["month_closes"]}

    dep_monthly = dep_annual / 12.0
    results: list[dict] = []

    for month_start in months:
        y, m = month_start.year, month_start.month
        month_end = _month_end(y, m)
        prev_month_end = month_start - timedelta(days=1)

        # Cash change = sum of ALL bank transactions in the calendar month
        cash_change = sum(
            float(t["amount"]) for t in bank_txns
            if month_start <= t["date"] <= month_end
        )

        mc = month_closes_by_month.get(month_start)
        profit = float(mc["profit"]) if mc else 0.0

        # ΔAR: outstanding AR at month-end minus at prior month-end
        receipts_to_end: dict[str, float] = defaultdict(float)
        receipts_to_start: dict[str, float] = defaultdict(float)
        for rec in all_receipts:
            if rec["date"] <= month_end:
                receipts_to_end[rec["invoice_id"]] += float(rec["amount"])
            if rec["date"] <= prev_month_end:
                receipts_to_start[rec["invoice_id"]] += float(rec["amount"])

        ar_end   = _ar_outstanding_at(all_ar, dict(receipts_to_end),   month_end)
        ar_start = _ar_outstanding_at(all_ar, dict(receipts_to_start), prev_month_end)
        delta_ar = ar_end - ar_start   # positive = more owed → less cash collected

        # ΔAP: outstanding AP at month-end minus at prior month-end
        payments_to_end: dict[str, float] = defaultdict(float)
        payments_to_start: dict[str, float] = defaultdict(float)
        for pay in all_payments_ap:
            if pay["date"] <= month_end:
                payments_to_end[pay["invoice_id"]] += float(pay["amount"])
            if pay["date"] <= prev_month_end:
                payments_to_start[pay["invoice_id"]] += float(pay["amount"])

        ap_end   = _ap_outstanding_at(all_ap, dict(payments_to_end),   month_end)
        ap_start = _ap_outstanding_at(all_ap, dict(payments_to_start), prev_month_end)
        delta_ap = ap_end - ap_start   # positive = more owed to suppliers → cash not yet paid

        # VAT and tax paid this calendar month (explicit lines)
        vat_paid = sum(
            -float(t["amount"]) for t in bank_txns
            if t["category"] == "vat_payment" and month_start <= t["date"] <= month_end
        )
        tax_paid = sum(
            -float(t["amount"]) for t in bank_txns
            if t["category"] == "tax_advance" and month_start <= t["date"] <= month_end
        )

        # Inventory & other timing = residual (guarantees reconciliation to cent)
        inventory_other = (
            profit + dep_monthly - delta_ar + delta_ap - vat_paid - tax_paid - cash_change
        )

        recon = round(
            profit + dep_monthly - delta_ar + delta_ap
            - inventory_other - vat_paid - tax_paid - cash_change,
            2,
        )

        sentence = _bridge_sentence(
            month_start, profit, dep_monthly, delta_ar, delta_ap,
            inventory_other, vat_paid, tax_paid, cash_change, forecast=False,
        )

        results.append({
            "month": month_start,
            "type": "historical",
            "profit": round(profit, 2),
            "depreciation": round(dep_monthly, 2),
            "delta_ar": round(delta_ar, 2),
            "delta_ap": round(delta_ap, 2),
            "vat_paid": round(vat_paid, 2),
            "tax_paid": round(tax_paid, 2),
            "inventory_other": round(inventory_other, 2),
            "cash_change": round(cash_change, 2),
            "reconciliation_error": recon,
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
    """Build bridge for forecast months from engine weekly output."""
    dep_monthly = dep_annual / 12.0
    mc_by_month = {mc["month"]: mc for mc in month_closes}
    results: list[dict] = []

    for month_start in forecast_months:
        y, m = month_start.year, month_start.month
        month_end = _month_end(y, m)

        # Cash change from engine: closing balance at month-end − at month-start
        bal_start = None
        bal_end = None
        prev_end = month_start - timedelta(days=1)
        for wk in scenario_weeks:
            if wk["week_start"] <= prev_end <= wk["week_end"] and bal_start is None:
                bal_start = wk["closing"]
            if wk["week_start"] <= month_end <= wk["week_end"] and bal_end is None:
                bal_end = wk["closing"]
        if bal_start is None:
            for wk in scenario_weeks:
                if wk["week_start"] <= month_start <= wk["week_end"]:
                    bal_start = wk["opening"]; break
            if bal_start is None:
                bal_start = opening_balance
        if bal_end is None:
            relevant = [wk for wk in scenario_weeks if wk["week_start"] <= month_end]
            bal_end = relevant[-1]["closing"] if relevant else bal_start

        cash_change = bal_end - bal_start

        mc = mc_by_month.get(month_start)
        profit = float(mc["profit"]) if mc else 0.0

        # AR change: revenue invoiced in month vs receipts collected in month
        revenue_gross = float(mc["revenue_booked"]) * 1.17 if mc else 0.0
        receipts_in_month = sum(
            float(item["amount"])
            for wk in scenario_weeks
            if month_start <= wk["week_start"] <= month_end
            for item in wk.get("receipt_items", [])
        )
        delta_ar = revenue_gross - receipts_in_month

        # AP change: purchases invoiced in month vs payments made in month
        cogs = float(mc["cogs"]) if mc else 0.0
        purchases_gross = cogs * 1.17
        payments_in_month = sum(
            float(item["amount"])
            for wk in scenario_weeks
            if month_start <= wk["week_start"] <= month_end
            for item in wk.get("payment_items", [])
            if item.get("source") in ("P1", "P2")
        )
        delta_ap = purchases_gross - payments_in_month

        # VAT and tax
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

        inventory_other = (
            profit + dep_monthly - delta_ar + delta_ap - vat_paid - tax_paid - cash_change
        )

        sentence = _bridge_sentence(
            month_start, profit, dep_monthly, delta_ar, delta_ap,
            inventory_other, vat_paid, tax_paid, cash_change, forecast=True,
        )

        results.append({
            "month": month_start,
            "type": "forecast",
            "profit": round(profit, 2),
            "depreciation": round(dep_monthly, 2),
            "delta_ar": round(delta_ar, 2),
            "delta_ap": round(delta_ap, 2),
            "vat_paid": round(vat_paid, 2),
            "tax_paid": round(tax_paid, 2),
            "inventory_other": round(inventory_other, 2),
            "cash_change": round(cash_change, 2),
            "reconciliation_error": 0.0,
            "sentence": sentence,
        })

    return results


def _fmt(amount: float, abbrev: bool = False) -> str:
    if abbrev and abs(amount) >= 1_000:
        return f"€{abs(amount)/1000:,.0f}k"
    return f"€{abs(amount):,.0f}"


def _bridge_sentence(
    month: date,
    profit: float,
    dep: float,
    delta_ar: float,
    delta_ap: float,
    inv_other: float,
    vat_paid: float,
    tax_paid: float,
    cash_change: float,
    forecast: bool,
) -> str:
    """Plain-English one-sentence bridge summary for CFO."""
    tag = " (forecast)" if forecast else ""
    p_sign = "+" if profit >= 0 else ""
    c_sign = "+" if cash_change >= 0 else ""

    parts: list[str] = []

    if abs(delta_ar) > 500:
        if delta_ar > 0:
            parts.append(
                f"customers owed {_fmt(delta_ar, True)} more at month-end "
                f"(invoiced but not yet collected)"
            )
        else:
            parts.append(
                f"customers reduced their outstanding balance by {_fmt(-delta_ar, True)}, "
                f"collecting more than was invoiced"
            )

    if abs(delta_ap) > 500:
        if delta_ap > 0:
            parts.append(
                f"{_fmt(delta_ap, True)} in new supplier invoices not yet paid "
                f"(temporary cash buffer)"
            )
        else:
            parts.append(
                f"{_fmt(-delta_ap, True)} more paid to suppliers than newly invoiced"
            )

    if vat_paid > 500:
        parts.append(f"VAT of {_fmt(vat_paid, True)} paid to tax authority")

    if tax_paid > 500:
        parts.append(f"quarterly tax advance of {_fmt(tax_paid, True)} paid")

    if abs(inv_other) > 500:
        if inv_other > 0:
            parts.append(f"{_fmt(inv_other, True)} paid for stock or other timing items")
        else:
            parts.append(f"{_fmt(-inv_other, True)} timing benefit (e.g. payroll accrual)")

    gap = cash_change - profit
    if abs(gap) < 500:
        detail = "cash and profit moved together"
    elif parts:
        detail = "; ".join(parts)
    else:
        detail = "no significant working-capital movement"

    profit_str = f"Profit {p_sign}{_fmt(profit, True)}"
    cash_str = f"cash {c_sign}{_fmt(cash_change, True)}"

    if abs(gap) < 500:
        return f"{month.strftime('%b %Y')}{tag}: {profit_str}, {cash_str} — {detail}."
    elif cash_change > profit:
        return (
            f"{month.strftime('%b %Y')}{tag}: {profit_str} but {cash_str} — {detail}."
        )
    else:
        return (
            f"{month.strftime('%b %Y')}{tag}: {profit_str} but {cash_str} — {detail}."
        )
