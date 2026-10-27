"""Turn the protocol's age criterion into minimum and maximum age in whole years.

Registry convention (ClinicalTrials.gov), which the card follows:
- Lower limit: the number as written. "Age > 18", "older than 18", "≥ 18", "18 or older"
  all give 18. (Sponsors write "> 18" to mean adults; the registry lists 18.)
- Upper limit: the oldest allowed age. "< 75", "under 75", "younger than 75" give 74;
  "≤ 75", "up to 75", "75 or younger", "18-75", "between 18 and 75" give 75.
Ages in months or days are not handled here (returns None for that bound).
"""
from __future__ import annotations

import re
import unicodedata

_NUM = r"(\d{1,3})"
_YRS = r"(?:\s*(?:years?|yrs?|y)(?:\s*(?:old|of\s+age))?)?"
_GE = r"(?:≥|>=|=>|>|≧|⩾)"
_LE = r"(?:≤|<=|=<|≦|⩽)"
_LT = r"(?:<)"

_RANGE = re.compile(rf"(?:between\s+|from\s+)?{_NUM}{_YRS}\s*(?:-|–|—|to|and|through)\s*{_NUM}{_YRS}", re.I)
_LOW = [
    re.compile(rf"{_GE}\s*{_NUM}", re.I),
    re.compile(rf"(?:at\s+least|older\s+than|greater\s+than|over|above|minimum(?:\s+age)?(?:\s+of)?|aged?)\s+{_NUM}(?!\s*(?:-|–|to|and)\s*\d)", re.I),
    re.compile(rf"{_NUM}{_YRS}\s*(?:or|and)\s*(?:older|over|above|greater)(?!\s*than)", re.I),
    re.compile(rf"{_NUM}\s*\+", re.I),
]
_HIGH_INCL = [
    re.compile(rf"{_LE}\s*{_NUM}", re.I),
    re.compile(rf"(?:up\s+to(?:\s+and\s+including)?|no\s+older\s+than|not\s+older\s+than|maximum(?:\s+age)?(?:\s+of)?|at\s+most)\s+{_NUM}", re.I),
    re.compile(rf"{_NUM}{_YRS}\s*(?:or|and)\s*(?:younger|under|less|below)(?!\s*than)", re.I),
]
_HIGH_EXCL = [
    re.compile(rf"(?<![<≤=]){_LT}(?!=)\s*{_NUM}", re.I),
    re.compile(rf"(?:younger\s+than|less\s+than|under|below)\s+{_NUM}", re.I),
]


def _clean(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    s = s.replace("\u2265", "≥").replace("\u2264", "≤")
    return re.sub(r"\s+", " ", s)


def _plausible(n: int) -> bool:
    return 0 <= n <= 120


def parse_age_criterion(text: str | None) -> tuple[int | None, int | None]:
    """(min_age_years, max_age_years) from an age criterion. None where not stated."""
    if not text:
        return None, None
    s = _clean(text)
    if re.search(r"\b(months?|weeks?|days?)\b", s, re.I) and not re.search(r"\byears?\b", s, re.I):
        return None, None
    lo = hi = None
    m = _RANGE.search(s)
    if m and _plausible(int(m.group(1))) and _plausible(int(m.group(2))) and int(m.group(1)) < int(m.group(2)):
        lo, hi = int(m.group(1)), int(m.group(2))
        # "18 to < 75" style exclusive upper bound right after the range
        if re.search(rf"(?:-|to|and)\s*<\s*{m.group(2)}", s[m.start():m.end() + 3]):
            hi -= 1
        return lo, hi
    for rx in _LOW:
        m = rx.search(s)
        if m and _plausible(int(m.group(1))):
            lo = int(m.group(1))
            break
    for rx in _HIGH_INCL:
        m = rx.search(s)
        if m and _plausible(int(m.group(1))):
            hi = int(m.group(1))
            break
    if hi is None:
        for rx in _HIGH_EXCL:
            m = rx.search(s)
            if m and _plausible(int(m.group(1))):
                hi = int(m.group(1)) - 1
                break
    if lo is not None and hi is not None and hi < lo:
        hi = None
    return lo, hi
