"""Fiscal week calendar for Program Z.

Week labels look like "2023W40". The year is FISCAL (starts ~calendar October);
labels roll to W01 at the fiscal year boundary. Fiscal 2021 has 53 weeks and a
14-week Q1 (ground truth: the Strong Seasonality Weeks sheet maps 2021 XMAS to
Q1 week 14 = year week 14, while 2022+ map XMAS to Q1 week 13). All other years
in scope are 52 weeks with 13-week quarters.

Calendar dates are approximate (anchor: fiscal 2021W43 contains 2021-07-20,
from the Pricing sheet; weeks assumed Mon-Sun) and used for DISPLAY ONLY —
all modelling runs on fiscal week labels. The pricing file's own date-to-week
mapping shows weeks actually running Fri-Thu (through 2022W22) then Thu-Wed,
so never bucket daily dates into fiscal weeks via approx_monday.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

WEEK_RE = re.compile(r"^(\d{4})W(\d{2})$")

BASE_YEAR = 2021
# Monday of fiscal 2021W01: 2021W43 contains Tue 2021-07-20 -> Monday 2021-07-19,
# minus 42 weeks = 2020-09-28.
BASE_MONDAY = date(2020, 9, 28)

_53_WEEK_YEARS = {2021}


def weeks_in_year(year: int) -> int:
    return 53 if year in _53_WEEK_YEARS else 52


def parse_week(label: str) -> tuple[int, int]:
    m = WEEK_RE.match(label)
    if not m:
        raise ValueError(f"bad week label: {label!r}")
    year, week = int(m.group(1)), int(m.group(2))
    if not 1 <= week <= weeks_in_year(year):
        raise ValueError(f"week out of range: {label!r}")
    return year, week


def week_label(year: int, week: int) -> str:
    if not 1 <= week <= weeks_in_year(year):
        raise ValueError(f"week out of range: {year}W{week:02d}")
    return f"{year}W{week:02d}"


def quarter_ends(year: int) -> list[int]:
    """Last fiscal week of Q1..Q4. 53-week years put the extra week in Q1."""
    q1 = 14 if weeks_in_year(year) == 53 else 13
    return [q1, q1 + 13, q1 + 26, q1 + 39]


def fiscal_qtr_week(label: str) -> tuple[int, int]:
    """Return (quarter 1-4, week-within-quarter 1-based)."""
    year, week = parse_week(label)
    prev_end = 0
    for q, end in enumerate(quarter_ends(year), start=1):
        if week <= end:
            return q, week - prev_end
        prev_end = end
    raise AssertionError("unreachable")


def quarter_label(label: str) -> str:
    year, _ = parse_week(label)
    q, _ = fiscal_qtr_week(label)
    return f"{year}Q{q}"


def week_index(label: str) -> int:
    """Global ordinal, 0 = fiscal 2021W01."""
    year, week = parse_week(label)
    if year < BASE_YEAR:
        raise ValueError(f"year before base: {label!r}")
    return sum(weeks_in_year(y) for y in range(BASE_YEAR, year)) + week - 1


def from_index(idx: int) -> str:
    if idx < 0:
        raise ValueError(f"negative week index: {idx}")
    year = BASE_YEAR
    while idx >= weeks_in_year(year):
        idx -= weeks_in_year(year)
        year += 1
    return week_label(year, idx + 1)


def add_weeks(label: str, n: int) -> str:
    return from_index(week_index(label) + n)


def week_range(start: str, end: str) -> list[str]:
    """Inclusive ordered list of labels from start to end."""
    i, j = week_index(start), week_index(end)
    if j < i:
        raise ValueError(f"end before start: {start} > {end}")
    return [from_index(k) for k in range(i, j + 1)]


def approx_monday(label: str) -> date:
    return BASE_MONDAY + timedelta(weeks=week_index(label))
