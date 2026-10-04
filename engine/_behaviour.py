"""Payment behaviour models: SimpleBehaviour (Phase 2) and RecencyBehaviour (Phase 3)."""
from __future__ import annotations

import calendar as _calendar
import math
import random
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Protocol, runtime_checkable

import sqlalchemy as sa
from sqlalchemy import text

# ── Kaplan-Meier helpers for right-censored delay estimation ──────────────────

_KM_TMAX = 365.0   # integration horizon for KM mean (days)


def _km_mean(
    obs: list[tuple[float, float, bool]],
    tmax: float = _KM_TMAX,
) -> float:
    """
    Recency-weighted Kaplan-Meier expected delay.
    obs: (delay, weight, is_event) — delay can be negative (early payment),
         is_event=False for right-censored observations (open overdue invoices).
    tmax: integration cap for open right tail.
    """
    if not obs:
        return 0.0
    events = [(d, w) for d, w, e in obs if e]
    if not events:
        tw = sum(w for _, w, _ in obs)
        return sum(d * w for d, w, _ in obs) / tw if tw > 0 else 0.0

    t_min = min(d for d, _, _ in obs)
    shifted = [(d - t_min, w, e) for d, w, e in obs]
    t_cap = min(tmax - t_min, max(d for d, _, _ in shifted))

    event_times = sorted(set(d for d, w, e in shifted if e))

    S = 1.0
    prev = 0.0
    km_mean = 0.0

    for t in event_times:
        if t > t_cap:
            break
        km_mean += S * (t - prev)
        at_risk = sum(w for d, w, _ in shifted if d >= t)
        evts = sum(w for d, w, e in shifted if e and d == t)
        if at_risk > 0:
            S *= 1.0 - evts / at_risk
        prev = t

    km_mean += S * (t_cap - prev)
    return km_mean + t_min


def _km_conditional_mean(
    obs: list[tuple[float, float, bool]],
    d: float,
) -> float:
    """
    E[T − d | T > d] from KM: expected remaining delay given d days already overdue.
    Returns at least 1.0.
    """
    cond: list[tuple[float, float, bool]] = []
    for delay, w, is_event in obs:
        if is_event and delay > d:
            cond.append((delay - d, w, True))
        elif not is_event and delay >= d:
            cond.append((delay - d, w, False))
    return max(1.0, _km_mean(cond)) if cond else 1.0


def _km_sample(
    obs: list[tuple[float, float, bool]],
    n: int,
    rng: random.Random,
) -> list[float]:
    """Sample n delays from the weighted KM empirical distribution."""
    if not obs:
        return []
    events = [(d, w) for d, w, e in obs if e]
    if not events:
        delays = [d for d, _, _ in obs]
        weights = [w for _, w, _ in obs]
        return rng.choices(delays, weights=weights, k=n)

    t_min = min(d for d, _, _ in obs)
    shifted = [(d - t_min, w, e) for d, w, e in obs]
    t_max_s = max(d for d, _, _ in shifted)
    event_times = sorted(set(d for d, w, e in shifted if e))

    S = 1.0
    steps: list[tuple[float, float]] = []  # (time_shifted, mass)
    for t in event_times:
        at_risk = sum(w for d, w, _ in shifted if d >= t)
        evts = sum(w for d, w, e in shifted if e and d == t)
        if at_risk > 0:
            h = evts / at_risk
            steps.append((t, S * h))
            S *= 1.0 - h

    if S > 0:
        steps.append((t_max_s, S))

    if not steps:
        return [t_min] * n

    times = [t + t_min for t, _ in steps]
    masses = [m for _, m in steps]
    total = sum(masses)
    if total <= 0:
        return [t_min] * n
    masses = [m / total for m in masses]
    return rng.choices(times, weights=masses, k=n)


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
# Overdue-fraction thresholds for sector slowing signal (new 2026-10-04; validated by Phase 3.4)
OVERDUE_30_DELTA_THRESHOLD = 0.20   # 20pp increase in >30d overdue fraction vs history
OVERDUE_30_ABS_THRESHOLD   = 0.50   # 50% of current open invoices are >30d overdue

# Month-end payment run (Protocol deviation 3, 2026-10-04)
_ME_PAYER_MIN_OBS  = 5
_ME_PAYER_THRESHOLD = 0.80


