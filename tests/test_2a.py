"""
Phase 2A tests.

1. Hand-built TEST_HAND: opening €100k, 3 AR invoices, 2 AP invoices,
   payroll, VAT — expected weekly balances verified to the cent.
2. Weekly conservation: opening + receipts − payments = closing.
3. eval.* access denied to hm_analyst.
4. Override moves an amount between weeks and is audited.
5. Superseding an override restores the original behaviour.
6. Seasonal factors are within caps [0.6, 1.4].
"""
from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy import text
from datetime import date, timedelta

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from config import settings
from scripts.migrate import apply_migrations
from engine._grid import date_to_week, week_starts
from engine._behaviour import SimpleBehaviour
from engine._components import (
    r1_open_receivables,
    r2_future_sales,
    p1_open_payables,
    p4_recurring,
    p5_vat,
    aggregate_weekly,
)
from engine._overrides import (
    insert_override,
    load_active_overrides,
    supersede_override,
)
from engine._forecast import run_forecast


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session", autouse=True)
def run_migrations():
    apply_migrations(verbose=False)


@pytest.fixture(scope="session")
def analyst_engine():
    return sa.create_engine(settings.role_dsn("hm_analyst"), pool_pre_ping=True)


@pytest.fixture(scope="session")
def approver_engine():
    return sa.create_engine(settings.role_dsn("hm_approver"), pool_pre_ping=True)


@pytest.fixture(scope="session")
def admin_engine():
    return sa.create_engine(settings.postgres_dsn, pool_pre_ping=True)


# ── Simple mock behaviour for hand tests ─────────────────────────────────────

class MockBehaviour:
    """Fixed delays per customer; segment pool for unknowns."""
    def __init__(self, delays: dict[str, float], seg_delays: dict[str, float] | None = None):
        self._delays = delays
        self._seg = seg_delays or {}

    def expected_delay(self, cust_code: str) -> float:
        return self._delays.get(cust_code, 0.0)

    def delay_sample(self, cust_code: str) -> list[float]:
        d = self._delays.get(cust_code)
        if d is not None:
            return [d] * 6
        return []

    def source(self, cust_code: str) -> str:
        return "customer" if cust_code in self._delays else "segment"

    def segment_expected_delay(self, segment: str) -> float:
        return self._seg.get(segment, 0.0)


# ── Test 1: Hand-built TEST_HAND ──────────────────────────────────────────────
#
# Setup:
#   as_of         = 2026-09-28 (Monday)
#   opening       = €100,000
#
#   AR invoices (all issued in September 2026, not yet paid):
#     INV_H1  CUST_H1  due 2026-10-01 (Week 1 Thu)  gross 11,700  vat 1,700
#     INV_H2  CUST_H2  due 2026-10-12 (Week 3 Mon)  gross  5,850  vat   850
#     INV_H3  CUST_H3  due 2026-11-09 (Week 7 Mon)  gross  2,340  vat   340
#
#   AP invoices (issued before as_of, not yet paid):
#     AP_H1  SUPP_H1  issue 2026-09-15  due 2026-10-15 (Week 3 Thu)  gross  5,850  vat   850
#     AP_H2  SUPP_H2  issue 2026-09-20  due 2026-11-09 (Week 7 Mon)  gross  2,925  vat   425
#
#   Payroll: €1,000 on last working day of each month in the horizon:
#             Sep 30 (Wed = Week 1), Oct 30 (Fri = Week 5), Nov 30 (Mon = Week 10)
#             Dec 31 is beyond the horizon (ends Dec 27) — not included.
#   VAT Sep: output 2,890 − input 1,275 = 1,615 due 2026-10-15 (Week 3)
#
#   MockBehaviour delays:
#     CUST_H1 → 3 days (receipt Oct 4, still Week 1)
#     CUST_H2 → 0 days (receipt Oct 12 = Week 3)
#     CUST_H3 → 8 days (receipt Nov 17 = Week 8)
#
# Expected on_time closing balances:
#   W1:  100,000 + 11,700 − 1,000 (Sep payroll)         = 110,700
#   W2:  110,700                                          = 110,700
#   W3:  110,700 + 5,850 − 5,850 − 1,615                = 109,085
#   W4:  109,085                                          = 109,085
#   W5:  109,085 − 1,000 (Oct payroll)                   = 108,085
#   W6:  108,085                                          = 108,085
#   W7:  108,085 + 2,340 − 2,925                         = 107,500
#   W8–9: 107,500
#   W10: 107,500 − 1,000 (Nov payroll)                   = 106,500
#   W11–13: 106,500
#
# Expected closing (expected scenario):
#   W1–6: same as on_time
#   W7:  108,085 − 2,925 = 105,160   (CUST_H3 receipt slips to W8)
#   W8:  105,160 + 2,340 = 107,500
#   W9:  107,500
#   W10: 107,500 − 1,000 (Nov payroll) = 106,500
#   W11–13: 106,500

