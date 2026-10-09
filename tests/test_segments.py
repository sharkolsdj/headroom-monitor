"""Customer-group summary used by the demo's customer ledger (engine/_segments.py)."""
from engine._segments import LATER_THAN_USUAL_DAYS, summarize_segments


def _c(seg, typ, rec, od=0.0, owed=0.0, src="customer"):
    return {"segment": seg, "typical_delay_days": typ, "recent_delay_days": rec,
            "overdue_amount": od, "total_owed": owed, "source": src}


def test_counts_and_totals():
    rows = [
        _c("a", 10, 10 + LATER_THAN_USUAL_DAYS, od=100, owed=300),  # exactly at threshold: later
        _c("a", 10, 16, od=50, owed=50),                             # 6 days later: not counted
        _c("a", 10, None, od=0, owed=20),                            # no recent delay: not compared
        _c("a", 30, 60, src="segment"),                              # group average: not compared
        _c("b", 5, 40, od=10.567, owed=10.567),
    ]
    s = summarize_segments(rows)
    assert s["a"] == {"n_customers": 4, "n_compared": 2, "n_later": 1, "slowing": True, "overdue_eur": 150.0, "owed_eur": 370.0}
    assert s["b"]["n_later"] == 1 and s["b"]["overdue_eur"] == 10.57


def test_empty():
    assert summarize_segments([]) == {}


def test_slowing_flag_needs_a_quarter_of_the_group():
    rows = [_c("g", 10, 30)] + [_c("g", 10, 10) for _ in range(4)]   # 1 of 5 = 20%
    assert summarize_segments(rows)["g"]["slowing"] is False
    rows.append(_c("g", 10, 30))                                     # 2 of 6 = 33%
    assert summarize_segments(rows)["g"]["slowing"] is True
