"""Entry point: python -m ingestion.generator [--all | --dataset S2_big_customer] [--dry-run]"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from ingestion.generator import run
from ingestion.generator.scenarios import SCENARIO_IDS
from ingestion.generator.writer import export_global_overview


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate synthetic HeadRoom Monitor datasets"
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--all", action="store_true",
                       help="Generate all 8 scenario datasets")
    group.add_argument("--dataset", metavar="ID",
                       help=f"Generate a single dataset (one of: {', '.join(SCENARIO_IDS)})")
    parser.add_argument("--dry-run", action="store_true",
                        help="Simulate and export CSVs without writing to DB")
    parser.add_argument("--quiet", action="store_true",
                        help="Suppress progress output")
    args = parser.parse_args()

    if not args.all and not args.dataset:
        parser.error("Specify --all or --dataset <ID>")

    if args.dataset and args.dataset not in SCENARIO_IDS:
        parser.error(f"Unknown dataset '{args.dataset}'. Choose from: {SCENARIO_IDS}")

    dataset_ids = SCENARIO_IDS if args.all else [args.dataset]
    verbose = not args.quiet

    t0 = time.perf_counter()
    if verbose:
        mode = "dry-run" if args.dry_run else "full"
        print(f"HeadRoom Monitor generator — {mode} mode")
        print(f"Datasets: {dataset_ids}")

    results = run(dataset_ids=dataset_ids, dry_run=args.dry_run, verbose=verbose)

    # Export global overview when generating all datasets
    if args.all:
        from ingestion.generator.writer import export_global_overview
        export_global_overview(dataset_ids)
        if verbose:
            print("  Wrote overview_all.csv")

    if args.all and not args.dry_run and verbose:
        _print_3way_table(dataset_ids)

    elapsed = time.perf_counter() - t0

    # Summary
    passed = sum(1 for r in results.values() if r.get("passed"))
    failed = len(results) - passed
    if verbose:
        print(f"\n=== Summary ===")
        for did, r in results.items():
            status = "PASS" if r.get("passed") else "FAIL"
            print(f"  {did}: {status}")
        print(f"\n{passed}/{len(results)} checks passed in {elapsed:.1f}s")
        if failed:
            print(f"  {failed} check(s) FAILED — see details above")

        # P&L tables (one per dataset, from overview.csv + config)
        if args.all or args.dataset:
            _print_pl_tables(dataset_ids, ROOT)

    return 0 if failed == 0 else 1


def _print_pl_tables(dataset_ids: list[str], root: Path) -> None:
    """Print an annual P&L summary table for each generated dataset."""
    import csv as csv_mod
    from ingestion.generator._cfg import load as load_cfg

    cfg = load_cfg()
    opex_annual = (cfg.payroll_net_monthly + cfg.payroll_social_monthly
                   + cfg.rent_monthly + cfg.opex_fixed_monthly) * 12
    dep_annual = cfg.depreciation_monthly * 12
    total_opex = opex_annual + dep_annual

    print("\n=== P&L tables (12-month history, EUR) ===")
    header = f"{'Dataset':<28} {'Revenue':>13} {'COGS(70%)':>12} {'GrossProfit':>12} {'Opex+Dep':>12} {'EBIT':>10} {'Tax21%':>8} {'NetProfit':>10} {'Top20%':>7}"
    print(header)
    print("-" * len(header))

    synthetic_dir = root / "data" / "synthetic"
    for did in dataset_ids:
        ov_path = synthetic_dir / did / "overview.csv"
        if not ov_path.exists():
            continue
        metrics: dict[str, str] = {}
        with ov_path.open(encoding="utf-8") as f:
            for rec in csv_mod.DictReader(f):
                metrics[rec["metric"]] = rec["value"]
        revenue = float(metrics.get("total_revenue", 0))
        net_profit = float(metrics.get("total_profit", 0))
        top20 = float(metrics.get("top20_revenue_share", 0))
        cogs = revenue * (1.0 - cfg.gross_margin)
        gross = revenue - cogs
        ebit = gross - total_opex
        tax = max(0.0, ebit * cfg.corporate_tax_rate)
        print(f"{did:<28} {revenue:>13,.0f} {cogs:>12,.0f} {gross:>12,.0f} {total_opex:>12,.0f} {ebit:>10,.0f} {tax:>8,.0f} {net_profit:>10,.0f} {top20:>6.1%}")


def _print_3way_table(dataset_ids: list[str]) -> None:
    """Print eval sim / engine on_time / engine expected min balance + weeks below threshold."""
    import sqlalchemy as sa
    from config import settings
    from ingestion.generator._cfg import load as load_cfg
    from engine._forecast import run_forecast
    from engine._loader import analyst_engine

    cfg = load_cfg()
    threshold = cfg.safety_threshold
    as_of = cfg.as_of_date
    from datetime import timedelta
    from sqlalchemy import text

    eval_eng  = sa.create_engine(settings.role_dsn("hm_evaluator"), pool_pre_ping=True)
    an_eng    = analyst_engine(settings)

    W = 105
    print(f"\n{'═' * W}")
    print(f"  3-WAY BALANCE TABLE  (threshold €{threshold:,.0f})")
    print(f"{'═' * W}")
    hdr = (f"  {'Dataset':<28}  {'eval(sim) min':>13}  {'<thr':>4}  "
           f"{'on_time min':>13}  {'<thr':>4}  {'expected min':>13}  {'<thr':>4}")
    print(hdr)
    print(f"  {'-'*100}")

    for did in dataset_ids:
        # ── eval (generator simulation with delays) ───────────────────────────
        with eval_eng.connect() as conn:
            rows = conn.execute(text(
                "SELECT closing_balance FROM eval.future_bank_balances "
                "WHERE dataset_id=:d AND week_start >= :a ORDER BY week_start"
            ), {"d": did, "a": as_of}).fetchall()
        if rows:
            ev_min  = min(float(r[0]) for r in rows)
            ev_wks  = sum(1 for r in rows if float(r[0]) < threshold)
        else:
            ev_min, ev_wks = 0.0, 0

        # ── engine on_time + expected ─────────────────────────────────────────
        try:
            res = run_forecast(did, an_eng, scenarios=["on_time", "expected"])
            ot_min  = min(w["closing"] for w in res["on_time"].weeks)
            ot_wks  = sum(1 for w in res["on_time"].weeks if w["closing"] < threshold)
            ex_min  = min(w["closing"] for w in res["expected"].weeks)
            ex_wks  = sum(1 for w in res["expected"].weeks if w["closing"] < threshold)
        except Exception as e:
            ot_min = ot_wks = ex_min = ex_wks = f"ERR:{e}"

        def fmt(v, n):
            if isinstance(v, str):
                return f"{'ERR':>13}  {'?':>4}"
            flag = f"{n:>4}" if n else "   -"
            return f"{v:>13,.0f}  {flag}"

        print(f"  {did:<28}  {fmt(ev_min, ev_wks)}  {fmt(ot_min, ot_wks)}  {fmt(ex_min, ex_wks)}")

    print(f"  {'-'*100}")
    print(f"  * = weeks below €{threshold:,.0f} threshold")


if __name__ == "__main__":
    sys.exit(main())
