"""Day-by-day simulation engine producing all transactional records."""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import numpy as np

from ._cfg import Cfg
from .counterparties import Customer, Supplier
from .scenarios import ScenarioParams


# ── Result container ──────────────────────────────────────────────────────────

@dataclass
class SimResult:
    dataset_id: str
    seed: int
    as_of_date: date
    opening_balance: float

    counterparties_hm: list[dict]       # hm.counterparties rows
    ar_invoices: list[dict]             # hm.ar_invoices
    ar_receipts_hist: list[dict]        # hm.ar_receipts  (date <= as_of)
    ap_invoices: list[dict]             # hm.ap_invoices
    ap_payments_hist: list[dict]        # hm.ap_payments  (date <= as_of)
    bank_transactions: list[dict]       # hm.bank_transactions (date <= as_of)
    bank_balances: list[dict]           # hm.bank_balances (weekly, history)
    recurring_outflows: list[dict]      # hm.recurring_outflows
    month_closes: list[dict]            # hm.month_closes
    close_adjustments: list[dict]       # hm.close_adjustments

    future_ar_receipts: list[dict]      # eval.future_ar_receipts
    future_ap_payments: list[dict]      # eval.future_ap_payments
    future_bank_balances: list[dict]    # eval.future_bank_balances

    vault_entries: list[dict]           # (dataset_id, code, display_name, iban)

    scenario_truth: dict
    weekly_balances: dict[date, float]  # all weeks (history + future), keyed by week-start Monday


# ── Public entry point ────────────────────────────────────────────────────────

def simulate(cfg: Cfg, dataset_id: str, seed: int,
             customers: list[Customer], suppliers: list[Supplier],
             params: ScenarioParams) -> SimResult:

    rng = np.random.default_rng(seed)

    sim_start = cfg.history_start          # 2025-09-29 Monday
    forecast_end = cfg.forecast_end        # 2026-12-27 Sunday

    # Apply scenario-specific customer modifications
    customers = _apply_scenario_to_customers(customers, params, cfg, rng)

    # Generate all invoices and receipts
    ar_invoices, ar_receipts = _gen_ar(cfg, customers, params, rng,
                                       sim_start, forecast_end)
    ap_invoices, ap_payments = _gen_ap(cfg, suppliers, params, rng,
                                       sim_start, forecast_end)

    # Generate recurring outflows events
    recurring_events = _gen_recurring(cfg, params, sim_start, forecast_end)

    # Compute VAT cash flows
    vat_events = _gen_vat(ar_invoices, ap_invoices, cfg, sim_start, forecast_end)

    # All cash flow events: (date, amount, category, ref_type, ref_id)
    all_events: list[tuple[date, float, str, str, str]] = []
    for r in ar_receipts:
        all_events.append((r["date"], r["amount"], "ar_receipt", "receipt", r["receipt_id"]))
    for p in ap_payments:
        all_events.append((p["date"], -p["amount"], "ap_payment", "payment", p["payment_id"]))
    for ev in recurring_events:
        all_events.append((ev["date"], -ev["amount"], ev["category"], "recurring", ev["ref_id"]))
    for ev in vat_events:
        all_events.append((ev["date"], -ev["amount"], "vat_payment", "recurring", ev["ref_id"]))

    # Solve opening balance so as_of balance = target
    opening_balance = _solve_opening_balance(
        all_events, cfg.as_of_date, cfg.target_balance_as_of
    )

    # Compute daily and weekly balances
    daily_balances = _compute_daily_balances(
        opening_balance, all_events, sim_start, forecast_end
    )
    weekly_balances = _compute_weekly_balances(daily_balances, sim_start, forecast_end)

    # Split history vs future
    as_of = cfg.as_of_date

    ar_receipts_hist = [r for r in ar_receipts if r["date"] < as_of]
    future_ar_receipts = [r for r in ar_receipts if r["date"] >= as_of]

    ap_payments_hist = [p for p in ap_payments if p["date"] < as_of]
    future_ap_payments = [p for p in ap_payments if p["date"] >= as_of]

    # Bank transactions for history
    bank_txns = _build_bank_transactions(
        dataset_id, ar_receipts_hist, ap_payments_hist, recurring_events, vat_events, as_of
    )

    # Weekly bank balances
    hist_balances, future_balances = _split_weekly_balances(
        dataset_id, weekly_balances, as_of
    )

    # Month closes
    month_closes, close_adj = _build_month_closes(
        dataset_id, ar_invoices, ap_invoices, cfg, params, sim_start, forecast_end
    )

    # Vault entries
    vault_entries = [
        {"dataset_id": dataset_id, "code": c.code,
         "display_name": c.display_name, "iban": c.iban}
        for c in customers
    ]
    for s in suppliers:
        vault_entries.append({
            "dataset_id": dataset_id, "code": s.code,
            "display_name": s.display_name, "iban": s.iban,
        })

    # counterparties rows (no names)
    cp_rows = [
        {
            "dataset_id": dataset_id,
            "code": c.code,
            "kind": "customer",
            "nace": c.nace,
            "segment": c.segment,
            "size_band": c.size_band,
            "payment_terms_days": c.payment_terms_days,
            "onboarded_on": c.onboarded_on,
        }
        for c in customers
    ]
    for s in suppliers:
        cp_rows.append({
            "dataset_id": dataset_id,
            "code": s.code,
            "kind": "supplier",
            "nace": None,
            "segment": None,
            "size_band": s.tier,
            "payment_terms_days": s.payment_terms_days,
            "onboarded_on": sim_start,
        })

    # recurring_outflows config rows (for hm.recurring_outflows)
    recur_cfg_rows = _build_recurring_config(dataset_id, cfg)

    # Scenario truth
    truth = _build_truth(dataset_id, params, customers, ar_receipts,
                         weekly_balances, cfg)

    return SimResult(
        dataset_id=dataset_id,
        seed=seed,
        as_of_date=as_of,
        opening_balance=opening_balance,
        counterparties_hm=cp_rows,
        ar_invoices=[dict(r, dataset_id=dataset_id) for r in ar_invoices],
        ar_receipts_hist=[dict(r, dataset_id=dataset_id) for r in ar_receipts_hist],
        ap_invoices=[dict(r, dataset_id=dataset_id) for r in ap_invoices],
        ap_payments_hist=[dict(r, dataset_id=dataset_id) for r in ap_payments_hist],
        bank_transactions=bank_txns,
        bank_balances=hist_balances,
        recurring_outflows=recur_cfg_rows,
        month_closes=month_closes,
        close_adjustments=close_adj,
        future_ar_receipts=[dict(r, dataset_id=dataset_id) for r in future_ar_receipts],
        future_ap_payments=[dict(r, dataset_id=dataset_id) for r in future_ap_payments],
        future_bank_balances=future_balances,
        vault_entries=vault_entries,
        scenario_truth=truth,
        weekly_balances=weekly_balances,
    )


