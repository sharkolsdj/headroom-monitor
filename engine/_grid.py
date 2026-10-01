"""Time grid utilities for the 13-week forecast horizon."""
from __future__ import annotations

import calendar
from datetime import date, timedelta


def week_starts(as_of: date, n_weeks: int = 13) -> list[date]:
    """Return list of n_weeks Monday week-start dates."""
    return [as_of + timedelta(weeks=k) for k in range(n_weeks)]


def date_to_week(d: date, as_of: date, n_weeks: int = 13) -> int | None:
    """Return 1-based week number (1..n_weeks) or None if outside horizon."""
    delta = (d - as_of).days
    if delta < 0 or delta >= n_weeks * 7:
        return None
    return delta // 7 + 1


def week_end(week_start: date) -> date:
    return week_start + timedelta(days=6)


def last_working_day(year: int, month: int) -> date:
    """Last Monday–Friday of the given month."""
    last = date(year, month, calendar.monthrange(year, month)[1])
    while last.weekday() > 4:
        last -= timedelta(days=1)
    return last


def next_working_day(d: date) -> date:
    while d.weekday() > 4:
        d += timedelta(days=1)
    return d


def months_in_horizon(as_of: date, n_weeks: int = 13) -> list[date]:
    """Return first-of-month dates for every month that overlaps the horizon."""
    horizon_end = as_of + timedelta(weeks=n_weeks) - timedelta(days=1)
    months: list[date] = []
    y, m = as_of.year, as_of.month
    while True:
        first = date(y, m, 1)
        if first > horizon_end:
            break
        months.append(first)
        m += 1
        if m > 12:
            m = 1
            y += 1
    return months
