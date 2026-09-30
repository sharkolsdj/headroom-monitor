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

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
