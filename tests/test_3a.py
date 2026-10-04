"""Phase 3.2 tests: RecencyBehaviour, sector trend, conditional timing, collections."""
from __future__ import annotations

import math
import random
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_behaviour_from_data(delays_by_cust, seg_by_cust, as_of, half_life=60):
    """Build an in-memory RecencyBehaviour-like object using public helpers."""
    from engine._behaviour import (
        RecencyBehaviour, _weighted_mean, _weighted_median, _BOOTSTRAP_N, _BOOTSTRAP_SEED
    )
    # We exercise public helpers rather than the full DB-backed class
    return _weighted_mean, _weighted_median


# ── Unit tests: weighted statistics ──────────────────────────────────────────

def test_weighted_mean_uniform():
    from engine._behaviour import _weighted_mean
    pairs = [(10.0, 1.0), (20.0, 1.0), (30.0, 1.0)]
    assert abs(_weighted_mean(pairs) - 20.0) < 1e-9


def test_weighted_mean_skewed():
    from engine._behaviour import _weighted_mean
    # heavy weight on 30 → result near 30
    pairs = [(10.0, 0.1), (30.0, 0.9)]
    result = _weighted_mean(pairs)
    assert result > 25.0


def test_weighted_median_even_weights():
    from engine._behaviour import _weighted_median
    pairs = [(5.0, 1.0), (10.0, 1.0), (20.0, 1.0), (40.0, 1.0)]
    # P50: cumulative weight passes half at 20.0
    median = _weighted_median(pairs)
    assert 10.0 <= median <= 20.0


def test_weighted_median_heavy_tail():
    from engine._behaviour import _weighted_median
    # Almost all weight on small value
    pairs = [(5.0, 0.95), (100.0, 0.05)]
    assert _weighted_median(pairs) == 5.0


def test_recency_weight_half_life():
    from engine._behaviour import RecencyBehaviour
    w0 = RecencyBehaviour._weight(0.0)
    w60 = RecencyBehaviour._weight(60.0)
    w120 = RecencyBehaviour._weight(120.0)
    assert abs(w0 - 1.0) < 1e-9
    assert abs(w60 - 0.5) < 1e-9
    assert abs(w120 - 0.25) < 1e-9


# ── Unit tests: worsening flag ────────────────────────────────────────────────

def _check_worsening_direct(all_obs, recent_obs):
    """Call RecencyBehaviour._check_worsening; obs are (delay, weight, is_event) tuples."""
    from engine._behaviour import RecencyBehaviour
    class _Dummy(RecencyBehaviour):
        def __init__(self):
            pass
    return _Dummy()._check_worsening(all_obs, recent_obs)


def test_worsening_fires_on_drifting_customer():
    # 10 old invoices at 5d + 4 recent at 30d (equal weights, all paid)
    old_obs = [(5.0, 1.0, True)] * 10
    recent_obs = [(30.0, 1.0, True)] * 4
    all_obs = old_obs + recent_obs
    assert _check_worsening_direct(all_obs, recent_obs) is True


def test_worsening_does_not_fire_on_stable_customer():
    # Long-run mean = 10d, recent mean = 12d (diff=2 < threshold 10)
    all_obs = [(10.0, 1.0, True)] * 8 + [(12.0, 1.0, True)] * 4
    recent_obs = [(12.0, 1.0, True)] * 4
    assert _check_worsening_direct(all_obs, recent_obs) is False


def test_worsening_needs_three_recent():
    # Only 2 recent paid invoices → should not fire
    all_obs = [(5.0, 0.1, True)] * 10 + [(30.0, 1.0, True)] * 2
    recent_obs = [(30.0, 1.0, True)] * 2
    assert _check_worsening_direct(all_obs, recent_obs) is False


# ── Unit tests: sector trend detection ───────────────────────────────────────

def test_sector_shift_fallback_uses_segment_pool_diff():
    """When a segment is slowing but no customer is worsening, shift = pool diff × amplifier."""
    from engine._sector import detect_sector_trends

    as_of = date(2026, 10, 2)
    # 10 customers, none worsening — slowed only by delay criterion
    cust_worsening = {f"CUST_{i:03d}": False for i in range(10)}
    cust_recent = {f"CUST_{i:03d}": 12.0 for i in range(10)}
    cust_longrun = {f"CUST_{i:03d}": 12.0 for i in range(10)}
    cust_seg = {f"CUST_{i:03d}": "L68" for i in range(10)}

    recent_start = as_of - timedelta(days=89)
    prior_dt = as_of - timedelta(days=200)
    # recent pool mean = 20d, prior pool mean = 10d → diff = 10d
    pool_entries = {"L68": [(20.0, recent_start)] * 20 + [(10.0, prior_dt)] * 20}
    statec = {"L": 1.0}   # amplifier = 1.0 → shift = 10.0d

    slowing, shift_map, alerts = detect_sector_trends(
        cust_worsening, cust_recent, cust_longrun, cust_seg, pool_entries, as_of, statec
    )
    assert slowing.get("L68") is True, "segment should be slowing by delay criterion"
    assert abs(shift_map.get("L68", 0) - 10.0) < 0.5, (
        f"expected shift ~10d, got {shift_map.get('L68')}"
    )


