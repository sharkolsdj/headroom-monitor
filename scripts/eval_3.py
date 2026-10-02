"""
Phase 3.3 evaluation: targets table + worsening customers (S2) + slowing segments (S3).
Run once; do not tune after this.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import sqlalchemy as sa

from config import settings
from engine._behaviour import RecencyBehaviour
from engine._forecast import run_forecast
from engine._loader import load_dataset
from engine._sector import detect_sector_trends, load_statec_stress

DEMO = ROOT / "data" / "demo"

# ── Load accuracy_summary.csv ─────────────────────────────────────────────────

def load_csv() -> dict[str, dict]:
    import csv
    rows = {}
    with open(DEMO / "accuracy_summary.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows[row["dataset_id"]] = row
    return rows


# ── Targets table ─────────────────────────────────────────────────────────────

PHASE2_BASELINE = {
    # From docs/PHASE3_PREREG.md
    "s2_threshold_week": ("6", "6 (exact)"),
    "s3_shows_crisis": ("P50 never breaches", "at least 1 week below"),
    "s4_spike_week": ("7", "7"),
    "false_alarm_total": ("4 (S2:2, S4:2)", "0 in S1/S5-S8; <=1 elsewhere"),
    "w1_pct": {"S1": "-16%", "S5": "-17%", "S6": "-30%", "S7": "-10%", "S8": "-17%"},
    "band_coverage": {"S1": "0%", "S5": "8%", "S6": "31%", "S7": "15%", "S8": "46%"},
}


def print_targets(rows: dict) -> None:
    print("\n=== Phase 3.3 Targets Table ===\n")
    print(f"{'Target':<55} {'Phase 2':>12} {'Phase 3':>12} {'Target':>12}")
    print("-" * 93)

    # S2 first forecast week below threshold
    s2 = rows.get("S2_big_customer", {})
    s2_fcst = s2.get("threshold_week_forecast", "N/A")
    s2_act  = s2.get("threshold_week_actual", "6")
    s2_phase3 = f"wk {s2_fcst} (act wk {s2_act})" if s2_fcst else "no breach"
    print(f"{'S2: forecast threshold week vs actual':<55} {'wk 6 (act 6)':>12} {s2_phase3:>12} {'within +-1wk':>12}")

    # S3 shows crisis
    s3 = rows.get("S3_sector_crisis", {})
    s3_fcst = s3.get("threshold_week_forecast", "")
    s3_act  = s3.get("threshold_week_actual", "3")
    s3_phase3 = f"wk {s3_fcst} (act wk {s3_act})" if s3_fcst else "no breach"
    print(f"{'S3: forecast shows crisis':<55} {'no breach':>12} {s3_phase3:>12} {'>=1wk, +-1wk':>12}")

    # S4 spike week
    s4 = rows.get("S4_outflow_spike", {})
    s4_fcst = s4.get("threshold_week_forecast", "7")
    print(f"{'S4: spike week':<55} {'wk 7':>12} {('wk ' + s4_fcst if s4_fcst else 'none'):>12} {'wk 7':>12}")

    # False alarm weeks
    fa_total = sum(int(r.get("false_alarm_weeks", 0) or 0) for r in rows.values())
    fa_s1s5_s8 = sum(
        int(rows[d].get("false_alarm_weeks", 0) or 0)
        for d in ["S1_normal", "S5_seasonality", "S6_new_customer",
                  "S7_partial_payments", "S8_month_end_close"]
        if d in rows
    )
    print(f"{'False alarms total (S1,S5-S8 must be 0)':<55} {'4':>12} {str(fa_total):>12} {'<=1 each':>12}")
    print(f"  S1,S5-S8 false alarms                                    {'0':>12} {str(fa_s1s5_s8):>12} {'0':>12}")

    # Week-1 errors for S1, S5-S8
    print(f"\n{'Week-1 absolute error':<55} {'Phase 2':>12} {'Phase 3':>12} {'Target':>12}")
    print("-" * 93)
    for did, base in [("S1_normal","-16%"), ("S5_seasonality","-17%"),
                      ("S6_new_customer","-30%"), ("S7_partial_payments","-10%"),
                      ("S8_month_end_close","-17%")]:
        pct = rows.get(did, {}).get("error_w1_pct", "N/A")
        label = f"{did.split('_')[0]}_{did.split('_')[1][:3]}"
        print(f"  {label:<53} {base:>12} {pct+'%':>12} {'<=10%':>12}")

    # Band coverage for S1, S5-S8
    print(f"\n{'Band coverage (actual in P10-P90)':<55} {'Phase 2':>12} {'Phase 3':>12} {'Target':>12}")
    print("-" * 93)
    for did, base in [("S1_normal","0%"), ("S5_seasonality","8%"),
                      ("S6_new_customer","31%"), ("S7_partial_payments","15%"),
                      ("S8_month_end_close","46%")]:
        cov = rows.get(did, {}).get("band_coverage_pct", "N/A")
        label = f"{did.split('_')[0]}_{did.split('_')[1][:3]}"
        print(f"  {label:<53} {base:>12} {cov+'%':>12} {'70-90%':>12}")


# ── Worsening customers in S2 ─────────────────────────────────────────────────

def print_s2_worsening(eng: sa.Engine) -> None:
    print("\n=== S2_big_customer: Customers Flagged Worsening ===\n")
    data = load_dataset(eng, "S2_big_customer")
    as_of = data["as_of"]
    beh = RecencyBehaviour(eng, "S2_big_customer", as_of)

    worsening = [
        (cc, beh.typical_delay(cc), beh.recent_delay(cc), beh.source(cc))
        for cc, flag in beh.cust_worsening.items()
        if flag
    ]
    worsening.sort(key=lambda x: -(x[2] - x[1]))  # sort by delta descending

    if not worsening:
        print("  (none)")
        return

    print(f"  {'Customer':>12}  {'Typical':>8}  {'Recent':>8}  {'Delta':>8}  {'Source':>12}")
    print(f"  {'-'*12}  {'-'*8}  {'-'*8}  {'-'*8}  {'-'*12}")
    for cc, typ, rec, src in worsening:
        delta = rec - typ
        print(f"  {cc:>12}  {typ:>8.1f}d  {rec:>8.1f}d  {'+' if delta>=0 else ''}{delta:>7.1f}d  {src:>12}")
    print(f"\n  Total worsening: {len(worsening)}")


# ── Slowing segments in S3 ────────────────────────────────────────────────────

def print_s3_segments(eng: sa.Engine) -> None:
    print("\n=== S3_sector_crisis: Slowing Segments ===\n")

    # Load from forecast.json sector_alerts if available
    forecast_path = DEMO / "S3_sector_crisis" / "forecast.json"
    if forecast_path.exists():
        doc = json.loads(forecast_path.read_text(encoding="utf-8"))
        alerts = doc.get("sector_alerts") or []
        if alerts:
            print(f"  {'Segment':>10}  {'Worsening':>10}  {'Total':>6}  {'Reason':>10}  {'Shift':>8}  {'STATEC%':>8}")
            print(f"  {'-'*10}  {'-'*10}  {'-'*6}  {'-'*10}  {'-'*8}  {'-'*8}")
            for a in alerts:
                print(
                    f"  {a['segment']:>10}  {a['n_worsening']:>10}  {a['n_customers']:>6}"
                    f"  {a['reason']:>10}  {a['shift_days']:>7.1f}d  {a['statec_stress_pct']:>7.1f}%"
                )
            return

    # Fallback: run detection directly
    data = load_dataset(eng, "S3_sector_crisis")
    as_of = data["as_of"]
    beh = RecencyBehaviour(eng, "S3_sector_crisis", as_of)
    statec = load_statec_stress()
    _, _, alerts = detect_sector_trends(
        cust_worsening=beh.cust_worsening,
        cust_recent_mean=beh.cust_recent_mean,
        cust_longrun_mean=beh.cust_longrun_mean,
        cust_seg=beh.cust_seg,
        seg_pool_entries=beh.seg_pool_entries,
        as_of=as_of,
        statec_stress=statec,
    )
    if not alerts:
        print("  (no slowing segments detected)")
    else:
        for a in alerts:
            print(f"  {a}")


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    rows = load_csv()
    print_targets(rows)

    eng = sa.create_engine(settings.role_dsn("hm_analyst"), pool_pre_ping=True)
    print_s2_worsening(eng)
    print_s3_segments(eng)

    print("\n=== END Phase 3.3 Evaluation ===")
    print("Do not tune after this point — except documented bug fixes.")


if __name__ == "__main__":
    main()
