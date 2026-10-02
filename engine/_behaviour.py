"""Payment behaviour model (Phase 2: simple average of last-12-months delays)."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Protocol, runtime_checkable

import sqlalchemy as sa
from sqlalchemy import text


@runtime_checkable
class PaymentBehaviourModel(Protocol):
    def expected_delay(self, cust_code: str) -> float: ...
    def delay_sample(self, cust_code: str) -> list[float]: ...
    def source(self, cust_code: str) -> str: ...          # "customer" | "segment"
    def segment_expected_delay(self, segment: str) -> float: ...
    def conditional_remaining_delay(self, cust_code: str, d: float) -> float: ...


class SimpleBehaviour:
    """
    Use paid invoices from the last 12 months.
    If fewer than 5 paid invoices for a customer: use the segment pool (source='segment').
    """

    MIN_CUSTOMER_INVOICES = 5

    def __init__(self, sa_engine: sa.Engine, dataset_id: str, as_of: date) -> None:
        self._delays: dict[str, list[float]] = {}
        self._sources: dict[str, str] = {}
        self._seg_pools: dict[str, list[float]] = defaultdict(list)
        self._cust_seg: dict[str, str] = {}
        self._load(sa_engine, dataset_id, as_of)

    def _load(self, sa_engine: sa.Engine, dataset_id: str, as_of: date) -> None:
        history_start = as_of - timedelta(days=365)
        with sa_engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT
                    i.invoice_id,
                    i.cust_code,
                    i.due_date,
                    c.segment,
                    i.amount_gross,
                    COALESCE(SUM(r.amount), 0.0)  AS paid_amount,
                    MAX(r.date)                    AS last_receipt_date
                FROM hm.ar_invoices i
                JOIN hm.counterparties c
                    ON c.code = i.cust_code AND c.dataset_id = i.dataset_id
                LEFT JOIN hm.ar_receipts r
                    ON r.invoice_id = i.invoice_id AND r.dataset_id = i.dataset_id
                WHERE i.dataset_id  = :did
                  AND i.issue_date >= :hist_start
                  AND i.issue_date <= :as_of
                GROUP BY i.invoice_id, i.cust_code, i.due_date, c.segment, i.amount_gross
                HAVING COALESCE(SUM(r.amount), 0.0) >= i.amount_gross * 0.99
            """), {"did": dataset_id, "hist_start": history_start, "as_of": as_of}).fetchall()

        cust_raw: dict[str, list[float]] = defaultdict(list)
        for row in rows:
            if row.last_receipt_date is None:
                continue
            delay = float((row.last_receipt_date - row.due_date).days)
            cust_raw[row.cust_code].append(delay)
            self._seg_pools[row.segment].append(delay)
            self._cust_seg[row.cust_code] = row.segment

        for cust_code, delays in cust_raw.items():
            seg = self._cust_seg.get(cust_code, "")
            if len(delays) >= self.MIN_CUSTOMER_INVOICES:
                self._delays[cust_code] = delays
                self._sources[cust_code] = "customer"
            else:
                pool = list(self._seg_pools.get(seg, []))
                self._delays[cust_code] = pool
                self._sources[cust_code] = "segment"

    def expected_delay(self, cust_code: str) -> float:
        sample = self._delays.get(cust_code)
        if sample:
            return sum(sample) / len(sample)
        seg = self._cust_seg.get(cust_code, "")
        pool = self._seg_pools.get(seg, [])
        if pool:
            return sum(pool) / len(pool)
        return 0.0

    def delay_sample(self, cust_code: str) -> list[float]:
        sample = self._delays.get(cust_code)
        if sample is not None:
            return list(sample)
        seg = self._cust_seg.get(cust_code, "")
        return list(self._seg_pools.get(seg, []))

    def source(self, cust_code: str) -> str:
        return self._sources.get(cust_code, "segment")

    def segment_expected_delay(self, segment: str) -> float:
        pool = self._seg_pools.get(segment, [])
        if pool:
            return sum(pool) / len(pool)
        return 0.0

    def conditional_remaining_delay(self, cust_code: str, d: float) -> float:
        """
        Mean of (past_delay − d) for past delays that exceeded d days.
        Falls back to segment pool when the customer has fewer than
        MIN_CUSTOMER_INVOICES qualifying observations. Returns minimum 1.0 day.
        """
        sample = self._delays.get(cust_code, [])
        qualifying = [x - d for x in sample if x > d]
        if len(qualifying) >= self.MIN_CUSTOMER_INVOICES:
            return max(1.0, sum(qualifying) / len(qualifying))
        seg = self._cust_seg.get(cust_code, "")
        pool = self._seg_pools.get(seg, [])
        pool_qualifying = [x - d for x in pool if x > d]
        if len(pool_qualifying) >= self.MIN_CUSTOMER_INVOICES:
            return max(1.0, sum(pool_qualifying) / len(pool_qualifying))
        return 1.0

    def all_customer_sources(self) -> dict[str, tuple[float, str]]:
        """Return {cust_code: (expected_delay, source)} for all known customers."""
        result: dict[str, tuple[float, str]] = {}
        all_codes = set(self._delays) | set(self._cust_seg)
        for code in all_codes:
            result[code] = (self.expected_delay(code), self.source(code))
        return result