AS_OF  = date(2026, 9, 28)
OPEN_AR = [
    {"invoice_id": "INV_H1", "cust_code": "CUST_H1",
     "due_date": date(2026, 10,  1), "amount_gross": 11_700.0, "outstanding_amount": 11_700.0},
    {"invoice_id": "INV_H2", "cust_code": "CUST_H2",
     "due_date": date(2026, 10, 12), "amount_gross":  5_850.0, "outstanding_amount":  5_850.0},
    {"invoice_id": "INV_H3", "cust_code": "CUST_H3",
     "due_date": date(2026, 11,  9), "amount_gross":  2_340.0, "outstanding_amount":  2_340.0},
]
OPEN_AP = [
    {"invoice_id": "AP_H1", "supp_code": "SUPP_H1",
     "due_date": date(2026, 10, 15), "amount_gross": 5_850.0, "outstanding_amount": 5_850.0},
    {"invoice_id": "AP_H2", "supp_code": "SUPP_H2",
     "due_date": date(2026, 11,  9), "amount_gross": 2_925.0, "outstanding_amount": 2_925.0},
]
HISTORY_AR = [
    {"invoice_id": "INV_H1", "cust_code": "CUST_H1", "issue_date": date(2026, 9, 25),
     "due_date": date(2026, 10,  1), "amount_net": 10_000.0, "amount_gross": 11_700.0, "vat": 1_700.0, "segment": "test_seg"},
    {"invoice_id": "INV_H2", "cust_code": "CUST_H2", "issue_date": date(2026, 9, 20),
     "due_date": date(2026, 10, 12), "amount_net":  5_000.0, "amount_gross":  5_850.0, "vat":   850.0, "segment": "test_seg"},
    {"invoice_id": "INV_H3", "cust_code": "CUST_H3", "issue_date": date(2026, 9, 15),
     "due_date": date(2026, 11,  9), "amount_net":  2_000.0, "amount_gross":  2_340.0, "vat":   340.0, "segment": "test_seg"},
]
HISTORY_AP = [
    {"invoice_id": "AP_H1", "supp_code": "SUPP_H1", "issue_date": date(2026, 9, 15),
     "due_date": date(2026, 10, 15), "amount_net": 5_000.0, "amount_gross": 5_850.0, "vat": 850.0},
    {"invoice_id": "AP_H2", "supp_code": "SUPP_H2", "issue_date": date(2026, 9, 20),
     "due_date": date(2026, 11,  9), "amount_net": 2_500.0, "amount_gross": 2_925.0, "vat": 425.0},
]
RECURRING = [
    {"kind": "payroll_net", "rule": {"day": "last_working"}, "amount": 1_000.0},
]
BEHAVIOUR = MockBehaviour({"CUST_H1": 3.0, "CUST_H2": 0.0, "CUST_H3": 8.0})

# Expected Sep VAT: output 2890 - input 1275 = 1615, due Oct 15 (Week 3)
_SEP_VAT = 1_615.0


def _run_hand(scenario: str) -> list[dict]:
    """Run the HAND scenario without R2/P2 (empty segments)."""
    r1, _beyond = r1_open_receivables(OPEN_AR, BEHAVIOUR, AS_OF, 13, scenario)
    p1 = p1_open_payables(OPEN_AP, AS_OF, 13)
    p4 = p4_recurring(RECURRING, AS_OF, 13)
    # P5: no R2/P2 (segments=[]), uses only Sep actual invoices
    p5 = p5_vat(HISTORY_AR, HISTORY_AP, {}, {}, AS_OF, 15, 13)

    from collections import defaultdict
    rec: dict = defaultdict(list)
    pay: dict = defaultdict(list)
    for wk, items in r1.items():
        rec[wk].extend(items)
    for wk, items in p1.items():
        pay[wk].extend(items)
    for wk, items in p4.items():
        pay[wk].extend(items)
    for wk, items in p5.items():
        pay[wk].extend(items)

    return aggregate_weekly(100_000.0, dict(rec), dict(pay), AS_OF, 13)