# ── AR generation ─────────────────────────────────────────────────────────────

def _gen_ar(cfg: Cfg, customers: list[Customer], params: ScenarioParams,
            rng: np.random.Generator, sim_start: date, sim_end: date
            ) -> tuple[list[dict], list[dict]]:

    invoices: list[dict] = []
    receipts: list[dict] = []

    inv_counter: dict[str, int] = defaultdict(int)
    rec_counter: dict[str, int] = defaultdict(int)

    partial_codes: set[str] = set()
    if params.partial_payments:
        # Will be determined after first pass
        pass

    for cust in customers:
        # S6 new customer: invoices are generated separately below
        if cust.code == "CUST_NC1":
            continue

        freq = cust.invoice_freq      # invoices per year
        interval = timedelta(days=round(365 / freq))

        # Start offset: spread customers so they don't all invoice on day 1
        offset_days = int(rng.integers(0, interval.days))
        first_date = sim_start + timedelta(days=offset_days)

        # Ensure first_date is a working day (Mon-Fri)
        first_date = _next_working_day(first_date)

        issue_date = first_date
        while issue_date <= sim_end:
            if issue_date < cust.onboarded_on:
                issue_date = _next_working_day(issue_date + interval)
                continue

            inv_counter[cust.code] += 1
            inv_id = f"AR_{cust.code}_{inv_counter[cust.code]:04d}"

            # Invoice amount = annual_revenue / freq ± noise
            base_amount = cust.annual_revenue / freq
            noise = 1.0 + float(rng.uniform(-cfg.invoice_noise, cfg.invoice_noise))
            amount_net = round(base_amount * noise, 2)
            vat_amount = round(amount_net * cfg.vat_rate, 2)
            amount_gross = round(amount_net + vat_amount, 2)

            due_date = issue_date + timedelta(days=cust.payment_terms_days)

            invoices.append({
                "invoice_id": inv_id,
                "cust_code": cust.code,
                "issue_date": issue_date,
                "due_date": due_date,
                "amount_net": amount_net,
                "vat": vat_amount,
                "amount_gross": amount_gross,
                "status": "paid",
            })

            # Receipt date
            receipt_date = _compute_receipt_date(
                due_date, cust, params, rng, cfg, issue_date
            )

            rec_counter[cust.code] += 1
            rec_id = f"REC_{cust.code}_{rec_counter[cust.code]:04d}"

            # S3: bankrupt customers never pay open invoices in the forecast horizon
            bankrupt_codes = params.sector_crisis.get("bankrupt_codes", set()) \
                if params.sector_crisis else set()
            is_bankrupt_forecast = (
                cust.code in bankrupt_codes and receipt_date >= cfg.as_of_date
            )

            if receipt_date <= sim_end and not is_bankrupt_forecast:
                receipts.append({
                    "receipt_id": rec_id,
                    "invoice_id": inv_id,
                    "date": receipt_date,
                    "amount": amount_gross,
                })

            issue_date = _next_working_day(issue_date + interval)

    # S6: add new customer invoices
    if params.new_customer:
        nc = params.new_customer
        nc_code = "CUST_NC1"  # special new customer code
        for i, (due, amount) in enumerate([
            (nc["invoice_1_due"], nc["invoice_1_amount"]),
            (nc["invoice_2_due"], nc["invoice_2_amount"]),
        ]):
            inv_id = f"AR_{nc_code}_{i+1:04d}"
            issue = due - timedelta(days=30)
            amount_net = amount
            vat_amount = round(amount_net * cfg.vat_rate, 2)
            amount_gross = round(amount_net + vat_amount, 2)
            invoices.append({
                "invoice_id": inv_id,
                "cust_code": nc_code,
                "issue_date": issue,
                "due_date": due,
                "amount_net": amount_net,
                "vat": vat_amount,
                "amount_gross": amount_gross,
                "status": "open",
            })
            # Slow archetype: mean 20 days late
            delay = max(cfg.delay_floor_days, round(float(rng.normal(20, 10))))
            receipt_date = due + timedelta(days=delay)
            if receipt_date <= sim_end:
                receipts.append({
                    "receipt_id": f"REC_{nc_code}_{i+1:04d}",
                    "invoice_id": inv_id,
                    "date": receipt_date,
                    "amount": amount_gross,
                })

    # S7: apply partial payment splits to a few invoices
    if params.partial_payments:
        receipts = _apply_partial_payments(invoices, receipts, params, rng, sim_end)

    return invoices, receipts