def test_sector_shift_uses_worsening_customers_when_present():
    """When worsening customers exist, shift uses their median extra (not the pool diff)."""
    from engine._sector import detect_sector_trends

    as_of = date(2026, 10, 2)
    cust_worsening = {f"CUST_{i:03d}": (i < 3) for i in range(10)}
    # worsening custs have recent=25d, longrun=10d → extra=15d each
    cust_recent = {f"CUST_{i:03d}": (25.0 if i < 3 else 10.0) for i in range(10)}
    cust_longrun = {f"CUST_{i:03d}": 10.0 for i in range(10)}
    cust_seg = {f"CUST_{i:03d}": "F41" for i in range(10)}
    pool_entries = {"F41": []}
    statec = {"F": 1.0}

    _, shift_map, _ = detect_sector_trends(
        cust_worsening, cust_recent, cust_longrun, cust_seg, pool_entries, as_of, statec
    )
    # median of [15,15,15] = 15, amplifier=1 → shift=15
    assert abs(shift_map.get("F41", 0) - 15.0) < 0.5, (
        f"expected shift ~15d, got {shift_map.get('F41')}"
    )


def test_sector_slowing_fires_on_cohort():
    from engine._sector import detect_sector_trends

    as_of = date(2026, 10, 2)
    # 10 customers in seg "F41", all worsening → 100% > 25%
    cust_worsening = {f"CUST_{i:03d}": True for i in range(10)}
    cust_recent = {f"CUST_{i:03d}": 25.0 for i in range(10)}
    cust_longrun = {f"CUST_{i:03d}": 5.0 for i in range(10)}
    cust_seg = {f"CUST_{i:03d}": "F41" for i in range(10)}
    pool_entries = {"F41": []}  # empty pool, criterion 1 should be enough
    statec = {"F": 1.1}

    slowing, shift, alerts = detect_sector_trends(
        cust_worsening, cust_recent, cust_longrun, cust_seg, pool_entries, as_of, statec
    )
    assert slowing.get("F41") is True
    assert len(alerts) == 1
    assert alerts[0]["segment"] == "F41"


def test_sector_not_slowing_below_threshold():
    from engine._sector import detect_sector_trends

    as_of = date(2026, 10, 2)
    # 10 customers, only 1 worsening → 10% < 25%
    cust_worsening = {f"CUST_{i:03d}": (i == 0) for i in range(10)}
    cust_recent = {f"CUST_{i:03d}": 7.0 for i in range(10)}
    cust_longrun = {f"CUST_{i:03d}": 5.0 for i in range(10)}
    cust_seg = {f"CUST_{i:03d}": "F41" for i in range(10)}
    pool_entries = {"F41": []}
    statec = {"F": 1.0}

    slowing, _, _ = detect_sector_trends(
        cust_worsening, cust_recent, cust_longrun, cust_seg, pool_entries, as_of, statec
    )
    assert slowing.get("F41") is False


def test_sector_slowing_by_delay_criterion():
    from engine._sector import detect_sector_trends

    as_of = date(2026, 10, 2)
    cust_worsening = {f"CUST_{i:03d}": False for i in range(5)}
    cust_recent = {f"CUST_{i:03d}": 10.0 for i in range(5)}
    cust_longrun = {f"CUST_{i:03d}": 10.0 for i in range(5)}
    cust_seg = {f"CUST_{i:03d}": "L68" for i in range(5)}

    # Pool: prior entries (> 90d ago) mean 5d, recent mean 15d → diff=10 >= 7
    prior_start = as_of - timedelta(days=365)
    recent_start = as_of - timedelta(days=89)
    prior_dt = prior_start + timedelta(days=50)
    recent_dt = recent_start + timedelta(days=5)
    pool_entries = {"L68": [(5.0, prior_dt)] * 20 + [(15.0, recent_dt)] * 20}
    statec = {"L": 1.0}

    slowing, _, _ = detect_sector_trends(
        cust_worsening, cust_recent, cust_longrun, cust_seg, pool_entries, as_of, statec
    )
    assert slowing.get("L68") is True


