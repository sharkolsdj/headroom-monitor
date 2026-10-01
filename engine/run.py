"""
Entry point: python -m engine.run --dataset S2 [--scenario expected,on_time] [--all]

Prints a weekly balance table per requested scenario.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from config import settings
from ingestion.generator.scenarios import SCENARIO_IDS
from engine._loader import analyst_engine
from engine._forecast import run_forecast, ENGINE_VERSION


def _print_weekly_table(dataset_id: str, results: dict) -> None:
    print(f"\n{'─'*72}")
    print(f"  {dataset_id}  (engine {ENGINE_VERSION})")
    print(f"{'─'*72}")
    header = f"{'Wk':>3}  {'Week start':>12}  {'Opening':>12}  {'Receipts':>12}  {'Payments':>12}  {'Closing':>12}"
    for scenario, result in results.items():
        print(f"\n  Scenario: {scenario}")
        print(f"  {'─'*60}")
        print(f"  {header}")
        print(f"  {'─'*60}")
        for wk in result.weeks:
            marker = " *" if wk["closing"] < 509_538 else "  "
            print(
                f"  {wk['week']:>3}  {str(wk['week_start']):>12}  "
                f"{wk['opening']:>12,.0f}  {wk['receipts']:>12,.0f}  "
                f"{wk['payments']:>12,.0f}  {wk['closing']:>12,.0f}{marker}"
            )
        if result.beyond_horizon:
            print(f"\n  Beyond-horizon R1 items: {len(result.beyond_horizon)}")
        if result.applied_overrides:
            print(f"  Active overrides: {len(result.applied_overrides)}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="HeadRoom Monitor cash-forecast engine"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true", help="Run all 8 datasets")
    group.add_argument("--dataset", metavar="ID", help="Run a single dataset")
    parser.add_argument(
        "--scenario", default="expected,on_time",
        help="Comma-separated scenarios (default: expected,on_time)"
    )
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    if args.dataset and args.dataset not in SCENARIO_IDS:
        parser.error(f"Unknown dataset '{args.dataset}'. Choose from: {SCENARIO_IDS}")

    dataset_ids = SCENARIO_IDS if args.all else [args.dataset]
    scenarios = [s.strip() for s in args.scenario.split(",")]

    engine = analyst_engine(settings)

    errors: list[str] = []
    for did in dataset_ids:
        try:
            results = run_forecast(did, engine, scenarios=scenarios)
            if not args.quiet:
                _print_weekly_table(did, results)
        except Exception as exc:
            print(f"ERROR {did}: {exc}", file=sys.stderr)
            errors.append(did)

    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
