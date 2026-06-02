"""ISIN and CUSIP identifier math.

ISIN = 2-letter country + 9-char NSIN + 1 check digit (mod-10 / Luhn over base-36).
CUSIP = 9 chars where the 9th is a mod-10 check digit.
For US securities: ISIN == "US" + 9-char CUSIP + ISIN check digit, so the mapping
is exact and reversible. This module is the single source of truth for that math.
"""
from __future__ import annotations

_ALNUM = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _luhn_mod10(digits: list[int]) -> int:
    """Luhn checksum used by ISIN: double every second digit from the right."""
    total = 0
    # Rightmost (the position the check digit will occupy) is doubled first.
    double = True
    for d in reversed(digits):
        if double:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        double = not double
    return (10 - (total % 10)) % 10


def isin_check_digit(isin_body: str) -> int:
    """Compute the ISIN check digit for the 11-char body (country+NSIN)."""
    expanded: list[int] = []
    for ch in isin_body.upper():
        val = _ALNUM.index(ch)
        if val < 10:
            expanded.append(val)
        else:
            expanded.append(val // 10)
            expanded.append(val % 10)
    return _luhn_mod10(expanded)


def is_valid_isin(isin: str) -> bool:
    if not isinstance(isin, str) or len(isin) != 12:
        return False
    if not isin[:2].isalpha():
        return False
    body, check = isin[:11], isin[11]
    if not check.isdigit():
        return False
    try:
        return isin_check_digit(body) == int(check)
    except ValueError:
        return False


def cusip_check_digit(cusip9: str) -> int:
    """The 9th CUSIP char is the check digit; recompute from the first 8."""
    body = cusip9.upper()[:8]
    total = 0
    for i, ch in enumerate(body):
        if ch.isdigit():
            v = int(ch)
        else:
            v = _ALNUM.index(ch)  # A=10..Z=35
        if i % 2 == 1:  # every second char (0-indexed odd) doubled
            v *= 2
        total += v // 10 + v % 10
    return (10 - (total % 10)) % 10


def us_isin_to_cusip(isin: str) -> str:
    if not isin.startswith("US") or len(isin) != 12:
        raise ValueError(f"Not a US ISIN: {isin!r}")
    return isin[2:11]


def cusip_to_us_isin(cusip9: str) -> str:
    body = "US" + cusip9.upper()
    return body + str(isin_check_digit(body))