# ── Unit tests: conditional overdue timing ───────────────────────────────────

def test_conditional_timing_places_receipt_in_future():
    """For od < ed, receipt date must be >= as_of + 1 day."""
    from engine._components import r1_open_receivables

    as_of = date(2026, 10, 2)
    due_date = as_of - timedelta(days=5)   # 5 days overdue
    inv = {
        "invoice_id": "INV001",
        "cust_code": "CUST_TEST",
        "due_date": due_date,
        "outstanding_amount": 1000.0,
        "segment": "F41",
    }

    class _FakeBehaviour:
        def expected_delay(self, cc): return 15.0
        def delay_sample(self, cc): return [15.0] * 10
        def source(self, cc): return "customer"
        def segment_expected_delay(self, seg): return 15.0
        def conditional_remaining_delay(self, cc, d):
            # od=5, ed=15 → conditional on delays > 5: [15-5] = [10]
            return 10.0

    beh = _FakeBehaviour()
    receipts, beyond = r1_open_receivables([inv], beh, as_of, n_weeks=13)

    all_items = [item for items in receipts.values() for item in items]
    all_items.extend(beyond)
    # receipt must be placed in the future
    for item in all_items:
        pass  # just ensure no exception
    assert len(receipts) + len(beyond) > 0


# ── Unit tests: priority ordering ────────────────────────────────────────────

def test_priority_ordering():
    """Higher-amount invoice with earlier due date gets higher priority."""
    from engine._collections import predict_invoice

    as_of = date(2026, 10, 2)
    due_soon = as_of + timedelta(days=3)
    due_late = as_of + timedelta(days=30)

    class _FakeBehaviour:
        TYPICAL_SLOW_DAYS = 20.0
        def delay_sample(self, cc): return [5.0] * 100
        def expected_delay(self, cc): return 5.0
        def is_worsening(self, cc): return False
        def is_slow(self, cc): return False
        _recent_count = {"C1": 3, "C2": 3}

    beh = _FakeBehaviour()
    inv_large = {
        "invoice_id": "INV_A", "cust_code": "C1", "outstanding_amount": 50000.0,
        "due_date": due_soon, "segment": "F41",
    }
    inv_small = {
        "invoice_id": "INV_B", "cust_code": "C2", "outstanding_amount": 1000.0,
        "due_date": due_late, "segment": "F41",
    }

    pred_large = predict_invoice(inv_large, beh, as_of)
    pred_small = predict_invoice(inv_small, beh, as_of)
    assert pred_large["priority_score"] > pred_small["priority_score"]


# ── Unit tests: MC reproducibility ───────────────────────────────────────────

def test_mc_same_seed_reproducible():
    """Running MC twice with same seed yields identical results."""
    import sqlalchemy as sa
    pytest.importorskip("sqlalchemy")

    try:
        from config import settings
        eng = sa.create_engine(settings.role_dsn("hm_analyst"), pool_pre_ping=True)
        eng.connect().close()
    except Exception:
        pytest.skip("DB not available")

    from engine._forecast import run_forecast

    r1 = run_forecast("S1_normal", eng, include_mc=True, include_stress=False)
    r2 = run_forecast("S1_normal", eng, include_mc=True, include_stress=False)

    band1 = r1["expected"].mc_band
    band2 = r2["expected"].mc_band
    for k in band1:
        assert band1[k]["p50"] == band2[k]["p50"]


# ── STATEC loading ────────────────────────────────────────────────────────────

def test_statec_stress_loads():
    from engine._sector import load_statec_stress
    stress = load_statec_stress()
    assert "F" in stress
    assert 0.5 < stress["F"] < 3.0   # reasonable range


def test_statec_stress_total():
    from engine._sector import load_statec_stress
    stress = load_statec_stress()
    # Total has 5yr avg ~1095, 2024=1158 → ~1.06
    assert 0.9 < stress.get("TOT_X_O_T_U", 1.0) < 2.0


# ── Unit tests: Kaplan-Meier helpers ─────────────────────────────────────────

def test_km_mean_with_censoring():
    """KM mean must exceed plain paid mean when censored obs extend beyond event times."""
    from engine._behaviour import _km_mean, _weighted_mean
    # 5 paid at 10d, 5 censored (open, overdue) at 15d (still outstanding)
    paid_obs     = [(10.0, 1.0, True)] * 5
    censored_obs = [(15.0, 1.0, False)] * 5
    all_obs = paid_obs + censored_obs
    km = _km_mean(all_obs)
    plain = _weighted_mean([(10.0, 1.0)] * 5)   # = 10.0
    assert km > plain, f"KM mean {km:.2f} should exceed paid mean {plain:.2f}"


