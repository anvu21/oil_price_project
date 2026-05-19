"""
Pure aggregation functions: TransformRecord list → upsert-ready dataclasses.

No SQLAlchemy or boto3 imports — fully unit-testable without AWS dependencies.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal


# ---------------------------------------------------------------------------
# Output dataclasses (plain Python — no ORM attachment)
# ---------------------------------------------------------------------------

@dataclass
class WeeklyRow:
    state: str
    week_start: date
    avg_price: Decimal
    grade: str


@dataclass
class MonthlyRow:
    state: str
    year_month: date    # first day of the month
    avg_price: Decimal
    min_price: Decimal
    max_price: Decimal
    grade: str


@dataclass
class YearlyRow:
    state: str
    year: int
    avg_price: Decimal
    min_price: Decimal
    max_price: Decimal
    grade: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _avg(values: list[Decimal]) -> Decimal:
    """Mean using Decimal arithmetic to avoid floating-point rounding."""
    return sum(values) / Decimal(len(values))


def _month_start(d: date) -> date:
    return date(d.year, d.month, 1)


# ---------------------------------------------------------------------------
# Aggregation functions
# ---------------------------------------------------------------------------

def build_weekly(records: list) -> list[WeeklyRow]:
    """
    One WeeklyRow per (state, week_start, grade).

    The EIA API returns one record per area per week so there is almost always
    exactly one value per key. The average handles the edge case where a backfill
    file contains duplicate weeks.
    """
    buckets: dict[tuple, list[Decimal]] = defaultdict(list)
    for r in records:
        buckets[(r.state, r.week_start, r.grade)].append(r.avg_price)

    return [
        WeeklyRow(state=state, week_start=week_start, avg_price=_avg(prices), grade=grade)
        for (state, week_start, grade), prices in sorted(buckets.items())
    ]


def build_monthly(records: list) -> list[MonthlyRow]:
    """
    One MonthlyRow per (state, year_month, grade).

    Aggregates all weekly observations within a calendar month.
    avg_price is the mean; min/max are the extremes across all weeks.
    """
    buckets: dict[tuple, list[Decimal]] = defaultdict(list)
    for r in records:
        buckets[(r.state, _month_start(r.week_start), r.grade)].append(r.avg_price)

    return [
        MonthlyRow(
            state=state,
            year_month=ym,
            avg_price=_avg(prices),
            min_price=min(prices),
            max_price=max(prices),
            grade=grade,
        )
        for (state, ym, grade), prices in sorted(buckets.items())
    ]


def build_yearly(records: list) -> list[YearlyRow]:
    """
    One YearlyRow per (state, year, grade).

    Aggregates all weekly observations within a calendar year.
    """
    buckets: dict[tuple, list[Decimal]] = defaultdict(list)
    for r in records:
        buckets[(r.state, r.week_start.year, r.grade)].append(r.avg_price)

    return [
        YearlyRow(
            state=state,
            year=year,
            avg_price=_avg(prices),
            min_price=min(prices),
            max_price=max(prices),
            grade=grade,
        )
        for (state, year, grade), prices in sorted(buckets.items())
    ]
