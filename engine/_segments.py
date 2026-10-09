"""Customer-group (segment) summary for the customer ledger.

Shows the CFO whether a slow payer is an isolated case or part of a group that is
slowing down. Pure aggregation of the per-customer figures already produced by the
engine (customers.json); no new estimation.
"""
from __future__ import annotations

from collections import defaultdict

# A customer counts as "paying later than usual" when its delay over the last 90 days
# exceeds its usual delay by at least this many days. Same 7-day gap as the sector
# slowdown detector (engine/_sector.py, _SLOWING_DELAY_DIFF).
LATER_THAN_USUAL_DAYS = 7.0
# The group is flagged as slowing when at least this share of its compared customers is
# paying later than usual. Same 25% as the sector slowdown detector (_SLOWING_FRAC).
SLOWING_SHARE = 0.25


def summarize_segments(customers: list[dict]) -> dict[str, dict]:
    """Return {segment: {n_customers, n_compared, n_later, slowing, overdue_eur, owed_eur, ranked, later}}.

    ranked: customer codes ordered by how much later they pay now than usual (largest
    increase first; customers that cannot be compared last, by overdue amount).
    later: codes of the customers counted in n_later.

    customers: records as written to customers.json (keys: segment, typical_delay_days,
    recent_delay_days, overdue_amount, total_owed, source).
    Customers whose delay comes from the group average (source == 'segment') are not
    compared, because they have no usual delay of their own.
    """
    out: dict[str, dict] = defaultdict(
        lambda: {"n_customers": 0, "n_compared": 0, "n_later": 0, "overdue_eur": 0.0, "owed_eur": 0.0,
                 "_keys": [], "later": []}
    )
    for c in customers:
        s = out[c["segment"]]
        s["n_customers"] += 1
        s["overdue_eur"] += float(c.get("overdue_amount") or 0.0)
        s["owed_eur"] += float(c.get("total_owed") or 0.0)
        typ, rec = c.get("typical_delay_days"), c.get("recent_delay_days")
        od = float(c.get("overdue_amount") or 0.0)
        code = c.get("cust_code", "")
        if c.get("source") == "segment" or typ is None or rec is None:
            s["_keys"].append((1, 0.0, -od, code))
            continue
        s["n_compared"] += 1
        s["_keys"].append((0, -(rec - typ), -od, code))
        if rec - typ >= LATER_THAN_USUAL_DAYS:
            s["n_later"] += 1
            s["later"].append(code)
    result = {}
    for k, v in out.items():
        keys = v.pop("_keys")
        result[k] = {**v, "slowing": v["n_compared"] > 0 and v["n_later"] >= SLOWING_SHARE * v["n_compared"],
                     "overdue_eur": round(v["overdue_eur"], 2), "owed_eur": round(v["owed_eur"], 2),
                     "ranked": [code for *_, code in sorted(keys)]}
    return result