def _compute_receipt_date(due_date: date, cust: Customer,
                          params: ScenarioParams, rng: np.random.Generator,
                          cfg: Cfg, issue_date: date) -> date:
    # Base delay from archetype
    delay = float(rng.normal(cust.archetype_mean, cust.archetype_sd))
    delay = max(cfg.delay_floor_days, delay)

    # Sector stress modifier: delay × (1 + beta × (stress − 1))
    stress_mult = 1.0 + cfg.sector_stress_beta * (cust.stress_index - 1.0)
    delay = delay * stress_mult

    # S2: big-customer drift
    bcd = params.big_customer_drift
    if bcd and cust.code == bcd.get("target_code"):
        extra = _big_customer_extra_delay(due_date, bcd, cfg.as_of_date)
        delay += extra

    # S3: sector crisis for F41+F43 customers (except excluded top-5)
    sc = params.sector_crisis
    if sc:
        nace_codes = sc.get("nace_codes", ["F41"])
        affected = sc.get("affected_codes", set())
        if cust.nace in nace_codes and cust.code in affected:
            shock_start = sc["shock_start"]
            if issue_date >= shock_start:
                extra_min = sc.get("extra_delay_min", 30)
                extra_max = sc.get("extra_delay_max", 50)
                stress_idx = sc.get("stress_index", 1.0)
                delay += float(rng.uniform(extra_min, extra_max)) * stress_idx

    # Seasonality
    delay += _seasonality_extra(due_date, cust, cfg)

    # Month-end batching for public entities
    receipt_date = due_date + timedelta(days=round(delay))
    if cust.batch_payment_month_end:
        receipt_date = _next_month_end(receipt_date)

    return receipt_date


def _big_customer_extra_delay(due_date: date, bcd: dict, as_of: date) -> float:
    """Linear drift: from delay_from at drift_start to delay_to at as_of."""
    drift_start = bcd["drift_start"]
    delay_from = float(bcd.get("delay_from", 10))
    delay_to   = float(bcd.get("delay_to",   45))
    if due_date < drift_start:
        return 0.0
    total_days = (as_of - drift_start).days
    if total_days <= 0:
        return delay_to
    elapsed = min((due_date - drift_start).days, total_days)
    return delay_from + (delay_to - delay_from) * elapsed / total_days


def _seasonality_extra(due_date: date, cust: Customer, cfg: Cfg) -> float:
    extra = 0.0
    seas = cfg.seasonality
    if not seas:
        return extra

    # Construction leave windows (F41, F43)
    if cust.nace in ("F41", "F43"):
        cl = seas.get("construction_leave", {})
        cl_days = float(cl.get("extra_days", 10))
        for window in cl.get("windows", []):
            m, w = int(window["month"]), int(window["week"])
            wk = _iso_week_date(due_date.year, m, w)
            if wk and wk <= due_date < wk + timedelta(weeks=1):
                extra += cl_days

    # Year-end window
    ye = seas.get("year_end", {})
    if ye:
        ye_days = float(ye.get("extra_days", 7))
        start_str = ye.get("start", "12-20")
        end_str   = ye.get("end",   "01-05")
        sm, sd = int(start_str.split("-")[0]), int(start_str.split("-")[1])
        em, ed = int(end_str.split("-")[0]),   int(end_str.split("-")[1])
        in_window = (
            (due_date.month == sm and due_date.day >= sd) or
            (due_date.month == em and due_date.day <= ed)
        )
        if in_window:
            extra += ye_days
    return extra


