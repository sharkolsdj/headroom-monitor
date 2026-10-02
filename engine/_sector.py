"""Sector trend detection and STATEC bankruptcy stress index (Phase 3)."""
from __future__ import annotations

import csv
import math
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

_STATEC_CSV = (
    Path(__file__).parent.parent
    / "data" / "public" / "raw"
    / "statec_bankruptcies_lustat_2016_2025.csv"
)

# Pre-registered parameters (docs/PHASE3_PREREG.md)
_SLOWING_FRAC = 0.25
_SLOWING_MIN_CUST = 8
_SLOWING_DELAY_DIFF = 7.0    # days: recent mean must exceed 9-month prior mean
_RECENT_DAYS = 90
_PRIOR_DAYS = 365            # look-back start
_STATEC_BASE_YEARS = (2019, 2020, 2021, 2022, 2023)
_STATEC_CURRENT_YEAR = 2024


def _nace_section(code: str) -> str:
    """'F41' → 'F'."""
    return "".join(c for c in code if c.isalpha()).upper()


def load_statec_stress(path: Path = _STATEC_CSV) -> dict[str, float]:
    """
    Return {nace_activity: stress_index} where stress_index = count_2024 / mean(2019-2023).
    Exact activity codes from the CSV (e.g. 'F', 'L', 'G45').
    Falls back to 1.0 when base data is absent.
    """
    counts: dict[str, dict[int, float]] = defaultdict(dict)
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        next(reader)
        for row in reader:
            if len(row) < 19:
                continue
            activity = row[12].strip()
            tp = row[16].strip()
            obs = row[18].strip()
            if not tp.isdigit() or not obs.isdigit():
                continue
            counts[activity][int(tp)] = float(obs)

    result: dict[str, float] = {}
    for activity, year_counts in counts.items():
        base = [year_counts[y] for y in _STATEC_BASE_YEARS if y in year_counts]
        current = year_counts.get(_STATEC_CURRENT_YEAR)
        if len(base) >= 3 and current is not None:
            base_avg = sum(base) / len(base)
            result[activity] = current / base_avg if base_avg > 0 else 1.0
        else:
            result[activity] = 1.0
    return result


def statec_stress_for_segment(seg_code: str, stress_table: dict[str, float]) -> float:
    """Resolve a segment code (e.g. 'F41') to a stress index.  Falls back to 1.0."""
    if seg_code in stress_table:
        return stress_table[seg_code]
    section = _nace_section(seg_code)
    return stress_table.get(section, 1.0)


def detect_sector_trends(
    cust_worsening: dict[str, bool],
    cust_recent_mean: dict[str, float],
    cust_longrun_mean: dict[str, float],
    cust_seg: dict[str, str],
    seg_pool_entries: dict[str, list[tuple[float, date]]],
    as_of: date,
    statec_stress: dict[str, float],
) -> tuple[dict[str, bool], dict[str, float], list[dict]]:
    """
    Detect which segments are slowing, compute per-segment shift, and build alerts.

    Returns (sector_slowing, sector_shift, sector_alerts).
        sector_slowing: {seg_code: bool}
        sector_shift:   {seg_code: extra_delay_days}  — applied to low-evidence customers
        sector_alerts:  list of alert dicts for forecast.json
    """
    recent_cutoff = as_of - timedelta(days=_RECENT_DAYS)
    prior_start = as_of - timedelta(days=_PRIOR_DAYS)

    seg_customers: dict[str, list[str]] = defaultdict(list)
    for cust, seg in cust_seg.items():
        seg_customers[seg].append(cust)

    sector_slowing: dict[str, bool] = {}
    sector_shift: dict[str, float] = {}
    sector_alerts: list[dict] = []

    for seg, customers in seg_customers.items():
        n_active = len(customers)
        n_worsening = sum(1 for c in customers if cust_worsening.get(c, False))

        slowing_by_frac = (
            n_active >= _SLOWING_MIN_CUST
            and n_worsening / n_active >= _SLOWING_FRAC
        )

        entries = seg_pool_entries.get(seg, [])
        recent_d = [d for d, dt in entries if dt >= recent_cutoff]
        prior_d  = [d for d, dt in entries if prior_start <= dt < recent_cutoff]

        slowing_by_delay = False
        if recent_d and prior_d:
            recent_mean_seg = sum(recent_d) / len(recent_d)
            prior_mean_seg  = sum(prior_d)  / len(prior_d)
            slowing_by_delay = (recent_mean_seg - prior_mean_seg) >= _SLOWING_DELAY_DIFF

        is_slowing = slowing_by_frac or slowing_by_delay
        sector_slowing[seg] = is_slowing

        if is_slowing:
            stress = statec_stress_for_segment(seg, statec_stress)
            # Sector shift = median extra delay among worsening customers × STATEC amplifier
            worsening_custs = [c for c in customers if cust_worsening.get(c, False)]
            extras = [
                cust_recent_mean.get(c, 0.0) - cust_longrun_mean.get(c, 0.0)
                for c in worsening_custs
                if (cust_recent_mean.get(c, 0.0) - cust_longrun_mean.get(c, 0.0)) > 0
            ]
            if extras:
                extras_sorted = sorted(extras)
                median_extra = extras_sorted[len(extras_sorted) // 2]
            else:
                median_extra = 0.0
            amplifier = 1.0 + 0.5 * (stress - 1.0)
            shift = max(0.0, median_extra * amplifier)
            sector_shift[seg] = shift

            # STATEC pct change vs 5-yr avg
            stress_pct = round((stress - 1.0) * 100, 1)
            sector_alerts.append({
                "segment": seg,
                "n_worsening": n_worsening,
                "n_customers": n_active,
                "reason": "fraction" if slowing_by_frac else "delay",
                "shift_days": round(shift, 1),
                "statec_stress_pct": stress_pct,
            })
        else:
            sector_shift[seg] = 0.0

    return sector_slowing, sector_shift, sector_alerts