def _last_cal_day_of(d: date) -> date:
    """Last calendar day of the month containing d."""
    return date(d.year, d.month, _calendar.monthrange(d.year, d.month)[1])


def snap_to_month_end(receipt_date: date, earliest: date) -> date:
    """
    Return the last-calendar-day-of-month of the month containing `earliest`.
    This is always >= earliest, and matches the generator's _next_month_end().
    receipt_date is retained for call-site clarity but does not affect the result;
    callers control the target by choosing earliest appropriately:
      - not-yet-due: earliest = receipt_date (snap to month-end of that month)
      - overdue:     earliest = as_of + 1  (snap to current month's last-cal-day)
    """
    return _last_cal_day_of(earliest)


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

        # KM observations (delay, weight, is_event) per customer and per segment pool
        self._raw_obs: dict[str, list[tuple[float, float, bool]]] = {}
        # Paid-only weighted pairs retained for typical_delay (display median)
        self._raw_w: dict[str, list[tuple[float, float]]] = {}
        self._seg_pool_obs: dict[str, list[tuple[float, float, bool]]] = defaultdict(list)
        self._seg_pools_w: dict[str, list[tuple[float, float]]] = defaultdict(list)
        # Pool entries with receipt dates for sector trend detection
        self._seg_pool_entries: dict[str, list[tuple[float, date]]] = defaultdict(list)
        # Overdue >30d fractions: {seg: (current_frac, hist_frac)}
        self._seg_overdue_frac: dict[str, tuple[float, float]] = {}

        self._cust_seg: dict[str, str] = {}
        self._sources: dict[str, str] = {}
        self._worsening: dict[str, bool] = {}
        self._recent_count: dict[str, int] = {}
        self._recent_mean: dict[str, float] = {}
        self._longrun_mean: dict[str, float] = {}

        # Pre-bootstrapped delay lists for MC (delay_sample return value)
        self._bootstrap: dict[str, list[float]] = {}

        # Month-end payer / segment sets (Protocol deviation 3)
        self._me_payers: set[str] = set()
        self._me_segments: set[str] = set()

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

        params = {"did": dataset_id, "hist_start": history_start, "as_of": as_of}

        with sa_engine.connect() as conn:
            # ── Paid invoices (events) ────────────────────────────────────────
            paid_rows = conn.execute(text("""
                SELECT
                    i.cust_code,
                    i.due_date,
                    i.issue_date,
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
                GROUP BY i.invoice_id, i.cust_code, i.due_date, i.issue_date, c.segment, i.amount_gross
                HAVING COALESCE(SUM(r.amount), 0.0) >= i.amount_gross * 0.99
                ORDER BY i.invoice_id
            """), params).fetchall()

            # ── Open overdue invoices (right-censored observations) ───────────
            open_rows = conn.execute(text("""
                SELECT
                    i.cust_code,
                    i.due_date,
                    i.issue_date,
                    c.segment,
                    i.amount_gross,
                    COALESCE(SUM(r.amount), 0.0)  AS paid_so_far
                FROM hm.ar_invoices i
                JOIN hm.counterparties c
                    ON c.code = i.cust_code AND c.dataset_id = i.dataset_id
                LEFT JOIN hm.ar_receipts r
                    ON r.invoice_id = i.invoice_id AND r.dataset_id = i.dataset_id
                WHERE i.dataset_id  = :did
                  AND i.issue_date >= :hist_start
                  AND i.issue_date <= :as_of
                  AND i.due_date    < :as_of
                GROUP BY i.invoice_id, i.cust_code, i.due_date, i.issue_date, c.segment, i.amount_gross
                HAVING COALESCE(SUM(r.amount), 0.0) < i.amount_gross * 0.99
                ORDER BY i.invoice_id
            """), params).fetchall()

        # Per-customer KM entries: (delay, weight, is_event, is_recent)
        # Segment counters for overdue fraction
        seg_open_cnt:    dict[str, int] = defaultdict(int)
        seg_over30_cnt:  dict[str, int] = defaultdict(int)
        seg_hist_cnt:    dict[str, int] = defaultdict(int)
        seg_hist_late30: dict[str, int] = defaultdict(int)

        # entries: (delay, weight, is_event, is_recent)
        cust_entries: dict[str, list[tuple[float, float, bool, bool]]] = defaultdict(list)
        # Receipt dates for month-end payer detection
        cust_receipt_dates: dict[str, list[date]] = defaultdict(list)
        seg_receipt_dates: dict[str, list[date]] = defaultdict(list)

        for row in paid_rows:
            if row.last_receipt_date is None:
                continue
            delay = float((row.last_receipt_date - row.due_date).days)
            age_days = (as_of - row.last_receipt_date).days
            w = self._weight(float(age_days))
            is_recent = row.last_receipt_date >= recent_cutoff
            cust_entries[row.cust_code].append((delay, w, True, is_recent))
            self._seg_pools_w[row.segment].append((delay, w))
            self._seg_pool_entries[row.segment].append((delay, row.last_receipt_date))
            self._seg_pool_obs[row.segment].append((delay, w, True))
            self._cust_seg[row.cust_code] = row.segment
            cust_receipt_dates[row.cust_code].append(row.last_receipt_date)
            seg_receipt_dates[row.segment].append(row.last_receipt_date)
            # Overdue-fraction: historical
            seg_hist_cnt[row.segment] += 1
            if delay > 30:
                seg_hist_late30[row.segment] += 1

        for row in open_rows:
            od = float((as_of - row.due_date).days)
            if od <= 0:
                continue
            # Weight based on issue_date age (we're observing this as of today)
            age_days = (as_of - row.issue_date).days
            w = self._weight(float(age_days))
            is_recent = row.issue_date >= recent_cutoff
            cust_entries[row.cust_code].append((od, w, False, is_recent))
            self._seg_pool_obs[row.segment].append((od, w, False))
            # Include in seg_pool_entries with issue_date as date proxy
            self._seg_pool_entries[row.segment].append((od, row.issue_date))
            self._cust_seg[row.cust_code] = row.segment
            # Overdue-fraction: current
            seg_open_cnt[row.segment] += 1
            if od > 30:
                seg_over30_cnt[row.segment] += 1

        # Compute per-segment overdue fractions
        all_segs = set(seg_hist_cnt) | set(seg_open_cnt)
        for seg in all_segs:
            h = seg_hist_cnt.get(seg, 0)
            hist_frac = seg_hist_late30.get(seg, 0) / h if h > 0 else 0.0
            o = seg_open_cnt.get(seg, 0)
            curr_frac = seg_over30_cnt.get(seg, 0) / o if o > 0 else 0.0
            self._seg_overdue_frac[seg] = (curr_frac, hist_frac)

        bsrng = random.Random(_BOOTSTRAP_SEED)

        for cust_code, entries in cust_entries.items():
            seg = self._cust_seg.get(cust_code, "")
            all_obs  = [(d, w, e) for d, w, e, _ in entries]
            paid_w   = [(d, w)    for d, w, e, _ in entries if e]   # for typical_delay
            recent_obs = [(d, w, e) for d, w, e, is_r in entries if is_r]

            self._recent_count[cust_code] = len(recent_obs)

            lr_mean = _km_mean(all_obs)
            self._longrun_mean[cust_code] = lr_mean
            self._recent_mean[cust_code] = _km_mean(recent_obs) if recent_obs else lr_mean

            self._worsening[cust_code] = self._check_worsening(all_obs, recent_obs)

            n_paid = sum(1 for _, _, e in all_obs if e)
            if n_paid >= self.MIN_CUSTOMER_INVOICES:
                self._raw_obs[cust_code] = all_obs
                self._raw_w[cust_code]   = paid_w
                self._sources[cust_code] = "customer"
                sample_obs = all_obs
            else:
                pool_obs = list(self._seg_pool_obs.get(seg, []))
                self._raw_obs[cust_code] = pool_obs
                self._raw_w[cust_code]   = [(d, w) for d, w, e in pool_obs if e]
                self._sources[cust_code] = "segment"
                sample_obs = pool_obs

            # Sector-shift for customers in slowing segments with < 3 recent observations
            shift = 0.0
            if self._sector_slowing.get(seg, False) and self._recent_count.get(cust_code, 0) < 3:
                self._sources[cust_code] = "segment trend"
                shift = self._sector_shift.get(seg, 0.0)

            # Bootstrap from KM distribution (sector shift applied to event delays)
            if sample_obs:
                shifted_obs = [(d + shift, w, e) if e else (d, w, e)
                               for d, w, e in sample_obs]
                self._bootstrap[cust_code] = _km_sample(shifted_obs, _BOOTSTRAP_N, bsrng)
            else:
                self._bootstrap[cust_code] = []

        self._load_partial(sa_engine, dataset_id, as_of, history_start)

        # ── Month-end payer / segment detection (Protocol deviation 3) ───────
        for cust_code, dates in cust_receipt_dates.items():
            if len(dates) >= _ME_PAYER_MIN_OBS:
                n_me = sum(
                    1 for d in dates
                    if d.day == _calendar.monthrange(d.year, d.month)[1]
                )
                if n_me / len(dates) >= _ME_PAYER_THRESHOLD:
                    self._me_payers.add(cust_code)
                    self._sources[cust_code] = "month-end payer"
        for seg, dates in seg_receipt_dates.items():
            if len(dates) >= _ME_PAYER_MIN_OBS:
                n_me = sum(
                    1 for d in dates
                    if d.day == _calendar.monthrange(d.year, d.month)[1]
                )
                if n_me / len(dates) >= _ME_PAYER_THRESHOLD:
                    self._me_segments.add(seg)

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
                ORDER BY p.cust_code
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
        all_obs: list[tuple[float, float, bool]],
        recent_obs: list[tuple[float, float, bool]],
    ) -> bool:
        n_recent_events = sum(1 for _, _, e in recent_obs if e)
        if n_recent_events < self.WORSENING_MIN_RECENT:
            return False
        lr_mean = _km_mean(all_obs)
        r_mean = _km_mean(recent_obs)
        diff = r_mean - lr_mean
        if diff < self.WORSENING_THRESHOLD:
            return False
        # Weighted variance of recent paid delays → SE
        recent_events = [(d, w) for d, w, e in recent_obs if e]
        r_tw = sum(w for _, w in recent_events)
        if r_tw <= 0:
            return False
        variance = sum(w * (d - r_mean) ** 2 for d, w in recent_events) / r_tw
        n_r = len(recent_events)
        if n_r < 2:
            return True
        se = math.sqrt(variance / n_r)
        return diff > self.WORSENING_SE_FACTOR * se if se > 0 else True

    # ── PaymentBehaviourModel protocol ────────────────────────────────────────

    def expected_delay(self, cust_code: str) -> float:
        """KM-adjusted expected delay (accounts for open overdue as censored obs)."""
        obs = self._raw_obs.get(cust_code)
        if obs:
            return _km_mean(obs)
        seg = self._cust_seg.get(cust_code, "")
        pool = self._seg_pool_obs.get(seg, [])
        return _km_mean(pool) if pool else 0.0

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
        if cust_code in self._me_payers:
            return "month-end payer"
        return self._sources.get(cust_code, "segment")

    def is_month_end_payer(self, cust_code: str) -> bool:
        return cust_code in self._me_payers

    def is_month_end_segment(self, segment: str) -> bool:
        return segment in self._me_segments

    @property
    def me_payers(self) -> frozenset:
        return frozenset(self._me_payers)

    @property
    def me_segments(self) -> frozenset:
        return frozenset(self._me_segments)

    def segment_expected_delay(self, segment: str) -> float:
        pool = self._seg_pool_obs.get(segment, [])
        return _km_mean(pool) if pool else 0.0

    def conditional_remaining_delay(self, cust_code: str, d: float) -> float:
        """E[T - d | T > d] from KM. Falls back to segment pool."""
        obs = self._raw_obs.get(cust_code)
        if obs:
            return _km_conditional_mean(obs, d)
        seg = self._cust_seg.get(cust_code, "")
        pool = self._seg_pool_obs.get(seg, [])
        return _km_conditional_mean(pool, d) if pool else 1.0

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
    def seg_overdue_fracs(self) -> dict[str, tuple[float, float]]:
        """Per-segment (current_frac_over30d, hist_frac_over30d)."""
        return dict(self._seg_overdue_frac)

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
