"""Load and apply CFO overrides from hm.assumption_overrides."""
from __future__ import annotations

from datetime import date
from typing import Any

import sqlalchemy as sa
from sqlalchemy import text


def load_active_overrides(engine: sa.Engine, dataset_id: str) -> list[dict]:
    """
    Return active overrides: active=TRUE rows not superseded by any other row.

    The table is insert-only. To cancel an override, insert a new row with
    active=FALSE and supersedes=<old_id>. The query excludes any override
    that has been superseded by a newer row.
    """
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT o.override_id, o.target_type, o.target_id, o.field, o.new_value,
                   o.reason, o.created_by, o.created_at, o.supersedes
            FROM hm.assumption_overrides o
            WHERE o.dataset_id = :did
              AND o.active = TRUE
              AND NOT EXISTS (
                SELECT 1 FROM hm.assumption_overrides s
                WHERE s.dataset_id = o.dataset_id
                  AND s.supersedes = o.override_id
              )
            ORDER BY o.override_id
        """), {"did": dataset_id}).fetchall()
    return [dict(row._mapping) for row in rows]


def apply_overrides(data: dict[str, Any], overrides: list[dict]) -> dict[str, Any]:
    """
    Apply overrides to a data dict (as returned by _loader.load_dataset).
    Returns modified data dict (copies only what changes).
    Logs each applied override in data['applied_overrides'].
    """
    applied: list[dict] = []

    # Index open_ar and open_ap by invoice_id for fast lookup
    ar_by_id = {inv["invoice_id"]: inv for inv in data.get("open_ar", [])}
    ap_by_id = {inv["invoice_id"]: inv for inv in data.get("open_ap", [])}

    for ov in overrides:
        ttype = ov["target_type"]
        tid   = ov["target_id"]
        field = ov["field"]
        val   = ov["new_value"]

        if ttype == "invoice" and tid in ar_by_id:
            inv = dict(ar_by_id[tid])
            if field == "expected_date":
                inv["_override_receipt_date"] = date.fromisoformat(val)
            elif field == "amount":
                inv["outstanding_amount"] = float(val)
            ar_by_id[tid] = inv
            applied.append({**ov, "applied_to": f"ar_invoice:{tid}"})

        elif ttype == "invoice" and tid in ap_by_id:
            inv = dict(ap_by_id[tid])
            if field == "amount":
                inv["outstanding_amount"] = float(val)
            elif field == "expected_date":
                inv["_override_due_date"] = date.fromisoformat(val)
            ap_by_id[tid] = inv
            applied.append({**ov, "applied_to": f"ap_invoice:{tid}"})

        elif ttype == "customer":
            # Customer-level delay override stored in data['cust_delay_overrides']
            co = data.setdefault("cust_delay_overrides", {})
            if field == "delay_days":
                co[tid] = float(val)
            applied.append({**ov, "applied_to": f"customer:{tid}"})

        elif ttype == "parameter":
            po = data.setdefault("param_overrides", {})
            po[tid] = val
            applied.append({**ov, "applied_to": f"parameter:{tid}"})

    data["open_ar"] = list(ar_by_id.values())
    data["open_ap"] = list(ap_by_id.values())
    data["applied_overrides"] = applied
    return data


def insert_override(
    engine: sa.Engine,
    dataset_id: str,
    target_type: str,
    target_id: str,
    field: str,
    new_value: str,
    reason: str,
    created_by: str,
    supersedes: int | None = None,
) -> int:
    """Insert a new override row and return its override_id."""
    with engine.begin() as conn:
        row = conn.execute(text("""
            INSERT INTO hm.assumption_overrides
                (dataset_id, target_type, target_id, field, new_value,
                 reason, created_by, supersedes)
            VALUES (:did, :tt, :tid, :field, :val, :reason, :by, :sup)
            RETURNING override_id
        """), {
            "did": dataset_id, "tt": target_type, "tid": target_id,
            "field": field, "val": str(new_value), "reason": reason,
            "by": created_by, "sup": supersedes,
        }).fetchone()
    return row.override_id


def supersede_override(
    engine: sa.Engine,
    dataset_id: str,
    old_override_id: int,
    reason: str,
    created_by: str,
) -> int:
    """
    Cancel an override by inserting a new row with active=FALSE and supersedes=old_id.
    The old row is never modified (insert-only table). The new cancellation row
    causes load_active_overrides to exclude the old row.
    Returns the new (cancellation) override_id.
    """
    with engine.begin() as conn:
        old = conn.execute(text("""
            SELECT target_type, target_id, field, new_value
            FROM hm.assumption_overrides
            WHERE override_id = :oid
        """), {"oid": old_override_id}).fetchone()
        if old is None:
            raise ValueError(f"Override {old_override_id} not found")

        row = conn.execute(text("""
            INSERT INTO hm.assumption_overrides
                (dataset_id, target_type, target_id, field, new_value,
                 reason, created_by, active, supersedes)
            VALUES (:did, :tt, :tid, :field, :val, :reason, :by, FALSE, :sup)
            RETURNING override_id
        """), {
            "did": dataset_id,
            "tt": old.target_type, "tid": old.target_id,
            "field": old.field, "val": old.new_value,
            "reason": reason, "by": created_by, "sup": old_override_id,
        }).fetchone()
    return row.override_id
