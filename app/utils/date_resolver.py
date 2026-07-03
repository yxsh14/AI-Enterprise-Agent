"""Resolve explicit calendar dates in user questions to ISO ``YYYY-MM-DD`` strings.

Supported formats (weekday names like "Wednesday" are intentionally **not** parsed):

- ``2026-07-02``
- ``02 July 2026``, ``2 July 2026``, ``2nd July 2026``
- ``July 02 2026``, ``July 2, 2026``
- ``02/07/2026``, ``02-07-2026`` (day/month/year)
"""

from __future__ import annotations

import re
from datetime import date

_ISO_DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")

_DAY_MONTH_YEAR_RE = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th)?\s+"
    r"(january|february|march|april|may|june|july|august|september|october|november|december|"
    r"jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)"
    r"\s+(\d{4})\b",
    re.IGNORECASE,
)

_MONTH_DAY_YEAR_RE = re.compile(
    r"\b(january|february|march|april|may|june|july|august|september|october|november|december|"
    r"jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)"
    r"\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b",
    re.IGNORECASE,
)

_NUMERIC_DMY_RE = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b")

_MONTHS: dict[str, int] = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sep": 9,
    "sept": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}


def resolve_date(question: str) -> str | None:
    """Return ``YYYY-MM-DD`` when an explicit date is found in *question*, else ``None``."""
    iso_match = _ISO_DATE_RE.search(question)
    if iso_match:
        return _to_iso(iso_match.group(1), iso_match.group(2), iso_match.group(3))

    day_month_year = _DAY_MONTH_YEAR_RE.search(question)
    if day_month_year:
        day = int(day_month_year.group(1))
        month = _MONTHS[day_month_year.group(2).lower()]
        year = int(day_month_year.group(3))
        return _to_iso(year, month, day)

    month_day_year = _MONTH_DAY_YEAR_RE.search(question)
    if month_day_year:
        month = _MONTHS[month_day_year.group(1).lower()]
        day = int(month_day_year.group(2))
        year = int(month_day_year.group(3))
        return _to_iso(year, month, day)

    numeric = _NUMERIC_DMY_RE.search(question)
    if numeric:
        day = int(numeric.group(1))
        month = int(numeric.group(2))
        year = int(numeric.group(3))
        return _to_iso(year, month, day)

    return None


def _to_iso(year: int | str, month: int | str, day: int | str) -> str | None:
    try:
        return date(int(year), int(month), int(day)).isoformat()
    except ValueError:
        return None