def _iso_week_date(year: int, month: int, week_of_month: int) -> date | None:
    """Return the Monday of the nth week (1-based) of month/year."""
    try:
        d = date(year, month, 1)
        # Advance to Monday of the first week
        d += timedelta(days=(7 - d.weekday()) % 7)
        d += timedelta(weeks=week_of_month - 1)
        if d.month != month:
            return None
        return d
    except ValueError:
        return None


def _apply_partial_payments(invoices: list[dict], receipts: list[dict],
                             params: ScenarioParams, rng: np.random.Generator,
                             sim_end: date) -> list[dict]:
    """Split receipts for 3 customers: part on due date, rest 3-6 weeks later."""
    pp = params.partial_payments
    n = int(pp.get("n_customers", 3))
    ratio_min = float(pp.get("part_ratio_min", 0.50))
    ratio_max = float(pp.get("part_ratio_max", 0.70))

    # Pick n distinct customer codes from invoices that have receipts > as_of
    receipt_map = {r["invoice_id"]: r for r in receipts}
    candidates = list({inv["cust_code"] for inv in invoices
                       if inv["invoice_id"] in receipt_map})
    if len(candidates) < n:
        return receipts

    chosen = list(rng.choice(candidates, size=n, replace=False))
    chosen_set = set(chosen)
    new_receipts: list[dict] = []
    split_counter: dict[str, int] = defaultdict(int)

    for r in receipts:
        # Find the invoice to get cust_code
        inv = next((i for i in invoices if i["invoice_id"] == r["invoice_id"]), None)
        if inv is None or inv["cust_code"] not in chosen_set:
            new_receipts.append(r)
            continue

        ratio = float(rng.uniform(ratio_min, ratio_max))
        part1 = round(r["amount"] * ratio, 2)
        part2 = round(r["amount"] - part1, 2)
        split_counter[r["receipt_id"]] += 1

        new_receipts.append({
            "receipt_id": r["receipt_id"] + "_A",
            "invoice_id": r["invoice_id"],
            "date": r["date"],
            "amount": part1,
        })
        late_days = int(rng.integers(21, 43))  # 3-6 weeks
        late_date = r["date"] + timedelta(days=late_days)
        if late_date <= sim_end:
            new_receipts.append({
                "receipt_id": r["receipt_id"] + "_B",
                "invoice_id": r["invoice_id"],
                "date": late_date,
                "amount": part2,
            })

    return new_receipts


# ── AP generation ─────────────────────────────────────────────────────────────

def _gen_ap(cfg: Cfg, suppliers: list[Supplier], params: ScenarioParams,
            rng: np.random.Generator, sim_start: date, sim_end: date
            ) -> tuple[list[dict], list[dict]]:

    invoices: list[dict] = []
    payments: list[dict] = []
    inv_counter: dict[str, int] = defaultdict(int)
    pay_counter: dict[str, int] = defaultdict(int)

    for supp in suppliers:
        interval = timedelta(days=round(365 / supp.invoice_freq))
        offset_days = int(rng.integers(0, interval.days))
        issue_date = _next_working_day(sim_start + timedelta(days=offset_days))

        while issue_date <= sim_end:
            inv_counter[supp.code] += 1
            inv_id = f"AP_{supp.code}_{inv_counter[supp.code]:04d}"

            amount_net = round(supp.annual_purchases / supp.invoice_freq, 2)
            noise = 1.0 + float(rng.uniform(-0.10, 0.10))
            amount_net = round(amount_net * noise, 2)
            vat_amount = round(amount_net * cfg.vat_rate, 2)
            amount_gross = round(amount_net + vat_amount, 2)
            due_date = issue_date + timedelta(days=supp.payment_terms_days)

            invoices.append({
                "invoice_id": inv_id,
                "supp_code": supp.code,
                "issue_date": issue_date,
                "due_date": due_date,
                "amount_net": amount_net,
                "vat": vat_amount,
                "amount_gross": amount_gross,
                "status": "paid",
            })

            pay_date = due_date   # pay on due date (disciplined)
            if pay_date <= sim_end:
                pay_counter[supp.code] += 1
                pay_id = f"PAY_{supp.code}_{pay_counter[supp.code]:04d}"
                payments.append({
                    "payment_id": pay_id,
                    "invoice_id": inv_id,
                    "date": pay_date,
                    "amount": amount_gross,
                })

            issue_date = _next_working_day(issue_date + interval)

    # S2: extraordinary SUPP_01 invoice
    for xap in params.extraordinary_ap:
        inv_counter[xap["supp_code"]] += 1
        inv_id = f"AP_{xap['supp_code']}_X{inv_counter[xap['supp_code']]:04d}"
        amount_net = float(xap["amount_net"])
        vat_amount = round(amount_net * cfg.vat_rate, 2)
        amount_gross = round(amount_net + vat_amount, 2)
        invoices.append({
            "invoice_id": inv_id,
            "supp_code": xap["supp_code"],
            "issue_date": xap["issue_date"],
            "due_date": xap["due_date"],
            "amount_net": amount_net,
            "vat": vat_amount,
            "amount_gross": amount_gross,
            "status": "paid",
            "is_inventory": True,
            "note": xap.get("note", ""),
        })
        pay_counter[xap["supp_code"]] += 1
        pay_id = f"PAY_{xap['supp_code']}_X{pay_counter[xap['supp_code']]:04d}"
        if xap["due_date"] <= sim_end:
            payments.append({
                "payment_id": pay_id,
                "invoice_id": inv_id,
                "date": xap["due_date"],
                "amount": amount_gross,
            })

    # S4: extraordinary outflow spike
    sp = params.outflow_spike
    if sp:
        inv_counter[sp["supp_code"]] += 1
        inv_id = f"AP_{sp['supp_code']}_S4X{inv_counter[sp['supp_code']]:04d}"
        amount_net = float(sp["amount_net"])
        vat_amount = round(amount_net * cfg.vat_rate, 2)
        amount_gross = round(amount_net + vat_amount, 2)
        issue_date = sp["due_date"] - timedelta(days=60)
        invoices.append({
            "invoice_id": inv_id,
            "supp_code": sp["supp_code"],
            "issue_date": issue_date,
            "due_date": sp["due_date"],
            "amount_net": amount_net,
            "vat": vat_amount,
            "amount_gross": amount_gross,
            "status": "paid",
            "is_inventory": True,
        })
        pay_counter[sp["supp_code"]] += 1
        pay_id = f"PAY_{sp['supp_code']}_S4X{pay_counter[sp['supp_code']]:04d}"
        if sp["due_date"] <= sim_end:
            payments.append({
                "payment_id": pay_id,
                "invoice_id": inv_id,
                "date": sp["due_date"],
                "amount": amount_gross,
            })

    return invoices, payments


