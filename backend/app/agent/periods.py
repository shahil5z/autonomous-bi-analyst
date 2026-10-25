"""Deterministic period parsing, resolved against the real data range."""

from __future__ import annotations

import re
from datetime import date

from app.agent.schemas import Period

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
     "november", "december"], start=1)}
MONTHS.update({k[:3]: v for k, v in list(MONTHS.items())})
ORDINAL_Q = {"first": 1, "second": 2, "third": 3, "fourth": 4, "1st": 1, "2nd": 2, "3rd": 3, "4th": 4}


def quarter(year: int, q: int) -> Period:
    start = date(year, 3 * (q - 1) + 1, 1)
    end = date(year + 1, 1, 1) if q == 4 else date(year, 3 * q + 1, 1)
    return Period(label=f"{year}-Q{q}", start=start, end=end)


def month(year: int, m: int) -> Period:
    end = date(year + 1, 1, 1) if m == 12 else date(year, m + 1, 1)
    return Period(label=f"{year}-{m:02d}", start=date(year, m, 1), end=end)


def year(y: int) -> Period:
    return Period(label=str(y), start=date(y, 1, 1), end=date(y + 1, 1, 1))


def latest_complete_quarter(hi: date) -> Period:
    y, q = hi.year, (hi.month - 1) // 3 + 1
    p = quarter(y, q)
    if hi < date.fromordinal(p.end.toordinal() - 1):
        q -= 1
        if q == 0:
            y, q = y - 1, 4
    return quarter(y, q)


def previous_quarter(p: Period) -> Period:
    y, q = int(p.label[:4]), int(p.label[-1])
    return quarter(y - 1, 4) if q == 1 else quarter(y, q - 1)


def same_quarter_last_year(p: Period) -> Period:
    return quarter(int(p.label[:4]) - 1, int(p.label[-1]))


def parse_label(label: str | None, hi: date) -> Period | None:
    """Parse a single label like '2011-Q3', 'Q3 2011', '2011', '2011-03', 'March 2011'."""
    if not label:
        return None
    found = find_periods(label, hi)
    return found[0] if found else None


def find_periods(text: str, hi: date) -> list[Period]:
    """Return all periods mentioned, in order of appearance."""
    t = text.lower()
    hits: list[tuple[int, Period]] = []
    taken: list[tuple[int, int]] = []

    def add(m: re.Match, p: Period) -> None:
        if any(a < m.end() and m.start() < b for a, b in taken):
            return
        taken.append((m.start(), m.end()))
        hits.append((m.start(), p))

    for m in re.finditer(r"\b(20\d\d)\s*[-/ ]?\s*q([1-4])\b", t):
        add(m, quarter(int(m.group(1)), int(m.group(2))))
    for m in re.finditer(r"\bq([1-4])\s*(?:of\s*)?(20\d\d)\b", t):
        add(m, quarter(int(m.group(2)), int(m.group(1))))
    for m in re.finditer(r"\b(first|second|third|fourth|1st|2nd|3rd|4th)\s+quarter(?:\s+(?:of\s+)?(20\d\d))?", t):
        q = ORDINAL_Q[m.group(1)]
        y = int(m.group(2)) if m.group(2) else (hi.year if quarter(hi.year, q).end <= hi else hi.year - 1)
        add(m, quarter(y, q))
    for m in re.finditer(r"\bq([1-4])\b", t):
        q = int(m.group(1))
        y = hi.year if quarter(hi.year, q).end <= hi else hi.year - 1
        add(m, quarter(y, q))
    for m in re.finditer(r"\b(20\d\d)-(0[1-9]|1[0-2])\b", t):
        add(m, month(int(m.group(1)), int(m.group(2))))
    for m in re.finditer(r"\b(" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\s+(20\d\d)\b", t):
        add(m, month(int(m.group(2)), MONTHS[m.group(1)]))
    for m in re.finditer(r"\b(20\d\d)\b", t):
        add(m, year(int(m.group(1))))
    if re.search(r"\blast quarter\b", t):
        m = re.search(r"\blast quarter\b", t)
        add(m, latest_complete_quarter(hi))
    if re.search(r"\blast month\b", t):
        m = re.search(r"\blast month\b", t)
        y, mo = (hi.year, hi.month - 1) if hi.month > 1 else (hi.year - 1, 12)
        add(m, month(y, mo))
    return [p for _, p in sorted(hits, key=lambda h: h[0])]
