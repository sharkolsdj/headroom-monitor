"""Build the customer and supplier portfolios for a dataset."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

import numpy as np

from ._cfg import Cfg
from ._names import make_display_name, make_iban


@dataclass
class Customer:
    code: str
    nace: str
    segment: str
    size_band: str          # "large" / "medium" / "small"
    payment_terms_days: int
    archetype: str
    archetype_mean: float
    archetype_sd: float
    annual_revenue: float
    invoice_freq: int       # invoices per year
    onboarded_on: date | None
    never_chronic_late: bool
    batch_payment_month_end: bool
    stress_index: float
    display_name: str
    iban: str


@dataclass
class Supplier:
    code: str
    tier: str
    payment_terms_days: int
    annual_purchases: float
    invoice_freq: int       # AP invoices per year received from this supplier
    display_name: str
    iban: str


# Revenue-band thresholds (percentile-based)
_LARGE_CUTOFF  = 0.80   # top 20% by revenue → weekly invoicing
_MEDIUM_CUTOFF = 0.40   # 40–80th percentile → biweekly


def build_customers(cfg: Cfg, rng: np.random.Generator,
                    history_start: date,
                    stress_map: dict[str, float] | None = None) -> list[Customer]:
    """Generate cfg.customer_count customers with lognormal revenue distribution."""
    n = cfg.customer_count
    stress_map = stress_map or {}

    # Assign segment counts proportionally
    segment_counts = _assign_segment_counts(cfg.segments, n)

    # Build per-segment customer lists
    customers: list[Customer] = []
    cust_idx = 1

    for seg, count in zip(cfg.segments, segment_counts):
        nace = str(seg["nace"])
        terms = int(seg["payment_terms_days"])
        never_cl = bool(seg.get("never_chronic_late", False))
        batch_me = seg.get("batch_payment") == "month_end"

        # Get stress index for this segment
        stress = stress_map.get(nace, 1.0)

        # Revenue distribution: lognormal tuned to hit top-20 share
        # (tuned globally, then each segment's share is proportional)
        seg_revenues = None  # filled after global tuning below

        for i in range(count):
            code = f"CUST_{cust_idx:03d}"
            arch = _pick_archetype(cfg, rng, never_chronic_late=never_cl)
            customers.append(Customer(
                code=code,
                nace=nace,
                segment=seg["code"],
                size_band="",          # set after revenue assignment
                payment_terms_days=terms,
                archetype=arch["name"],
                archetype_mean=float(arch["mean_delay_days"]),
                archetype_sd=float(arch["sd_days"]),
                annual_revenue=0.0,    # set below
                invoice_freq=0,        # set below
                onboarded_on=history_start,
                never_chronic_late=never_cl,
                batch_payment_month_end=batch_me,
                stress_index=stress,
                display_name=make_display_name(rng, "customer"),
                iban=make_iban(rng),
            ))
            cust_idx += 1

    # Tune lognormal sigma so top-20 share lands in [57%, 63%] and largest in [6%, 9%]
    revenues = _tune_revenues(cfg, rng, n)
    # Sort customers by revenue descending and assign
    order = np.argsort(revenues)[::-1]
    for rank, cidx in enumerate(order):
        customers[cidx].annual_revenue = float(revenues[cidx])

    total_rev = sum(c.annual_revenue for c in customers)
    # Scale to exact target revenue
    scale = cfg.net_revenue_annual / total_rev
    for c in customers:
        c.annual_revenue *= scale

    # Assign size bands and invoice frequencies
    sorted_by_rev = sorted(customers, key=lambda c: c.annual_revenue, reverse=True)
    top20_cutoff  = int(math.ceil(n * 0.20))   # top 20% → large
    mid60_cutoff  = int(math.ceil(n * 0.60))   # 20–60% → medium

    for rank, c in enumerate(sorted_by_rev):
        if rank < top20_cutoff:
            c.size_band = "large"
            c.invoice_freq = 52     # weekly
        elif rank < mid60_cutoff:
            c.size_band = "medium"
            c.invoice_freq = 26     # biweekly
        else:
            c.size_band = "small"
            c.invoice_freq = 12     # monthly

    return customers


def build_suppliers(cfg: Cfg, rng: np.random.Generator) -> list[Supplier]:
    suppliers: list[Supplier] = []
    for tier_def in cfg.supplier_tiers:
        if tier_def["tier"] == "major":
            annual = cfg.cogs_annual * float(tier_def["revenue_share"])
            suppliers.append(Supplier(
                code=tier_def["code"],
                tier="major",
                payment_terms_days=int(tier_def["payment_terms_days"]),
                annual_purchases=annual,
                invoice_freq=12,    # monthly invoice from major supplier
                display_name=make_display_name(rng, "supplier"),
                iban=make_iban(rng),
            ))
        elif tier_def["tier"] == "mid":
            mid_codes = tier_def.get("codes", [])
            total_share = float(tier_def["revenue_share_total"])
            per_share = total_share / len(mid_codes)
            for code in mid_codes:
                annual = cfg.cogs_annual * per_share
                suppliers.append(Supplier(
                    code=code,
                    tier="mid",
                    payment_terms_days=int(tier_def["payment_terms_days"]),
                    annual_purchases=annual,
                    invoice_freq=12,
                    display_name=make_display_name(rng, "supplier"),
                    iban=make_iban(rng),
                ))
        elif tier_def["tier"] == "small":
            n_small = int(tier_def["count"])
            total_share = float(tier_def["revenue_share_total"])
            per_share = total_share / n_small
            for i in range(n_small):
                code = f"SUPP_{6 + i:02d}"
                annual = cfg.cogs_annual * per_share
                suppliers.append(Supplier(
                    code=code,
                    tier="small",
                    payment_terms_days=int(tier_def["payment_terms_days"]),
                    annual_purchases=annual,
                    invoice_freq=12,
                    display_name=make_display_name(rng, "supplier"),
                    iban=make_iban(rng),
                ))

    return suppliers


# ── helpers ───────────────────────────────────────────────────────────────────

def _assign_segment_counts(segments: list[dict], total: int) -> list[int]:
    """Distribute total customers across segments; adjust last to hit total exactly."""
    counts = []
    assigned = 0
    for i, seg in enumerate(segments):
        if i == len(segments) - 1:
            counts.append(total - assigned)
        else:
            c = round(total * float(seg["share"]))
            counts.append(c)
            assigned += c
    return counts


def _pick_archetype(cfg: Cfg, rng: np.random.Generator,
                    never_chronic_late: bool = False) -> dict:
    archetypes = cfg.archetypes
    if never_chronic_late:
        archetypes = [a for a in archetypes if a["name"] != "chronic_late"]
    shares = [float(a["share"]) for a in archetypes]
    total = sum(shares)
    cum = 0.0
    r = float(rng.random())
    for arch, share in zip(archetypes, shares):
        cum += share / total
        if r < cum:
            return arch
    return archetypes[-1]


def _tune_revenues(cfg: Cfg, rng: np.random.Generator, n: int,
                   max_iter: int = 50) -> np.ndarray:
    """Binary-search lognormal sigma so top-20 share is in [57%, 63%]."""
    lo, hi = 1.0, 3.0
    best = None

    for _ in range(max_iter):
        sigma = (lo + hi) / 2.0
        # Use a fresh sub-generator (same state for reproducibility)
        rev = rng.lognormal(mean=0.0, sigma=sigma, size=n)
        rev.sort()
        rev = rev[::-1]   # descending
        total = rev.sum()
        if total == 0:
            continue
        top20 = rev[:20].sum() / total
        largest = rev[0] / total

        fits_top20 = cfg.top20_share_min <= top20 <= cfg.top20_share_max
        fits_largest = cfg.largest_share_min <= largest <= cfg.largest_share_max

        if fits_top20 and fits_largest:
            best = rev
            break
        elif top20 < cfg.top20_share_min:
            lo = sigma   # need more inequality
        else:
            hi = sigma   # too unequal

    if best is None:
        # Use the last sigma tried
        best = rng.lognormal(mean=0.0, sigma=(lo + hi) / 2.0, size=n)
    # Shuffle (to break the sort order before segment assignment)
    rng.shuffle(best)
    return best