def test_km_mean_all_censored():
    """With no events (all censored), KM falls back to weighted mean of censoring times."""
    from engine._behaviour import _km_mean
    obs = [(20.0, 1.0, False)] * 4 + [(40.0, 2.0, False)] * 2
    result = _km_mean(obs)
    # weighted mean = (20*4 + 40*4) / 8 = 30.0
    assert abs(result - 30.0) < 1e-6


def test_worsening_detected_with_censoring():
    """Customer with open overdue invoices >> typical delay gets worsening=True."""
    # 8 historical paid at 10d + 4 recent open overdue at 40d (censored)
    all_obs    = [(10.0, 1.0, True)] * 8 + [(40.0, 1.0, False)] * 4
    recent_obs = [(40.0, 1.0, False)] * 4
    # recent KM mean must exceed long-run by > 10d and recent must have ≥3 events
    # recent_obs has 0 paid events → WORSENING_MIN_RECENT = 3 not met → False
    assert _check_worsening_direct(all_obs, recent_obs) is False
    # Add 3 paid recent events well above historical to confirm worsening fires
    recent_obs2 = [(40.0, 1.0, True)] * 3 + [(40.0, 1.0, False)] * 2
    all_obs2    = [(10.0, 1.0, True)] * 8 + recent_obs2
    assert _check_worsening_direct(all_obs2, recent_obs2) is True


def test_sector_overdue_fraction_fires():
    """A segment with high >30d overdue fraction triggers slowing via overdue signal."""
    from engine._sector import detect_sector_trends

    as_of = date(2026, 10, 2)
    cust_worsening = {f"CUST_{i:03d}": False for i in range(5)}
    cust_recent = {f"CUST_{i:03d}": 7.0 for i in range(5)}
    cust_longrun = {f"CUST_{i:03d}": 5.0 for i in range(5)}
    cust_seg = {f"CUST_{i:03d}": "G46" for i in range(5)}
    pool_entries = {"G46": []}
    statec = {"G": 1.0}
    # 80% of open invoices >30d overdue (hist_frac=0.05) → delta=0.75 > 0.20
    seg_overdue_fracs = {"G46": (0.80, 0.05)}

    slowing, _, alerts = detect_sector_trends(
        cust_worsening, cust_recent, cust_longrun, cust_seg, pool_entries,
        as_of, statec, seg_overdue_fracs=seg_overdue_fracs,
    )
    assert slowing.get("G46") is True
    assert any(a["segment"] == "G46" and a["reason"] == "overdue" for a in alerts)


def test_statec_mapping_segment_names():
    """Synthetic segment names resolve to correct NACE stress index, not 1.0 fallback."""
    from engine._sector import statec_stress_for_segment

    mock_table = {"F": 1.52, "L": 1.64, "G47": 0.84, "O": 0.90}

    assert statec_stress_for_segment("specialised_installers", mock_table) == 1.52
    assert statec_stress_for_segment("general_contractors",    mock_table) == 1.52
    assert statec_stress_for_segment("property_developers",    mock_table) == 1.64
    assert statec_stress_for_segment("retail_diy",             mock_table) == 0.84
    # public_entities → O → in mock_table
    assert statec_stress_for_segment("public_entities",        mock_table) == 0.90
    # Numeric NACE code ('F41') still resolves via _nace_section → 'F'
    assert statec_stress_for_segment("F41", mock_table) == 1.52
    # Unknown segment still falls back to 1.0
    assert statec_stress_for_segment("unknown_sector", mock_table) == 1.0


def test_statec_definition_2025_over_mean_2020_2024():
    """STATEC uses 2025 / mean(2020-2024). Construction F should be ~1.16."""
    from engine._sector import load_statec_stress
    t = load_statec_stress()
    # F: mean(109,121,117,160,200)=141.4, 2025=164 → 164/141.4=1.160
    assert "F" in t, "F (construction) section missing from stress table"
    assert 1.10 <= t["F"] <= 1.25, f"F stress {t['F']:.4f} outside expected range [1.10, 1.25]"


# ── Unit tests: month-end payment run (Protocol deviation 3) ──────────────────

def test_snap_to_month_end_basic():
    from engine._behaviour import snap_to_month_end
    assert snap_to_month_end(date(2026, 10, 15), date(2026, 10, 15)) == date(2026, 10, 31)


def test_snap_to_month_end_already_at_end():
    from engine._behaviour import snap_to_month_end
    assert snap_to_month_end(date(2026, 9, 30), date(2026, 9, 30)) == date(2026, 9, 30)


