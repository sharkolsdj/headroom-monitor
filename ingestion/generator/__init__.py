"""Synthetic dataset generator for HeadRoom Monitor."""
from __future__ import annotations

from .scenarios import SCENARIO_IDS


def run(dataset_ids: list[str] | None = None, dry_run: bool = False, verbose: bool = True) -> dict:
    """Generate one or more synthetic datasets.

    Parameters
    ----------
    dataset_ids : list[str] | None
        IDs to generate; None means all 8.
    dry_run : bool
        Simulate and export CSVs but skip DB writes.
    verbose : bool
        Print progress.

    Returns
    -------
    dict mapping dataset_id -> {'checks': dict, 'rows': dict}
    """
    from ._pipeline import generate_dataset

    ids = dataset_ids or SCENARIO_IDS
    results = {}
    for did in ids:
        if verbose:
            print(f"\n=== {did} ===")
        results[did] = generate_dataset(did, dry_run=dry_run, verbose=verbose)
    return results
