"""
Fetch and normalise public reference data into hm.public_series.

Sources
-------
1. ECB SDMX REST API — deposit facility rate and 3-month Euribor.
2. LUSTAT/STATEC — bankruptcies by NACE section, 2016-2025.
   Attempts the LUSTAT SDMX REST API (LU1:DSD_DEMO_ENT_2@DF_D1312) first.
   Falls back to data/public/raw/statec_bankruptcies_lustat_2016_2025.csv
   when the API is unavailable (the server returns the web interface for all
   SDMX REST paths).

Run:
    python -m ingestion.public_data [--dry-run]

Segment stress-index mapping (for the generator, Phase 1C):
    F41 / F43  -> stress_index_F        (Construction)
    L68        -> stress_index_L        (Real estate activities)
    G47        -> stress_index_G47      (Retail trade)
    G46.73/74  -> stress_index_G46      (Wholesale trade, our sector)
    O84        -> stress_index_O = 1.0  (public admin excluded from STATEC)
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

# ── Paths ──────────────────────────────────────────────────────────────────────
LUSTAT_RAW_CSV = (
    ROOT / "data" / "public" / "raw" / "statec_bankruptcies_lustat_2016_2025.csv"
)
RAW_DIR = ROOT / "data" / "public" / "raw"

# ── Source metadata ────────────────────────────────────────────────────────────
LUSTAT_SOURCE_URL = (
    "https://lustat.statec.lu/vis?df[ds]=ds-release"
    "&df[id]=DSD_DEMO_ENT_2%40DF_D1312&df[ag]=LU1"
    "&vw=tb&dq=..A...&pd=2016%2C2025&to[TIME_PERIOD]=false&lc=en&pg=0"
)
LUSTAT_DATAFLOW = "LU1:DSD_DEMO_ENT_2@DF_D1312"
LUSTAT_SDMX_KEY = "..A..."

# SDMX REST candidates for LUSTAT; tried in order, first 200+CSV response wins.
# As of 2026-09, lustat.statec.lu returns the web interface for all these paths,
# so the CSV fallback is always used. Kept here for future re-enablement.
LUSTAT_SDMX_CANDIDATES: list[str] = [
    f"https://lustat.statec.lu/service/data/{LUSTAT_DATAFLOW}/{LUSTAT_SDMX_KEY}"
    "?format=csvdata&startPeriod=2016",
    f"https://lustat.statec.lu/sdmxapi/rest/data/{LUSTAT_DATAFLOW}/{LUSTAT_SDMX_KEY}"
    "?format=csvdata&startPeriod=2016",
]

# ── ECB series ─────────────────────────────────────────────────────────────────
ECB_BASE = "https://data-api.ecb.europa.eu/service/data"
ECB_SERIES = [
    # (sdmx_key, series_id, source, source_url, unit)
    ("FM/B.U2.EUR.4F.KR.DFR.LEV",
     "ecb_deposit_rate", "ECB",
     "https://data-api.ecb.europa.eu/service/data/FM",
     "percent_annual"),
    ("FM/M.U2.EUR.RT.MM.EURIBOR3MD_.HSTA",
     "euribor_3m", "ECB",
     "https://data-api.ecb.europa.eu/service/data/FM",
     "percent_annual"),
]

# ── Stress index: sector stress = 2025 / mean(2020-2024) ──────────────────────
# Public entities (O84) are excluded from STATEC; fixed at 1.0.
STRESS_BASE_YEARS = list(range(2020, 2025))
STRESS_LATEST_YEAR = 2025
FIXED_STRESS_INDICES: dict[str, float] = {"O": 1.0}

# Segment → NACE section mapping (for generator reference)
SEGMENT_NACE_MAP: dict[str, str] = {
    "F41": "F",    # General contractors
    "F43": "F",    # Specialised installers (plumbing, electrical, HVAC)
    "L68": "L",    # Property developers / renovation
    "G47": "G47",  # Retail / DIY
    "G46.73": "G46",  # Wholesale building materials (our own sector)
    "G46.74": "G46",
    "O84": "O",    # Public entities (fixed 1.0)
}


# ── Row type ──────────────────────────────────────────────────────────────────
class Row(NamedTuple):
    source: str
    series_id: str
    period: str
    value: float
    unit: str | None
    source_url: str | None


# ── HTTP helper ───────────────────────────────────────────────────────────────
def _get(url: str, timeout: int = 15) -> "requests.Response | None":  # type: ignore[name-defined]
    if not _HAS_REQUESTS:
        warnings.warn("requests not installed; skipping live API fetch")
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


# ── ECB ───────────────────────────────────────────────────────────────────────
def _fetch_ecb_series(key: str, series_id: str, source: str,
                      source_url: str, unit: str) -> list[Row]:
    url = f"{ECB_BASE}/{key}?format=csvdata&detail=dataonly"
    resp = _get(url)
    if resp is None:
        return []

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    safe = series_id.replace("/", "_")
    (RAW_DIR / f"{safe}.csv").write_text(resp.text, encoding="utf-8")

    rows: list[Row] = []
    try:
        reader = csv.DictReader(resp.text.splitlines())
        for record in reader:
            period = record.get("TIME_PERIOD") or record.get("time_period")
            obs = record.get("OBS_VALUE") or record.get("obs_value")
            if period is None or not obs:
                continue
            try:
                rows.append(Row(source, series_id, period, float(obs), unit, source_url))
            except ValueError:
                continue
    except Exception as exc:
        warnings.warn(f"Failed to parse ECB response for {series_id}: {exc}")
    return rows


# ── LUSTAT ────────────────────────────────────────────────────────────────────
def _try_lustat_sdmx() -> list[Row] | None:
    """Attempt LUSTAT SDMX REST API. Returns rows on success, None if unavailable."""
    for url in LUSTAT_SDMX_CANDIDATES:
        resp = _get(url)
        if resp is None:
            continue
        ct = resp.headers.get("Content-Type", "")
        if "csv" not in ct.lower() and "text" not in ct.lower():
            continue
        # Must look like SDMX/tabular CSV, not HTML
        if resp.text.strip().startswith("<!"):
            continue
        rows = _parse_lustat_response(resp.text, LUSTAT_SOURCE_URL)
        if rows:
            return rows
    return None


def _parse_lustat_response(text: str, source_url: str) -> list[Row]:
    """Parse SDMX-style CSV with ACTIVITY / TIME_PERIOD / OBS_VALUE columns."""
    rows: list[Row] = []
    try:
        reader = csv.DictReader(text.splitlines())
        if not reader.fieldnames or "ACTIVITY" not in reader.fieldnames:
            return []
        for record in reader:
            activity = (record.get("ACTIVITY") or "").strip()
            period = (record.get("TIME_PERIOD") or "").strip()
            raw_val = (record.get("OBS_VALUE") or "").strip()
            obs_status = (record.get("OBS_STATUS") or "").strip()
            if not activity or not period:
                continue
            if not raw_val:
                if obs_status in ("-", "M"):
                    raw_val = "0"
                else:
                    continue
            try:
                rows.append(Row(
                    "LUSTAT",
                    f"bankruptcies_{activity}",
                    period,
                    float(raw_val),
                    "count",
                    source_url,
                ))
            except ValueError:
                continue
    except Exception as exc:
        warnings.warn(f"Failed to parse LUSTAT response: {exc}")
    return rows


def _load_lustat_csv() -> list[Row]:
    """Parse the downloaded LUSTAT CSV from data/public/raw/."""
    if not LUSTAT_RAW_CSV.exists():
        warnings.warn(f"LUSTAT raw CSV not found: {LUSTAT_RAW_CSV}")
        return []
    with LUSTAT_RAW_CSV.open(newline="", encoding="utf-8") as fh:
        return _parse_lustat_response(fh.read(), LUSTAT_SOURCE_URL)


def _load_lustat() -> tuple[list[Row], str]:
    """Try SDMX API; fall back to raw CSV. Returns (rows, source_label)."""
    rows = _try_lustat_sdmx()
    if rows:
        return rows, "LUSTAT SDMX REST API"
    rows = _load_lustat_csv()
    return rows, "raw CSV (SDMX not available)"


# ── Stress indices ────────────────────────────────────────────────────────────
def _compute_stress_indices(lustat_rows: list[Row]) -> list[Row]:
    """Compute stress_index_<NACE> for every section with 2020-2025 data.

    stress = bankruptcies_2025 / mean(bankruptcies_2020..2024)

    Also appends fixed entries from FIXED_STRESS_INDICES (e.g., O=1.0).
    """
    from collections import defaultdict

    by_section: dict[str, dict[int, float]] = defaultdict(dict)
    for r in lustat_rows:
        if not r.series_id.startswith("bankruptcies_"):
            continue
        section = r.series_id[len("bankruptcies_"):]
        try:
            by_section[section][int(r.period)] = r.value
        except ValueError:
            continue

    stress_rows: list[Row] = []
    for section, year_vals in sorted(by_section.items()):
        base = [year_vals[y] for y in STRESS_BASE_YEARS if y in year_vals]
        if not base or STRESS_LATEST_YEAR not in year_vals:
            continue
        avg_base = sum(base) / len(base)
        if avg_base == 0:
            continue
        stress = year_vals[STRESS_LATEST_YEAR] / avg_base
        stress_rows.append(Row(
            "derived",
            f"stress_index_{section}",
            str(STRESS_LATEST_YEAR),
            round(stress, 6),
            "ratio",
            None,
        ))

    for section, val in FIXED_STRESS_INDICES.items():
        stress_rows.append(Row(
            "derived",
            f"stress_index_{section}",
            str(STRESS_LATEST_YEAR),
            float(val),
            "ratio",
            None,
        ))

    return stress_rows


# ── Persistence ───────────────────────────────────────────────────────────────
def _remove_stale_rows(engine: sa.Engine) -> int:
    """Delete rows from old STATEC source (manual CSV, superseded by LUSTAT)."""
    with engine.begin() as conn:
        result = conn.execute(
            text("DELETE FROM hm.public_series WHERE source = 'STATEC'")
        )
        return result.rowcount


def _insert_rows(engine: sa.Engine, rows: list[Row]) -> int:
    """Insert rows, skip on duplicate (source, series_id, period). Returns new rows."""
    if not rows:
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


def _upsert_stress_indices(engine: sa.Engine, rows: list[Row]) -> int:
    """Upsert stress index rows; updates value if it changed. Returns row count."""
    if not rows:
        return 0
    now = datetime.now(timezone.utc)
    count = 0
    with engine.begin() as conn:
        for r in rows:
            conn.execute(text("""
                INSERT INTO hm.public_series
                    (source, series_id, period, value, unit, fetched_at, source_url)
                VALUES (:src, :sid, :per, :val, :unit, :fat, :url)
                ON CONFLICT (source, series_id, period)
                    DO UPDATE SET value = EXCLUDED.value, fetched_at = EXCLUDED.fetched_at
            """), {
                "src": r.source, "sid": r.series_id, "per": r.period,
                "val": r.value, "unit": r.unit, "fat": now, "url": r.source_url,
            })
            count += 1
    return count


# ── Main entry point ──────────────────────────────────────────────────────────
def run(dry_run: bool = False, verbose: bool = True) -> dict:
    """Fetch all public series, upsert into DB, return summary dict.

    Returns
    -------
    dict with keys:
        source          : which LUSTAT source was used
        inserted        : new raw rows inserted (0 on idempotent re-run)
        stress_indices  : {series_id: value} for every computed stress index
        fill_in_count   : always 0 (LUSTAT data is complete)
    """
    engine = _owner_engine()

    # ── Step 1: ECB rates ────────────────────────────────────────────────────
    ecb_rows: list[Row] = []
    for ecb_key, sid, src, url, unit in ECB_SERIES:
        rows = _fetch_ecb_series(ecb_key, sid, src, url, unit)
        label = "optional " if sid == "euribor_3m" else ""
        if verbose:
            status = f"{len(rows)} rows" if rows else "unreachable — skipped"
            print(f"  ECB {label}{sid}: {status}")
        ecb_rows.extend(rows)

    # ── Step 2: LUSTAT bankruptcies ──────────────────────────────────────────
    lustat_rows, source_label = _load_lustat()
    if verbose:
        print(f"  LUSTAT bankruptcies: {source_label}, {len(lustat_rows)} rows")

    # ── Step 3: Sector stress indices ────────────────────────────────────────
    stress_rows = _compute_stress_indices(lustat_rows)
    if verbose:
        for sr in stress_rows:
            print(f"  {sr.series_id}: {sr.value:.4f} ({sr.period})")

    # ── Step 4: Persist ──────────────────────────────────────────────────────
    inserted = 0
    if not dry_run:
        stale = _remove_stale_rows(engine)
        if verbose and stale:
            print(f"  removed {stale} stale STATEC rows")
        inserted += _insert_rows(engine, ecb_rows + lustat_rows)
        _upsert_stress_indices(engine, stress_rows)

    if verbose:
        action = "would insert" if dry_run else "inserted"
        print(f"  {action} {inserted} new rows into hm.public_series")

    return {
        "source": source_label,
        "inserted": inserted,
        "stress_indices": {r.series_id: float(r.value) for r in stress_rows},
        "fill_in_count": 0,
    }


def get_stress_index(nace_sub: str, engine: sa.Engine | None = None) -> float:
    """Return the stress index for a customer segment NACE sub-code.

    Falls back to 1.0 if data is missing (as specified in the generator rules).
    """
    nace_section = SEGMENT_NACE_MAP.get(nace_sub)
    if nace_section is None:
        return 1.0
    eng = engine or _owner_engine()
    with eng.connect() as conn:
        val = conn.execute(text("""
            SELECT value FROM hm.public_series
            WHERE  series_id = :sid AND source = 'derived'
            ORDER BY period DESC LIMIT 1
        """), {"sid": f"stress_index_{nace_section}"}).scalar()
    if val is None:
        warnings.warn(
            f"No stress index for {nace_sub} (section {nace_section}); using 1.0"
        )
        return 1.0
    return float(val)


def _owner_engine() -> sa.Engine:
    return sa.create_engine(settings.postgres_dsn, pool_pre_ping=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch public reference data")
    parser.add_argument("--dry-run", action="store_true",
                        help="Parse and print without writing to DB")
    args = parser.parse_args()
    run(dry_run=args.dry_run, verbose=True)