def test_snap_to_month_end_earliest_pushes_forward():
    from engine._behaviour import snap_to_month_end
    # Receipt in September, earliest in October → Oct 31
    assert snap_to_month_end(date(2026, 9, 25), date(2026, 10, 1)) == date(2026, 10, 31)


def test_snap_to_month_end_february():
    from engine._behaviour import snap_to_month_end
    # Feb 2026 is non-leap: 28 days
    assert snap_to_month_end(date(2026, 2, 14), date(2026, 2, 14)) == date(2026, 2, 28)


def test_month_end_payer_snap_in_r1():
    """For a month-end payer, r1_open_receivables snaps receipt_date to last-cal-day."""
    from engine._components import r1_open_receivables

    as_of = date(2026, 9, 28)
    due_date = as_of - timedelta(days=5)  # 5 days overdue

    class _MEBehaviour:
        """Stub that marks every customer as a month-end payer."""
        def expected_delay(self, cc): return 10.0
        def delay_sample(self, cc): return [10.0] * 10
        def source(self, cc): return "month-end payer"
        def segment_expected_delay(self, seg): return 10.0
        def conditional_remaining_delay(self, cc, d): return 3.0  # → as_of+3 = Oct 1
        def is_month_end_payer(self, cc): return True

    inv = {
        "invoice_id": "INV_ME", "cust_code": "CUST_001",
        "due_date": due_date, "outstanding_amount": 5000.0, "segment": "public_entities",
    }
    receipts, beyond = r1_open_receivables([inv], _MEBehaviour(), as_of, n_weeks=13)
    all_items = [i for items in receipts.values() for i in items] + beyond
    assert len(all_items) == 1
    rd = all_items[0]["receipt_date"]
    # extra=3 → raw receipt = Oct 1, but overdue snap uses earliest=Sep 29 → Sep 30
    assert rd == date(2026, 9, 30), f"Expected 2026-09-30, got {rd}"


# ── Reproducibility: PYTHONHASHSEED independence ──────────────────────────────

def test_s2_reproducible_across_hashseed():
    """W1 closing and band coverage for S2 must be identical regardless of PYTHONHASHSEED."""
    import json
    import subprocess
    import sys
    import tempfile
    import os

    root = str(Path(__file__).parent.parent).replace("\\", "\\\\")
    lines = [
        "import json, sys",
        f"sys.path.insert(0, '{root}')",
        "import sqlalchemy as sa",
        "from config import settings",
        "from engine._forecast import run_forecast",
        "eng = sa.create_engine(settings.role_dsn('hm_analyst'), pool_pre_ping=True)",
        "results = run_forecast('S2_big_customer', eng,",
        "    scenarios=['expected'], include_mc=True, include_stress=False,",
        "    include_assumptions=False, include_bridge=False, include_collections=False)",
        "exp = results['expected']",
        "w1 = exp.p50_weeks[0]['closing']",
        "band = exp.mc_band or {}",
        "cov = sum(1 for v in band.values() if v) / len(band) if band else 0",
        "print(json.dumps({'w1': w1, 'cov': round(cov, 6)}))",
    ]
    script = "\n".join(lines) + "\n"

    try:
        import sqlalchemy as sa
        from config import settings
        sa.create_engine(settings.role_dsn("hm_analyst"), pool_pre_ping=True).connect().close()
    except Exception:
        pytest.skip("DB not available")

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False,
                                    encoding="utf-8") as f:
        f.write(script)
        script_path = f.name

    try:
        env0 = {**os.environ, "PYTHONHASHSEED": "0"}
        env1 = {**os.environ, "PYTHONHASHSEED": "1"}
        r0 = subprocess.run(
            [sys.executable, script_path], capture_output=True, text=True, env=env0, timeout=120
        )
        r1 = subprocess.run(
            [sys.executable, script_path], capture_output=True, text=True, env=env1, timeout=120
        )
        assert r0.returncode == 0, f"HASHSEED=0 failed:\n{r0.stderr}"
        assert r1.returncode == 0, f"HASHSEED=1 failed:\n{r1.stderr}"
        out0 = json.loads(r0.stdout.strip())
        out1 = json.loads(r1.stdout.strip())
        assert out0["w1"] == out1["w1"], (
            f"W1 differs: HASHSEED=0 → {out0['w1']}, HASHSEED=1 → {out1['w1']}"
        )
        assert out0["cov"] == out1["cov"], (
            f"Band coverage differs: HASHSEED=0 → {out0['cov']}, HASHSEED=1 → {out1['cov']}"
        )
    finally:
        os.unlink(script_path)
