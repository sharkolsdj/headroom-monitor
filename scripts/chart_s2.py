"""
Generate S2 forecast review chart: docs/img/S2_forecast.png

Shows: on_time (blue), expected (green) with P10–P90 band, stress (orange),
threshold line (red dashed).
Run: python -m scripts.chart_s2   (or  python scripts/chart_s2.py)
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import sqlalchemy as sa

from config import settings
from engine._forecast import run_forecast

DATASET_ID = "S2_big_customer"
THRESHOLD = 509_538.0       # 4 × weekly_fixed_costs
DEP_ANNUAL = 250_000.0
GROSS_MARGIN = 0.30
VAT_RATE = 0.17
MC_N_RUNS = 1_000


def make_chart(dataset_id: str, out_path: Path) -> None:
    eng = sa.create_engine(settings.role_dsn("hm_analyst"), pool_pre_ping=True)

    results = run_forecast(
        dataset_id, eng,
        scenarios=["expected", "on_time"],
        include_stress=True,
        include_mc=True,
        threshold=THRESHOLD,
        dep_annual=DEP_ANNUAL,
        gross_margin=GROSS_MARGIN,
        vat_rate=VAT_RATE,
        mc_n_runs=MC_N_RUNS,
    )

    exp = results["expected"]
    on_time = results["on_time"]
    stress = results.get("stress")

    weeks = [w["week"] for w in exp.weeks]
    # Use MC P50 as the "expected" line so it sits inside the band
    p50_src = exp.p50_weeks if exp.p50_weeks else exp.weeks
    exp_close   = [w["closing"] / 1_000 for w in p50_src]
    ot_close    = [w["closing"] / 1_000 for w in on_time.weeks]
    st_close    = [w["closing"] / 1_000 for w in stress.weeks] if stress else None
    p10 = [exp.mc_band[k]["p10"] / 1_000 for k in weeks] if exp.mc_band else None
    p90 = [exp.mc_band[k]["p90"] / 1_000 for k in weeks] if exp.mc_band else None

    fig, ax = plt.subplots(figsize=(12, 6))

    # P10–P90 band
    if p10 and p90:
        ax.fill_between(weeks, p10, p90, alpha=0.20, color="green", label="P10–P90 band")

    # Lines
    ax.plot(weeks, ot_close, "b-o", linewidth=1.5, markersize=4, label="on_time")
    ax.plot(weeks, exp_close, "g-o", linewidth=2.0, markersize=4,
            label="expected (P50)")
    if st_close:
        ax.plot(weeks, st_close, color="orange", linestyle="--", linewidth=1.5,
                markersize=4, marker="s", label="stress")

    # Threshold
    thr_k = THRESHOLD / 1_000
    ax.axhline(thr_k, color="red", linestyle=":", linewidth=1.5, label=f"threshold €{THRESHOLD/1000:.0f}k")

    ax.set_xlabel("Week", fontsize=11)
    ax.set_ylabel("Closing balance (€k)", fontsize=11)
    ax.set_title(f"{dataset_id} — 13-week cash forecast (as of 2026-09-28)", fontsize=13)
    ax.set_xticks(weeks)
    ax.yaxis.set_major_formatter(ticker.FuncFormatter(lambda x, _: f"€{x:,.0f}k"))
    ax.legend(loc="upper right", fontsize=9)
    ax.grid(True, alpha=0.3)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    out = ROOT / "docs" / "img" / f"{DATASET_ID}_forecast.png"
    make_chart(DATASET_ID, out)
