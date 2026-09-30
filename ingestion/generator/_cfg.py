"""Load company.yaml and compute derived simulation parameters."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).parent.parent.parent
COMPANY_YAML = ROOT / "config" / "company.yaml"


@dataclass
class Cfg:
    seed: int
    net_revenue_annual: float
    gross_margin: float
    cogs_annual: float
    payroll_net_monthly: float
    payroll_social_monthly: float
    rent_monthly: float
    opex_fixed_monthly: float
    vat_rate: float
    vat_return_day: int
    tax_advance_quarterly: float
    tax_advance_months: list[int]   # [3, 6, 9, 12]
    tax_advance_day: int            # 10

    as_of_date: date
    history_start: date
    history_end: date
    forecast_weeks: int
    target_balance_as_of: float

    safety_weeks: int

    customer_count: int
    segments: list[dict]
    top20_share_min: float
    top20_share_max: float
    largest_share_min: float
    largest_share_max: float
    invoices_per_year_total: int
    invoice_noise: float
    archetypes: list[dict]
    delay_floor_days: int
    sector_stress_beta: float
    seasonality: dict

    supplier_count: int
    supplier_tiers: list[dict]
    early_payment_discount: float
    early_payment_enabled: bool

    depreciation_monthly: float
    corporate_tax_rate: float

    credit_facility_code: str
    credit_facility_limit: float
    credit_facility_rate_ref: str

    @property
    def forecast_end(self) -> date:
        from datetime import timedelta
        return self.as_of_date + timedelta(weeks=self.forecast_weeks) - timedelta(days=1)

    @property
    def weekly_fixed_costs(self) -> float:
        monthly = (self.payroll_net_monthly + self.payroll_social_monthly
                   + self.rent_monthly + self.opex_fixed_monthly)
        return monthly * 12 / 52

    @property
    def safety_threshold(self) -> float:
        return self.safety_weeks * self.weekly_fixed_costs


def load(overlay: dict | None = None) -> Cfg:
    with COMPANY_YAML.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if overlay:
        _deep_merge(data, overlay)

    fin = data.get("financials", {})
    tl  = data.get("timeline", {})
    saf = data.get("safety", {})
    cust = data.get("customers", {})
    szdist = cust.get("size_distribution", {})
    sup = data.get("suppliers", {})
    cf  = data.get("credit_facility", {})
    seas = cust.get("seasonality", {})

    tax_dates = fin.get("tax_advance_dates", [])

    return Cfg(
        seed=data.get("seed", 42),
        net_revenue_annual=float(fin.get("net_revenue_annual", 25_000_000)),
        gross_margin=float(fin.get("gross_margin", 0.30)),
        cogs_annual=float(fin.get("cogs_annual", 17_500_000)),
        payroll_net_monthly=float(fin.get("payroll_net_monthly", 290_000)),
        payroll_social_monthly=float(fin.get("payroll_social_monthly", 177_000)),
        rent_monthly=float(fin.get("rent_monthly", 35_000)),
        opex_fixed_monthly=float(fin.get("opex_fixed_monthly", 50_000)),
        vat_rate=float(fin.get("vat_rate", 0.17)),
        vat_return_day=int(fin.get("vat_return_day", 15)),
        tax_advance_quarterly=float(fin.get("tax_advance_quarterly", 40_000)),
        tax_advance_months=[int(d["month"]) for d in tax_dates],
        tax_advance_day=int(tax_dates[0]["day"]) if tax_dates else 10,
        as_of_date=_parse_date(tl.get("as_of_date", "2026-09-28")),
        history_start=_parse_date(tl.get("history_start", "2025-09-29")),
        history_end=_parse_date(tl.get("history_end", "2026-09-27")),
        forecast_weeks=int(tl.get("forecast_weeks", 13)),
        target_balance_as_of=float(tl.get("target_balance_as_of", 1_200_000)),
        safety_weeks=int(saf.get("safety_weeks", 4)),
        customer_count=int(cust.get("count", 237)),
        segments=cust.get("segments", []),
        top20_share_min=float(szdist.get("top20_share_min", 0.57)),
        top20_share_max=float(szdist.get("top20_share_max", 0.63)),
        largest_share_min=float(szdist.get("largest_share_min", 0.06)),
        largest_share_max=float(szdist.get("largest_share_max", 0.09)),
        invoices_per_year_total=int(szdist.get("invoices_per_year_total", 2000)),
        invoice_noise=float(szdist.get("invoice_noise", 0.25)),
        archetypes=cust.get("payment_archetypes", []),
        delay_floor_days=int(cust.get("delay_floor_days", -10)),
        sector_stress_beta=float(cust.get("sector_stress_beta", 0.5)),
        seasonality=seas,
        supplier_count=int(sup.get("count", 25)),
        supplier_tiers=sup.get("tiers", []),
        early_payment_discount=float(sup.get("early_payment_discount", 0.02)),
        early_payment_enabled=bool(sup.get("early_payment_enabled", False)),
        depreciation_monthly=float(fin.get("depreciation_annual", 250_000)) / 12.0,
        corporate_tax_rate=float(fin.get("corporate_tax_rate", 0.21)),
        credit_facility_code=str(cf.get("code", "FAC_REVOLVING")),
        credit_facility_limit=float(cf.get("limit_amount", 1_000_000)),
        credit_facility_rate_ref=str(cf.get("rate_ref", "euribor_3m")),
    )


def _parse_date(s: str | date) -> date:
    if isinstance(s, date):
        return s
    return date.fromisoformat(str(s))


def _deep_merge(base: dict, overlay: dict) -> None:
    for k, v in overlay.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
