"""
Fetch and normalise public reference data into hm.public_series.

Sources
-------
1. ECB SDMX REST API — deposit facility rate and 3-month Euribor.
2. LUSTAT SDMX (data.public.lu) — STATEC bankruptcies by NACE section.
   Falls back to data/public/manual/statec_bankruptcies.csv when the API
   cannot be reached or returns no usable data.

Run:
    python -m ingestion.public_data [--dry-run]

The script prints which rows were inserted/skipped and which CSV values still
need to be filled in by hand.
"""
from __future__ import annotations

import argparse
import csv
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

import sqlalchemy as sa
from sqlalchemy import text

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
from config import settings  # noqa: E402

try:
    import requests as _requests
    _HAS_REQUESTS = True
except ImportError:
    _HAS_REQUESTS = False

MANUAL_BANKRUPTCIES = ROOT / "data" / "public" / "manual" / "statec_bankruptcies.csv"
RAW_DIR = ROOT / "data" / "public" / "raw"

# ECB SDMX REST base
ECB_BASE = "https://data-api.ecb.europa.eu/service/data"

# ECB series keys (FM = Financial Markets dataset)
# Deposit facility rate — business-day level (percent p.a.)
# Key confirmed from data-api.ecb.europa.eu: FM.B.U2.EUR.4F.KR.DFR.LEV
ECB_DEPOSIT_KEY = "FM/B.U2.EUR.4F.KR.DFR.LEV"
# 3-month Euribor — monthly historical average (percent p.a., optional)
# Key confirmed: FM.M.U2.EUR.RT.MM.EURIBOR3MD_.HSTA
ECB_EURIBOR3M_KEY = "FM/M.U2.EUR.RT.MM.EURIBOR3MD_.HSTA"

ECB_SERIES = [
    (ECB_DEPOSIT_KEY, "ecb_deposit_rate", "ECB",
     "https://data-api.ecb.europa.eu/service/data/FM",
     "percent_annual"),
    (ECB_EURIBOR3M_KEY, "euribor_3m", "ECB",
     "https://data-api.ecb.europa.eu/service/data/FM",
     "percent_annual"),
]


class Row(NamedTuple):
    source: str
    series_id: str
    period: str
    value: float
    unit: str | None
    source_url: str | None


def _get(url: str, timeout: int = 15) -> "requests.Response | None":  # type: ignore[name-defined]
    if not _HAS_REQUESTS:
        warnings.warn("requests library not installed; skipping live API fetch")
        return None
    import requests
    try:
        r = requests.get(url, timeout=timeout,
                         headers={"Accept": "text/csv,application/csv,*/*"})
        r.raise_for_status()
        return r
    except Exception as exc:
        warnings.warn(f"HTTP fetch failed for {url}: {exc}")
        return None


def _fetch_ecb_series(key: str, series_id: str, source: str,
                      source_url: str, unit: str) -> list[Row]:
    url = f"{ECB_BASE}/{key}?format=csvdata&detail=dataonly"
    resp = _get(url)
    if resp is None:
        return []

    # Save raw to disk
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    safe = series_id.replace("/", "_")
    (RAW_DIR / f"{safe}.csv").write_text(resp.text, encoding="utf-8")

    rows: list[Row] = []
    try:
        lines = resp.text.splitlines()
        # ECB csvdata: first line is header, then data lines
        # Columns vary; find TIME_PERIOD and OBS_VALUE
        reader = csv.DictReader(lines)
        for record in reader:
            period = record.get("TIME_PERIOD") or record.get("time_period")
            obs = record.get("OBS_VALUE") or record.get("obs_value")
            if period is None or obs is None:
                continue
            try:
                rows.append(Row(source, series_id, period, float(obs), unit, source_url))
            except ValueError:
                continue
    except Exception as exc:
        warnings.warn(f"Failed to parse ECB response for {series_id}: {exc}")
    return rows


def _load_statec_from_api() -> list[Row]:
    """Try the LUSTAT / data.public.lu SDMX endpoint for bankruptcy counts."""
    # data.public.lu does not expose a stable machine-readable SDMX endpoint for
    # the "Démographie des entreprises" series as of 2026-09.
    # This function is a placeholder; it immediately returns [] so the manual
    # fallback is used.
    return []


def _load_statec_manual() -> tuple[list[Row], list[str]]:
    """Load STATEC bankruptcies from the hand-curated CSV.

    Returns (rows, fill_in_warnings) where fill_in_warnings lists every row
    whose value is still FILL_IN.
    """
    rows: list[Row] = []
    warnings_out: list[str] = []

    if not MANUAL_BANKRUPTCIES.exists():
        warnings.warn(f"Manual CSV not found: {MANUAL_BANKRUPTCIES}")
        return rows, warnings_out

    with MANUAL_BANKRUPTCIES.open(newline="", encoding="utf-8") as fh:
        for record in csv.DictReader(fh):
            nace = record["nace_section"].strip()
            year = record["year"].strip()
            raw_val = record["bankruptcies"].strip()
            url = record.get("source_url", "").strip() or None

            if raw_val == "FILL_IN":
                warnings_out.append(
                    f"  FILL_IN: nace_section={nace}, year={year}"
                    f"  -> look up at {url}"
                )
                continue

            try:
                rows.append(Row(
                    source="STATEC",
                    series_id=f"bankruptcies_{nace}",
                    period=year,
                    value=float(raw_val),
                    unit="count",
                    source_url=url,
                ))
            except ValueError:
                warnings.warn(f"Unexpected value '{raw_val}' in {MANUAL_BANKRUPTCIES}")

    return rows, warnings_out