# ── Recurring outflows ────────────────────────────────────────────────────────

def _gen_recurring(cfg: Cfg, params: ScenarioParams,
                   sim_start: date, sim_end: date) -> list[dict]:
    events: list[dict] = []
    counter: dict[str, int] = defaultdict(int)

    d = sim_start
    while d <= sim_end:
        # Payroll net: last working day of each month
        if d == _last_working_day(d.year, d.month):
            counter["payroll_net"] += 1
            events.append({
                "date": d,
                "amount": cfg.payroll_net_monthly,
                "category": "payroll_net",
                "ref_id": f"PAY_NET_{d.year}{d.month:02d}",
            })

        # Payroll social: 15th of each month
        if d.day == 15:
            prev = _prev_month(d)
            counter["payroll_social"] += 1
            events.append({
                "date": d,
                "amount": cfg.payroll_social_monthly,
                "category": "payroll_social",
                "ref_id": f"PAY_SOC_{prev.year}{prev.month:02d}",
            })

        # Rent: 1st of month
        if d.day == 1:
            counter["rent"] += 1
            events.append({
                "date": d,
                "amount": cfg.rent_monthly,
                "category": "rent",
                "ref_id": f"RENT_{d.year}{d.month:02d}",
            })

        # Opex: 5th of month
        if d.day == 5:
            counter["opex"] += 1
            events.append({
                "date": d,
                "amount": cfg.opex_fixed_monthly,
                "category": "opex",
                "ref_id": f"OPEX_{d.year}{d.month:02d}",
            })

        # Tax advances: 10th of quarter months (Mar, Jun, Sep, Dec)
        if d.day == cfg.tax_advance_day and d.month in cfg.tax_advance_months:
            # Skip if S4 moved the Dec advance
            if params.outflow_spike and d.month == 12:
                pass   # S4 replaces Dec advance with outflow_spike extra
            else:
                counter["tax_advance"] += 1
                events.append({
                    "date": d,
                    "amount": cfg.tax_advance_quarterly,
                    "category": "tax_advance",
                    "ref_id": f"TAX_{d.year}Q{(d.month - 1) // 3 + 1}",
                })

        d += timedelta(days=1)

    # S4: extra tax advance moved to same week as the outflow spike
    if params.outflow_spike and params.outflow_spike.get("extra_tax_advance_date"):
        td = params.outflow_spike["extra_tax_advance_date"]
        events.append({
            "date": td,
            "amount": float(params.outflow_spike.get("extra_tax_advance_amount", 40_000)),
            "category": "tax_advance",
            "ref_id": f"TAX_S4_MOVED",
        })

    return events


# ── VAT cash flows ────────────────────────────────────────────────────────────

