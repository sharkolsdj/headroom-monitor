"""Fictional company name generator for vault display names only.

Names are neutral invented strings — no real companies, no personal data.
"""
from __future__ import annotations

import numpy as np

_PREFIXES = [
    "Nord", "Sud", "Est", "Arc", "Euro", "Berg", "Val", "Bau", "Tri",
    "Pro", "Max", "Top", "Atel", "Visi", "Alta", "Delta", "Alpha",
    "Sigma", "Primo", "Ardis", "Volta", "Hansa", "Krona", "Lenz",
]

_ROOTS = [
    "bau", "werk", "haus", "group", "build", "atelier", "construct",
    "services", "trading", "properties", "partners", "systems",
    "works", "management", "logistics", "ventures", "depot",
]

_SUFFIXES_CUST = [
    "S.à r.l.", "S.A.", "SARL", "SA", "GmbH", "Ltd.",
    "& Cie", "& Partners", "Group",
]

_SUFFIXES_SUPP = [
    "Matériaux S.à r.l.", "Fournitures SA", "Supplies GmbH",
    "Distribution Ltd.", "Bau AG", "Materials SARL",
]

_IBAN_BANK_CODES = ["001", "002", "003", "099", "149", "263", "270"]


def make_display_name(rng: np.random.Generator, kind: str = "customer") -> str:
    if kind == "supplier":
        prefix = _PREFIXES[int(rng.integers(len(_PREFIXES)))]
        suf = _SUFFIXES_SUPP[int(rng.integers(len(_SUFFIXES_SUPP)))]
        return f"{prefix} {suf}"
    prefix = _PREFIXES[int(rng.integers(len(_PREFIXES)))]
    root = _ROOTS[int(rng.integers(len(_ROOTS)))]
    suf = _SUFFIXES_CUST[int(rng.integers(len(_SUFFIXES_CUST)))]
    return f"{prefix}{root} {suf}"


def make_iban(rng: np.random.Generator) -> str:
    """Generate a plausible-looking synthetic Luxembourg IBAN (LU format)."""
    bank = _IBAN_BANK_CODES[int(rng.integers(len(_IBAN_BANK_CODES)))]
    account = "".join(str(int(rng.integers(10))) for _ in range(13))
    bban = bank + account
    check = (98 - int(bban + "213000") % 97) % 99 + 1
    return f"LU{check:02d}{bban}"