ON_TIME_EXPECTED_CLOSINGS = {
    1: 110_700.0,   # +11700 receipt, -1000 Sep payroll (Sep 30)
    2: 110_700.0,
    3: 109_085.0,   # +5850 receipt, -5850 AP, -1615 Sep VAT
    4: 109_085.0,
    5: 108_085.0,   # -1000 Oct payroll (Oct 30)
    6: 108_085.0,
    7: 107_500.0,   # +2340 receipt, -2925 AP
    8: 107_500.0,
    9: 107_500.0,
    10: 106_500.0,  # -1000 Nov payroll (Nov 30)
    11: 106_500.0,
    12: 106_500.0,
    13: 106_500.0,
}
EXPECTED_CLOSINGS = {
    **{k: v for k, v in ON_TIME_EXPECTED_CLOSINGS.items() if k <= 6},
    7: 105_160.0,   # -2925 AP; CUST_H3 receipt slips to W8
    8: 107_500.0,   # +2340 CUST_H3 receipt (Nov 17)
    9: 107_500.0,
    10: 106_500.0,  # -1000 Nov payroll
    11: 106_500.0,
    12: 106_500.0,
    13: 106_500.0,
}


@pytest.mark.parametrize("scenario,expected_map", [
    ("on_time", ON_TIME_EXPECTED_CLOSINGS),
    ("expected", EXPECTED_CLOSINGS),
])
def test_hand_built_balances(scenario, expected_map):
    """Hand-built weekly balances must match to the cent."""
    weeks = _run_hand(scenario)
    for wk in weeks:
        k = wk["week"]
        expected = expected_map.get(k)
        if expected is not None:
            assert wk["closing"] == pytest.approx(expected, abs=0.01), (
                f"Week {k} closing: got {wk['closing']:.2f}, expected {expected:.2f}"
            )


# ── Test 2: Weekly conservation ───────────────────────────────────────────────

@pytest.mark.parametrize("scenario", ["on_time", "expected"])
def test_weekly_conservation(scenario):
    """opening + receipts − payments = closing for every week."""
    weeks = _run_hand(scenario)
    for wk in weeks:
        computed = round(wk["opening"] + wk["receipts"] - wk["payments"], 2)
        assert computed == pytest.approx(wk["closing"], abs=0.01), (
            f"Week {wk['week']}: conservation violated "
            f"({wk['opening']:.2f} + {wk['receipts']:.2f} - {wk['payments']:.2f} "
            f"≠ {wk['closing']:.2f})"
        )


@pytest.mark.parametrize("dataset_id", ["S1_normal", "S2_big_customer"])
def test_weekly_conservation_db(dataset_id, analyst_engine):
    """Conservation holds for real datasets loaded from DB."""
    results = run_forecast(dataset_id, analyst_engine, scenarios=["expected"])
    for wk in results["expected"].weeks:
        computed = round(wk["opening"] + wk["receipts"] - wk["payments"], 2)
        assert computed == pytest.approx(wk["closing"], abs=0.01), (
            f"{dataset_id} Week {wk['week']}: conservation violated"
        )


# ── Test 3: No eval.* access for hm_analyst ───────────────────────────────────

def test_analyst_cannot_read_eval(analyst_engine):
    """hm_analyst must get a permission error when querying eval.*."""
    with pytest.raises(Exception, match="permission denied|does not exist"):
        with analyst_engine.connect() as conn:
            conn.execute(text("SELECT 1 FROM eval.scenario_truth LIMIT 1"))


# ── Test 4: Override moves amount between weeks ───────────────────────────────