def _gen_vat(ar_invoices: list[dict], ap_invoices: list[dict],
             cfg: Cfg, sim_start: date, sim_end: date) -> list[dict]:
    """Net VAT payable per month, paid on the 15th of the following month."""
    ar_vat_by_month: dict[tuple, float] = defaultdict(float)
    ap_vat_by_month: dict[tuple, float] = defaultdict(float)

    for inv in ar_invoices:
        m = (inv["issue_date"].year, inv["issue_date"].month)
        ar_vat_by_month[m] += float(inv["vat"])

    for inv in ap_invoices:
        m = (inv["issue_date"].year, inv["issue_date"].month)
        ap_vat_by_month[m] += float(inv["vat"])

    events = []
    all_months = sorted(set(ar_vat_by_month) | set(ap_vat_by_month))
    for ym in all_months:
        net_vat = ar_vat_by_month[ym] - ap_vat_by_month[ym]
        if net_vat <= 0:
            continue
        y, m = ym
        pay_year, pay_month = (y + 1, 1) if m == 12 else (y, m + 1)
        pay_date = date(pay_year, pay_month, cfg.vat_return_day)
        if sim_start <= pay_date <= sim_end:
            events.append({
                "date": pay_date,
                "amount": round(net_vat, 2),
                "category": "vat_payment",
                "ref_id": f"VAT_{y}{m:02d}",
            })
    return events


# ── Opening balance solver ────────────────────────────────────────────────────

def _solve_opening_balance(
        all_events: list[tuple[date, float, str, str, str]],
        as_of_date: date,
        target: float) -> float:
    """Solve opening balance so that the CLOSING balance on the day BEFORE as_of = target.

    History flows are all flows on dates strictly before as_of_date.
    The daily balance is opening_balance + cumulative_flows.
    """
    history_flows = sum(amt for dt, amt, *_ in all_events if dt < as_of_date)
    return target - history_flows


# ── Balance computation ───────────────────────────────────────────────────────

def _compute_daily_balances(opening_balance: float,
                             all_events: list[tuple[date, float, str, str, str]],
                             sim_start: date, sim_end: date) -> dict[date, float]:
    flows_by_date: dict[date, float] = defaultdict(float)
    for dt, amt, *_ in all_events:
        if sim_start <= dt <= sim_end:
            flows_by_date[dt] += amt

    balances: dict[date, float] = {}
    balance = opening_balance
    d = sim_start
    while d <= sim_end:
        balance += flows_by_date.get(d, 0.0)
        balances[d] = balance
        d += timedelta(days=1)
    return balances


def _compute_weekly_balances(daily_balances: dict[date, float],
                              sim_start: date, sim_end: date) -> dict[date, float]:
    """Return end-of-Sunday balance, keyed by the Monday (week start)."""
    weekly: dict[date, float] = {}
    # sim_start is a Monday; iterate week by week
    monday = sim_start
    while monday <= sim_end:
        sunday = monday + timedelta(days=6)
        end = min(sunday, sim_end)
        # Balance at end of Sunday (or last day in range)
        d = end
        while d >= monday:
            if d in daily_balances:
                weekly[monday] = daily_balances[d]
                break
            d -= timedelta(days=1)
        else:
            weekly[monday] = 0.0
        monday += timedelta(weeks=1)
    return weekly


def _split_weekly_balances(dataset_id: str,
                            weekly: dict[date, float],
                            as_of: date) -> tuple[list[dict], list[dict]]:
    hist, future = [], []
    for week_start, bal in sorted(weekly.items()):
        row = {
            "dataset_id": dataset_id,
            "account_code": "ACC_MAIN",
            "date": week_start + timedelta(days=6),  # Sunday end-of-week
            "week_start": week_start,
            "closing_balance": round(bal, 2),
        }
        if week_start < as_of:
            hist.append(row)
        else:
            future.append(row)
    return hist, future


# ── Bank transactions ─────────────────────────────────────────────────────────

def _build_bank_transactions(dataset_id: str,
                              ar_receipts: list[dict],
                              ap_payments: list[dict],
                              recurring_events: list[dict],
                              vat_events: list[dict],
                              as_of: date) -> list[dict]:
    txns: list[dict] = []
    txn_counter = 0

    def add(dt: date, amount: float, category: str, ref_type: str, ref_id: str) -> None:
        nonlocal txn_counter
        if dt > as_of:
            return
        txn_counter += 1
        txns.append({
            "dataset_id": dataset_id,
            "txn_id": f"TXN_{dataset_id}_{txn_counter:06d}",
            "account_code": "ACC_MAIN",
            "date": dt,
            "amount": round(amount, 2),
            "category": category,
            "ref_type": ref_type,
            "ref_id": ref_id,
        })

    for r in ar_receipts:
        add(r["date"], r["amount"], "ar_receipt", "receipt", r["receipt_id"])
    for p in ap_payments:
        add(p["date"], -p["amount"], "ap_payment", "payment", p["payment_id"])
    for ev in recurring_events:
        if ev["date"] < as_of:
            add(ev["date"], -ev["amount"], ev["category"], "recurring", ev["ref_id"])
    for ev in vat_events:
        if ev["date"] < as_of:
            add(ev["date"], -ev["amount"], "vat_payment", "recurring", ev["ref_id"])

    return txns


