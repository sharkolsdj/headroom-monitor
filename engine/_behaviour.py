"""Payment behaviour models: SimpleBehaviour (Phase 2) and RecencyBehaviour (Phase 3)."""
from __future__ import annotations

import math
import random
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
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


# ── RecencyBehaviour ──────────────────────────────────────────────────────────

_BOOTSTRAP_N = 500
_BOOTSTRAP_SEED = 0


def _weighted_mean(pairs: list[tuple[float, float]]) -> float:
    """Weighted mean of (value, weight) pairs. Returns 0.0 if empty."""
    tw = sum(w for _, w in pairs)
    if tw <= 0:
        return 0.0
    return sum(v * w for v, w in pairs) / tw


def _weighted_median(pairs: list[tuple[float, float]]) -> float:
    """Weighted median of (value, weight) pairs. Returns 0.0 if empty."""
    if not pairs:
        return 0.0
    sorted_pairs = sorted(pairs, key=lambda x: x[0])
    total_w = sum(w for _, w in sorted_pairs)
    half = total_w / 2.0
    cumulative = 0.0
    for v, w in sorted_pairs:
        cumulative += w
        if cumulative >= half:
            return v
    return sorted_pairs[-1][0]


class RecencyBehaviour:
    """
    Recency-weighted payment behaviour (Phase 3).

    Half-life 60 days: weight = 2^(-age_days / 60).
    Look-back window: 12 months.
    Worsening: recent-90d weighted mean >= long-run mean + 10d
               AND >= 3 recent invoices AND diff > 2 SE.
    Source: 'customer' (>=5 own invoices) / 'segment trend' (slowing segment,
            <3 recent invoices) / 'segment' (otherwise falls back to pool).
    """

    HALF_LIFE = 60.0
    MIN_CUSTOMER_INVOICES = 5
    MIN_POOL_INVOICES = 5
    RECENT_WINDOW = 90
    WORSENING_THRESHOLD = 10.0
    WORSENING_MIN_RECENT = 3
    WORSENING_SE_FACTOR = 2.0
    TYPICAL_SLOW_DAYS = 20.0   # threshold for 'slow'/'chronic' label

    def __init__(
        self,
        sa_engine: sa.Engine,
        dataset_id: str,
        as_of: date,
        sector_slowing: dict[str, bool] | None = None,
        sector_shift: dict[str, float] | None = None,
    ) -> None:
        self._as_of = as_of
        self._sector_slowing: dict[str, bool] = sector_slowing or {}
        self._sector_shift: dict[str, float] = sector_shift or {}

        # Raw weighted pairs (delay, weight) per customer and per segment pool
        self._raw_w: dict[str, list[tuple[float, float]]] = {}
        self._seg_pools_w: dict[str, list[tuple[float, float]]] = defaultdict(list)
        # Pool entries with receipt dates for sector trend detection
        self._seg_pool_entries: dict[str, list[tuple[float, date]]] = defaultdict(list)

        self._cust_seg: dict[str, str] = {}
        self._sources: dict[str, str] = {}
        self._worsening: dict[str, bool] = {}
        self._recent_count: dict[str, int] = {}
        self._recent_mean: dict[str, float] = {}
        self._longrun_mean: dict[str, float] = {}

        # Pre-bootstrapped delay lists for MC (delay_sample return value)
        self._bootstrap: dict[str, list[float]] = {}

        # Partial payment stats: (p_partial, split_ratio, gap_days) per cust
        self._partial_p: dict[str, float] = {}
        self._partial_ratio: dict[str, float] = {}
        self._partial_gap: dict[str, float] = {}

        self._load(sa_engine, dataset_id, as_of)

    # ── Internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _weight(age_days: float, half_life: float = HALF_LIFE) -> float:
        return 2.0 ** (-age_days / half_life)

    def _load(self, sa_engine: sa.Engine, dataset_id: str, as_of: date) -> None:
        history_start = as_of - timedelta(days=365)
        recent_cutoff = as_of - timedelta(days=self.RECENT_WINDOW)

        with sa_engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT
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

        # Per-customer raw entries: (delay, weight, receipt_date, is_recent)
        cust_entries: dict[str, list[tuple[float, float, date, bool]]] = defaultdict(list)

        for row in rows:
            if row.last_receipt_date is None:
                continue
            delay = float((row.last_receipt_date - row.due_date).days)
            age_days = (as_of - row.last_receipt_date).days
            w = self._weight(float(age_days))
            is_recent = row.last_receipt_date >= recent_cutoff
            cust_entries[row.cust_code].append((delay, w, row.last_receipt_date, is_recent))
            self._seg_pools_w[row.segment].append((delay, w))
            self._seg_pool_entries[row.segment].append((delay, row.last_receipt_date))
            self._cust_seg[row.cust_code] = row.segment

        bsrng = random.Random(_BOOTSTRAP_SEED)

        for cust_code, entries in cust_entries.items():
            seg = self._cust_seg.get(cust_code, "")
            delays_w = [(d, w) for d, w, _, _ in entries]

            recent_ent = [(d, w) for d, w, _, is_r in entries if is_r]
            self._recent_count[cust_code] = len(recent_ent)

            lr_mean = _weighted_mean(delays_w)
            self._longrun_mean[cust_code] = lr_mean

            if recent_ent:
                self._recent_mean[cust_code] = _weighted_mean(recent_ent)
            else:
                self._recent_mean[cust_code] = lr_mean

            self._worsening[cust_code] = self._check_worsening(delays_w, recent_ent)

            if len(entries) >= self.MIN_CUSTOMER_INVOICES:
                self._raw_w[cust_code] = delays_w
                self._sources[cust_code] = "customer"
                sample_w = delays_w
            else:
                pool_w = list(self._seg_pools_w.get(seg, []))
                self._raw_w[cust_code] = pool_w
                # Source is tentatively "segment"; updated to "segment trend" below
                self._sources[cust_code] = "segment"
                sample_w = pool_w

            # Sector-shift adjustment for customers in slowing segments with < 3 recent invoices
            shift = 0.0
            if self._sector_slowing.get(seg, False) and self._recent_count.get(cust_code, 0) < 3:
                self._sources[cust_code] = "segment trend"
                shift = self._sector_shift.get(seg, 0.0)

            # Bootstrap the delay list (adds sector shift where applicable)
            if sample_w:
                delays_list = [d + shift for d, _ in sample_w]
                weights_list = [w for _, w in sample_w]
                bootstrap = bsrng.choices(delays_list, weights=weights_list, k=_BOOTSTRAP_N)
            else:
                bootstrap = []
            self._bootstrap[cust_code] = bootstrap

        # Customers in cust_seg but without any paid history → segment pool only
        # (handled lazily in delay_sample / expected_delay)

        self._load_partial(sa_engine, dataset_id, as_of, history_start)

    def _load_partial(
        self, sa_engine: sa.Engine, dataset_id: str, as_of: date, history_start: date
    ) -> None:
        """Load partial-payment probability, split ratio, and gap per customer."""
        with sa_engine.connect() as conn:
            rows = conn.execute(text("""
                WITH paid AS (
                    SELECT i.invoice_id, i.cust_code, c.segment, i.amount_gross
                    FROM hm.ar_invoices i
                    JOIN hm.counterparties c
                        ON c.code = i.cust_code AND c.dataset_id = i.dataset_id
                    LEFT JOIN hm.ar_receipts r
                        ON r.invoice_id = i.invoice_id AND r.dataset_id = i.dataset_id
                    WHERE i.dataset_id = :did
                      AND i.issue_date >= :hist_start
                      AND i.issue_date <= :as_of
                    GROUP BY i.invoice_id, i.cust_code, c.segment, i.amount_gross
                    HAVING COALESCE(SUM(r.amount), 0.0) >= i.amount_gross * 0.99
                ),
                rcounts AS (
                    SELECT invoice_id,
                           COUNT(*)                         AS n_rec,
                           (MAX(date) - MIN(date))          AS gap_days,
                           MIN(amount) / NULLIF(SUM(amount), 0) AS first_ratio
                    FROM hm.ar_receipts
                    WHERE dataset_id = :did
                    GROUP BY invoice_id
                )
                SELECT
                    p.cust_code,
                    p.segment,
                    COUNT(*)                                             AS n_total,
                    SUM(CASE WHEN rc.n_rec > 1 THEN 1 ELSE 0 END)       AS n_partial,
                    AVG(CASE WHEN rc.n_rec > 1 THEN rc.gap_days  END)   AS avg_gap,
                    AVG(CASE WHEN rc.n_rec > 1 THEN rc.first_ratio END) AS avg_ratio
                FROM paid p
                LEFT JOIN rcounts rc ON rc.invoice_id = p.invoice_id
                GROUP BY p.cust_code, p.segment
            """), {"did": dataset_id, "hist_start": history_start, "as_of": as_of}).fetchall()

        # Accumulate segment pool stats for fallback
        seg_n_total: dict[str, float] = defaultdict(float)
        seg_n_partial: dict[str, float] = defaultdict(float)
        seg_gap: dict[str, list[float]] = defaultdict(list)
        seg_ratio: dict[str, list[float]] = defaultdict(list)

        for row in rows:
            n_tot = float(row.n_total or 0)
            n_par = float(row.n_partial or 0)
            seg = row.segment or ""
            seg_n_total[seg] += n_tot
            seg_n_partial[seg] += n_par
            if row.avg_gap is not None:
                seg_gap[seg].append(float(row.avg_gap))
            if row.avg_ratio is not None:
                seg_ratio[seg].append(float(row.avg_ratio))

        for row in rows:
            cust = row.cust_code
            seg = row.segment or ""
            n_tot = float(row.n_total or 0)
            n_par = float(row.n_partial or 0)

            if n_tot >= self.MIN_CUSTOMER_INVOICES:
                p = n_par / n_tot
                gap = float(row.avg_gap) if row.avg_gap is not None else 14.0
                ratio = float(row.avg_ratio) if row.avg_ratio is not None else 0.5
            else:
                # Segment pool fallback
                snt = seg_n_total.get(seg, 0.0)
                snp = seg_n_partial.get(seg, 0.0)
                p = (snp / snt) if snt > 0 else 0.0
                g_vals = seg_gap.get(seg, [])
                r_vals = seg_ratio.get(seg, [])
                gap = (sum(g_vals) / len(g_vals)) if g_vals else 14.0
                ratio = (sum(r_vals) / len(r_vals)) if r_vals else 0.5

            self._partial_p[cust] = min(1.0, max(0.0, p))
            self._partial_ratio[cust] = min(0.95, max(0.05, ratio))
            self._partial_gap[cust] = max(1.0, gap)

    def _check_worsening(
        self,
        all_pairs: list[tuple[float, float]],
        recent_pairs: list[tuple[float, float]],
    ) -> bool:
        if len(recent_pairs) < self.WORSENING_MIN_RECENT:
            return False
        lr_mean = _weighted_mean(all_pairs)
        r_mean = _weighted_mean(recent_pairs)
        diff = r_mean - lr_mean
        if diff < self.WORSENING_THRESHOLD:
            return False
        # Weighted variance of recent delays → SE
        r_tw = sum(w for _, w in recent_pairs)
        if r_tw <= 0:
            return False
        variance = sum(w * (d - r_mean) ** 2 for d, w in recent_pairs) / r_tw
        n_r = len(recent_pairs)
        if n_r < 2:
            return True
        se = math.sqrt(variance / n_r)
        return diff > self.WORSENING_SE_FACTOR * se if se > 0 else True

    # ── PaymentBehaviourModel protocol ────────────────────────────────────────

    def expected_delay(self, cust_code: str) -> float:
        """Recency-weighted mean delay. Falls back to segment pool."""
        pairs = self._raw_w.get(cust_code)
        if pairs:
            return _weighted_mean(pairs)
        seg = self._cust_seg.get(cust_code, "")
        pool = self._seg_pools_w.get(seg, [])
        return _weighted_mean(pool) if pool else 0.0

    def delay_sample(self, cust_code: str) -> list[float]:
        """Pre-bootstrapped weighted sample for MC rng.choice() calls."""
        bootstrap = self._bootstrap.get(cust_code)
        if bootstrap is not None:
            return list(bootstrap)
        # Fallback: segment pool bootstrap
        seg = self._cust_seg.get(cust_code, "")
        pool_w = self._seg_pools_w.get(seg, [])
        if not pool_w:
            return []
        bsrng = random.Random(_BOOTSTRAP_SEED)
        d_list = [d for d, _ in pool_w]
        w_list = [w for _, w in pool_w]
        return bsrng.choices(d_list, weights=w_list, k=_BOOTSTRAP_N)

    def source(self, cust_code: str) -> str:
        return self._sources.get(cust_code, "segment")

    def segment_expected_delay(self, segment: str) -> float:
        pool = self._seg_pools_w.get(segment, [])
        return _weighted_mean(pool) if pool else 0.0

    def conditional_remaining_delay(self, cust_code: str, d: float) -> float:
        """Mean of (bootstrap_delay − d) for bootstrap delays > d. Min 5, else pool."""
        sample = self._bootstrap.get(cust_code, [])
        qualifying = [x - d for x in sample if x > d]
        if len(qualifying) >= self.MIN_CUSTOMER_INVOICES:
            return max(1.0, sum(qualifying) / len(qualifying))
        seg = self._cust_seg.get(cust_code, "")
        pool_w = self._seg_pools_w.get(seg, [])
        if not pool_w:
            return 1.0
        bsrng = random.Random(_BOOTSTRAP_SEED)
        pool_bootstrap = bsrng.choices(
            [v for v, _ in pool_w], weights=[w for _, w in pool_w], k=_BOOTSTRAP_N
        )
        pool_q = [x - d for x in pool_bootstrap if x > d]
        if len(pool_q) >= self.MIN_POOL_INVOICES:
            return max(1.0, sum(pool_q) / len(pool_q))
        return 1.0

    # ── Phase 3 extras (not in protocol) ─────────────────────────────────────

    def typical_delay(self, cust_code: str) -> float:
        """Weighted median delay. Used for display (customers.json)."""
        pairs = self._raw_w.get(cust_code)
        if pairs:
            return _weighted_median(pairs)
        seg = self._cust_seg.get(cust_code, "")
        pool = self._seg_pools_w.get(seg, [])
        return _weighted_median(pool) if pool else 0.0

    def recent_delay(self, cust_code: str) -> float:
        """Weighted mean of last-90-day delays (or long-run mean if no recent data)."""
        return self._recent_mean.get(cust_code, self.expected_delay(cust_code))

    def is_worsening(self, cust_code: str) -> bool:
        return self._worsening.get(cust_code, False)

    def trend_label(self, cust_code: str) -> str:
        """'worsening' / 'stable' (improving is not detected in Phase 3)."""
        return "worsening" if self.is_worsening(cust_code) else "stable"

    def is_slow(self, cust_code: str) -> bool:
        """Typical delay >= 20 days (used for reminder rule)."""
        return self.typical_delay(cust_code) >= self.TYPICAL_SLOW_DAYS

    @property
    def seg_pool_entries(self) -> dict[str, list[tuple[float, date]]]:
        """Expose raw (delay, receipt_date) pairs per segment for sector detection."""
        return dict(self._seg_pool_entries)

    @property
    def cust_worsening(self) -> dict[str, bool]:
        return dict(self._worsening)

    @property
    def cust_recent_mean(self) -> dict[str, float]:
        return dict(self._recent_mean)

    @property
    def cust_longrun_mean(self) -> dict[str, float]:
        return dict(self._longrun_mean)

    @property
    def cust_seg(self) -> dict[str, str]:
        return dict(self._cust_seg)

    def all_customer_sources(self) -> dict[str, tuple[float, str]]:
        """Return {cust_code: (expected_delay, source)} for all known customers."""
        result: dict[str, tuple[float, str]] = {}
        for code in set(self._raw_w) | set(self._cust_seg):
            result[code] = (self.expected_delay(code), self.source(code))
        return result

    def get_partial_stats(self, cust_code: str) -> tuple[float, float, float]:
        """Return (p_partial, split_ratio, gap_days) for a customer. Defaults if unknown."""
        return (
            self._partial_p.get(cust_code, 0.0),
            self._partial_ratio.get(cust_code, 0.5),
            self._partial_gap.get(cust_code, 14.0),
        )