def _compute_stress_indices(rows: list[Row]) -> list[Row]:
    """Compute stress index per NACE section from bankruptcy rows.

    stress_index = bankruptcies_latest_year / avg(bankruptcies_previous_5_years)

    Only sections with at least 2 years of data are included (need a latest year
    plus at least one prior year; 1.0 is the fallback used by the generator).
    """
    from collections import defaultdict

    by_section: dict[str, dict[int, float]] = defaultdict(dict)
    for r in rows:
        if not r.series_id.startswith("bankruptcies_"):
            continue
        section = r.series_id[len("bankruptcies_"):]
        try:
            by_section[section][int(r.period)] = r.value
        except ValueError:
            continue

    stress_rows: list[Row] = []
    for section, year_vals in by_section.items():
        if not year_vals:
            continue
        latest_year = max(year_vals)
        prev_years = sorted(y for y in year_vals if y < latest_year)[-5:]
        if not prev_years:
            continue
        avg_prev = sum(year_vals[y] for y in prev_years) / len(prev_years)
        if avg_prev == 0:
            continue
        stress = year_vals[latest_year] / avg_prev

        stress_rows.append(Row(
            source="derived",
            series_id=f"stress_index_{section}",
            period=str(latest_year),
            value=round(stress, 6),
            unit="ratio",
            source_url=None,
        ))

    return stress_rows


def _upsert_rows(engine: sa.Engine, rows: list[Row], dry_run: bool) -> int:
    """Insert rows; skip duplicates (unique on source, series_id, period).
    Returns number of rows inserted.
    """
    if not rows or dry_run:
        return 0

    now = datetime.now(timezone.utc)
    inserted = 0
    with engine.begin() as conn:
        for r in rows:
            result = conn.execute(text("""
                INSERT INTO hm.public_series
                    (source, series_id, period, value, unit, fetched_at, source_url)
                VALUES (:src, :sid, :per, :val, :unit, :fat, :url)
                ON CONFLICT (source, series_id, period) DO NOTHING
            """), {
                "src": r.source, "sid": r.series_id, "per": r.period,
                "val": r.value, "unit": r.unit, "fat": now, "url": r.source_url,
            })
            inserted += result.rowcount
    return inserted


def run(dry_run: bool = False, verbose: bool = True) -> dict:
    """Fetch all public series, upsert into DB, return summary dict."""
    all_rows: list[Row] = []

    # 1. ECB rates
    for ecb_key, sid, src, url, unit in ECB_SERIES:
        ecb_rows = _fetch_ecb_series(ecb_key, sid, src, url, unit)
        if verbose:
            label = "optional " if sid == "euribor_3m" else ""
            status = f"{len(ecb_rows)} rows" if ecb_rows else "unreachable — skipped"
            print(f"  ECB {label}{sid}: {status}")
        all_rows.extend(ecb_rows)

    # 2. STATEC bankruptcies — try API, fall back to manual CSV
    statec_rows = _load_statec_from_api()
    fill_in_warnings: list[str] = []
    if not statec_rows:
        statec_rows, fill_in_warnings = _load_statec_manual()
        if verbose:
            source_label = "manual CSV fallback"
            print(f"  STATEC bankruptcies: {source_label}, {len(statec_rows)} rows loaded")
    else:
        if verbose:
            print(f"  STATEC bankruptcies: live API, {len(statec_rows)} rows")
    all_rows.extend(statec_rows)

    # 3. Derived: sector stress indices
    stress_rows = _compute_stress_indices(all_rows)
    if verbose:
        for sr in stress_rows:
            print(f"  stress_index_{sr.series_id.split('_')[-1]}: "
                  f"{sr.value:.4f} ({sr.period})")
    all_rows.extend(stress_rows)

    # 4. Persist
    engine = _owner_engine()
    inserted = _upsert_rows(engine, all_rows, dry_run)
    if verbose:
        action = "would insert" if dry_run else "inserted"
        print(f"  {action} {inserted} new rows into hm.public_series "
              f"(total fetched: {len(all_rows)})")

    # 5. Warn about manual fill-ins
    if fill_in_warnings:
        print("\n  Values still needed in data/public/manual/statec_bankruptcies.csv:")
        for w in fill_in_warnings:
            print(w)

    return {
        "total_rows": len(all_rows),
        "inserted": inserted,
        "stress_indices": {r.series_id: float(r.value) for r in stress_rows},
        "fill_in_count": len(fill_in_warnings),
    }


def _owner_engine() -> sa.Engine:
    return sa.create_engine(settings.postgres_dsn, pool_pre_ping=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch public reference data")
    parser.add_argument("--dry-run", action="store_true",
                        help="Parse and print without writing to DB")
    args = parser.parse_args()
    run(dry_run=args.dry_run, verbose=True)