# ── Month closes ──────────────────────────────────────────────────────────────

def _build_month_closes(dataset_id: str,
                         ar_invoices: list[dict],
                         ap_invoices: list[dict],
                         cfg: Cfg,
                         params: ScenarioParams,
                         sim_start: date,
                         sim_end: date) -> tuple[list[dict], list[dict]]:
    closes: list[dict] = []
    adjustments: list[dict] = []

    # Group AR by month
    ar_by_month: dict[tuple, list[dict]] = defaultdict(list)
    for inv in ar_invoices:
        ar_by_month[(inv["issue_date"].year, inv["issue_date"].month)].append(inv)

    ap_by_month: dict[tuple, list[dict]] = defaultdict(list)
    for inv in ap_invoices:
        ap_by_month[(inv["issue_date"].year, inv["issue_date"].month)].append(inv)

    # Generate closes for full calendar months only.
    # If sim_start is not the 1st, skip the partial first month.
    y, m = sim_start.year, sim_start.month
    if sim_start.day > 1:
        m += 1
        if m > 12:
            m = 1; y += 1
    end_ym = (sim_end.year, sim_end.month)

    while (y, m) <= end_ym:
        month_date = date(y, m, 1)
        month_end = date(y, m, _days_in_month(y, m))

        revenue = sum(float(i["amount_net"]) for i in ar_by_month[(y, m)])
        # Inventory-tagged AP invoices are balance sheet items (not P&L COGS) until goods are sold
        cogs_m  = sum(float(i["amount_net"]) for i in ap_by_month[(y, m)]
                      if not i.get("is_inventory"))
        opex_m  = (cfg.opex_fixed_monthly + cfg.rent_monthly + cfg.payroll_net_monthly
                   + cfg.payroll_social_monthly + cfg.depreciation_monthly)
        ebit    = revenue - cogs_m - opex_m
        tax     = max(0.0, ebit * cfg.corporate_tax_rate)
        profit  = ebit - tax

        # Close booking date
        if params.late_close:
            # S8: 15-20 days late
            close_delay = 15 + (((y * 12 + m) % 6))  # deterministic, varies 15-20
        else:
            close_delay = 5

        close_date = month_end + timedelta(days=close_delay)

        closes.append({
            "dataset_id": dataset_id,
            "month": month_date,
            "close_booked_on": close_date,
            "revenue_booked": round(revenue, 2),
            "cogs": round(cogs_m, 2),
            "opex": round(opex_m, 2),
            "profit": round(profit, 2),
        })

        # S8: September close adjustments
        if params.close_adjustments_sep and y == cfg.as_of_date.year and m == 9:
            for adj in params.close_adjustments_sep:
                adjustments.append({
                    "dataset_id": dataset_id,
                    "month": month_date,
                    "kind": adj["kind"],
                    "ref_id": f"ADJ_{y}{m:02d}_{adj['kind']}",
                    "amount": float(adj["amount"]),
                    "note": adj.get("note", ""),
                })

        if m == 12:
            y += 1
            m = 1
        else:
            m += 1

    return closes, adjustments


# ── Recurring config rows (for hm.recurring_outflows) ────────────────────────

def _build_recurring_config(dataset_id: str, cfg: Cfg) -> list[dict]:
    return [
        {"dataset_id": dataset_id, "kind": "payroll_net",
         "rule": {"day": "last_working"}, "amount": cfg.payroll_net_monthly},
        {"dataset_id": dataset_id, "kind": "payroll_social",
         "rule": {"day_of_month": 15}, "amount": cfg.payroll_social_monthly},
        {"dataset_id": dataset_id, "kind": "rent",
         "rule": {"day_of_month": 1}, "amount": cfg.rent_monthly},
        {"dataset_id": dataset_id, "kind": "opex",
         "rule": {"day_of_month": 5}, "amount": cfg.opex_fixed_monthly},
        {"dataset_id": dataset_id, "kind": "vat",
         "rule": {"day_of_month": cfg.vat_return_day, "following_month": True},
         "amount": 0},  # computed monthly
        {"dataset_id": dataset_id, "kind": "tax_advance",
         "rule": {"months": cfg.tax_advance_months, "day": cfg.tax_advance_day},
         "amount": cfg.tax_advance_quarterly},
    ]


# ── Scenario truth ────────────────────────────────────────────────────────────