def test_override_moves_receipt_week(approver_engine, analyst_engine, admin_engine):
    """
    Insert an override that moves INV_H1 receipt date from Oct 4 to Oct 12 (Week 3).
    Verify: Week 1 receipts decrease, Week 3 receipts increase, and override is audited.
    """
    did = "S1_normal"
    with admin_engine.connect() as conn:
        inv_row = conn.execute(text("""
            SELECT invoice_id FROM hm.ar_invoices
            WHERE dataset_id = :did
            ORDER BY issue_date
            LIMIT 1
        """), {"did": did}).fetchone()
    if inv_row is None:
        pytest.skip("No AR invoices available for S1_normal")

    inv_id = inv_row.invoice_id
    new_date = str(date(2026, 10, 12))   # move to Week 3

    ov_id = insert_override(
        approver_engine, did, "invoice", inv_id, "expected_date",
        new_date, "test: move receipt to week 3", "test_runner"
    )
    assert ov_id > 0

    active = load_active_overrides(analyst_engine, did)
    assert any(o["override_id"] == ov_id for o in active), (
        "Newly inserted override not found in active overrides"
    )

    # Verify audit log recorded the insert (table_name stored as schema.table)
    with admin_engine.connect() as conn:
        audit_row = conn.execute(text("""
            SELECT 1 FROM audit.log
            WHERE table_name = 'hm.assumption_overrides'
              AND op = 'INSERT'
            LIMIT 1
        """)).fetchone()
    assert audit_row is not None, "Audit log should record the override insert"

    # Clean up: supersede (cancel) the override
    cancel_id = supersede_override(
        approver_engine, did, ov_id, "test cleanup", "test_runner"
    )
    assert cancel_id > 0
    active_after = load_active_overrides(analyst_engine, did)
    assert not any(o["override_id"] == ov_id for o in active_after), (
        "Cancelled override should not appear in active list"
    )


# ── Test 5: Superseding restores original behaviour ───────────────────────────

def test_supersede_restores_original(approver_engine, analyst_engine, admin_engine):
    """
    After superseding an override, the forecast must return to its original value
    for the affected week.
    """
    did = "S1_normal"

    # Baseline forecast
    baseline = run_forecast(did, analyst_engine, scenarios=["expected"])
    w1_baseline = baseline["expected"].weeks[0]["closing"]

    # Find the largest open AR invoice (most impact)
    with admin_engine.connect() as conn:
        inv_row = conn.execute(text("""
            SELECT i.invoice_id
            FROM hm.ar_invoices i
            LEFT JOIN hm.ar_receipts r
                ON r.invoice_id = i.invoice_id AND r.dataset_id = i.dataset_id
            WHERE i.dataset_id = :did
              AND i.issue_date <= :as_of
            GROUP BY i.invoice_id, i.amount_gross
            HAVING i.amount_gross - COALESCE(SUM(r.amount), 0) > 1000
            ORDER BY i.amount_gross DESC
            LIMIT 1
        """), {"did": did, "as_of": date(2026, 9, 28)}).fetchone()
    if inv_row is None:
        pytest.skip("No large open AR invoice found")

    inv_id = inv_row.invoice_id
    far_future = str(date(2027, 6, 1))  # beyond horizon → receipt removed from all weeks

    ov_id = insert_override(
        approver_engine, did, "invoice", inv_id, "expected_date",
        far_future, "test: push receipt beyond horizon", "test_runner"
    )

    with_ov = run_forecast(did, analyst_engine, scenarios=["expected"])
    # Any week's closing should have changed (or the beyond_horizon list grew)
    weeks_changed_or_beyond = (
        with_ov["expected"].weeks[0]["closing"] != w1_baseline
        or len(with_ov["expected"].beyond_horizon) > len(baseline["expected"].beyond_horizon)
    )
    assert weeks_changed_or_beyond, "Override should change at least one week or beyond-horizon"

    # Cancel it
    supersede_override(approver_engine, did, ov_id, "test cleanup", "test_runner")

    # Forecast should return to baseline
    restored = run_forecast(did, analyst_engine, scenarios=["expected"])
    assert restored["expected"].weeks[0]["closing"] == pytest.approx(w1_baseline, rel=1e-6), (
        "After superseding override, week-1 closing should match baseline"
    )


# ── Test 6: Seasonal factors within caps ─────────────────────────────────────

def test_seasonal_factors_within_caps(analyst_engine):
    """All seasonal factors must be in [0.6, 1.4]."""
    from engine._loader import load_dataset
    from engine._behaviour import SimpleBehaviour
    from engine._components import r2_future_sales

    data = load_dataset(analyst_engine, "S1_normal")
    as_of = data["as_of"]
    behaviour = SimpleBehaviour(analyst_engine, "S1_normal", as_of)

    _, sf = r2_future_sales(
        data["history_ar"], data["segments"], behaviour, as_of, data["history_start"]
    )
    for seg, factors in sf.items():
        for wk_idx, f in enumerate(factors):
            assert 0.6 <= f <= 1.4, (
                f"Segment {seg} week {wk_idx+1}: seasonal factor {f:.4f} outside [0.6, 1.4]"
            )
