"""ISO weeks as the digest's unit of time. Monday 00:00 UTC to the next Monday."""

import re
from datetime import date, datetime, timedelta, timezone
from typing import Tuple

_WEEK = re.compile(r'^(\d{4})-W(\d{2})$')


def week_id(day: date) -> str:
    year, week, _ = day.isocalendar()
    return f'{year}-W{week:02d}'


def week_bounds(week: str) -> Tuple[datetime, datetime]:
    match = _WEEK.match(week)
    if not match:
        raise ValueError(f'week must look like 2026-W37, got {week!r}')
    year, number = int(match.group(1)), int(match.group(2))
    monday = date.fromisocalendar(year, number, 1)
    start = datetime(monday.year, monday.month, monday.day, tzinfo=timezone.utc)
    return start, start + timedelta(days=7)


def resolve_week(spec: str, today: date = None) -> str:
    """'current', 'previous' or an explicit YYYY-Www."""
    today = today or datetime.now(timezone.utc).date()
    if spec == 'current':
        return week_id(today)
    if spec == 'previous':
        return week_id(today - timedelta(days=7))
    week_bounds(spec)            # validates
    return spec