def _build_truth(dataset_id: str, params: ScenarioParams,
                 customers: list[Customer],
                 ar_receipts: list[dict],
                 weekly_balances: dict[date, float],
                 cfg: Cfg) -> dict:
    truth: dict = {"dataset_id": dataset_id}

    if dataset_id == "S1_normal":
        truth["verdict"] = "no_shortfall"

    elif dataset_id == "S2_big_customer":
        bcd = params.big_customer_drift
        truth["target_customer"] = bcd.get("target_code", "unknown")
        truth["drift_start"] = str(bcd.get("drift_start", ""))
        if params.extraordinary_ap:
            truth["shortfall_trigger"] = "week_6_large_supplier_bill"

    elif dataset_id == "S3_sector_crisis":
        sc = params.sector_crisis
        truth["shock_start"] = str(sc.get("shock_start", ""))
        truth["nace_codes"] = sc.get("nace_codes", ["F41"])
        truth["excluded_top5"] = sorted(sc.get("excluded_top5", []))
        truth["affected_codes"] = sorted(sc.get("affected_codes", []))
        truth["bankrupt_codes"] = sorted(sc.get("bankrupt_codes", []))
        truth["sector_crisis_affected"] = sorted(sc.get("affected_codes", []))

    elif dataset_id == "S4_outflow_spike":
        sp = params.outflow_spike
        truth["spike_week"] = 7
        truth["components"] = {
            "extraordinary_supplier_bill": sp.get("amount_net", 0),
            "moved_tax_advance": sp.get("extra_tax_advance_amount", 0),
            "vat_payment": "oct_vat_due_nov_15",
        }

    elif dataset_id == "S5_seasonality":
        truth["seasonal_factors"] = "construction_leave_aug, year_end_dec"

    elif dataset_id == "S6_new_customer":
        nc = params.new_customer
        truth["new_customer_code"] = "CUST_NC1"
        truth["true_archetype"] = "slow"
        truth["invoice_1_due"] = str(nc.get("invoice_1_due", ""))
        truth["invoice_2_due"] = str(nc.get("invoice_2_due", ""))

    elif dataset_id == "S7_partial_payments":
        truth["partial_payment_note"] = "3 customers split invoices"

    elif dataset_id == "S8_month_end_close":
        truth["late_close"] = True
        truth["adjustments"] = "sep_close_60k_cancel_25k_credit"

    return truth


# ── Apply scenario to customers ───────────────────────────────────────────────

def _apply_scenario_to_customers(customers: list[Customer],
                                  params: ScenarioParams,
                                  cfg: Cfg,
                                  rng: np.random.Generator) -> list[Customer]:
    """Apply scenario-specific modifications to the customer list."""
    # S2: identify top-3 customer and set as target
    if params.big_customer_drift:
        by_rev = sorted(customers, key=lambda c: c.annual_revenue, reverse=True)
        top3 = by_rev[:3]
        # Pick the one with most invoices due in weeks 4-6 (largest revenue wins)
        target = top3[0]
        params.big_customer_drift["target_code"] = target.code

    # S3: affected cohort = ALL F41+F43 except top-5 globally by revenue
    if params.sector_crisis:
        nace_codes = params.sector_crisis.get("nace_codes", ["F41"])
        excluded_top5 = params.sector_crisis.get("excluded_top5", set())
        construction = [c for c in customers if c.nace in nace_codes]
        affected = {c.code for c in construction if c.code not in excluded_top5}
        params.sector_crisis["affected_codes"] = affected

        # Bankrupt: n smallest affected construction customers (by revenue)
        n_bankrupt = params.sector_crisis.get("n_bankrupt", 0)
        if n_bankrupt > 0:
            small_aff = sorted(
                [c for c in construction if c.code in affected and c.size_band == "small"],
                key=lambda c: c.annual_revenue
            )
            bankrupt_codes = {c.code for c in small_aff[:n_bankrupt]}
            params.sector_crisis["bankrupt_codes"] = bankrupt_codes

    # S6: add new customer
    if params.new_customer:
        nc = params.new_customer
        stress = 1.0  # new customer, no stress history
        customers = list(customers) + [Customer(
            code="CUST_NC1",
            nace=nc["nace"],
            segment="specialised_installers",
            size_band="small",
            payment_terms_days=45,
            archetype=nc["archetype"],
            archetype_mean=20.0,
            archetype_sd=10.0,
            annual_revenue=150_000.0,
            invoice_freq=2,
            onboarded_on=nc["onboarded_on"],
            never_chronic_late=False,
            batch_payment_month_end=False,
            stress_index=stress,
            display_name="Atelier NC1 S.à r.l.",
            iban="LU00001000000000000",
        )]

    return customers


# ── Date helpers ──────────────────────────────────────────────────────────────

def _next_working_day(d: date) -> date:
    while d.weekday() >= 5:  # 5=Sat, 6=Sun
        d += timedelta(days=1)
    return d


def _last_working_day(year: int, month: int) -> date:
    import calendar
    last = date(year, month, calendar.monthrange(year, month)[1])
    while last.weekday() >= 5:
        last -= timedelta(days=1)
    return last


def _prev_month(d: date) -> date:
    if d.month == 1:
        return date(d.year - 1, 12, 1)
    return date(d.year, d.month - 1, 1)


def _next_month_end(d: date) -> date:
    """Return the last day of the month containing d."""
    import calendar
    last = calendar.monthrange(d.year, d.month)[1]
    return date(d.year, d.month, last)


def _days_in_month(year: int, month: int) -> int:
    import calendar
    return calendar.monthrange(year, month)[1]
