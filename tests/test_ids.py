import pytest
from radar.common.ids import (
    is_valid_isin, isin_check_digit, cusip_check_digit,
    us_isin_to_cusip, cusip_to_us_isin,
)

# Apple common stock ISIN US0378331005 (CUSIP 037833100) — published reference vector.
def test_valid_isin_apple():
    assert is_valid_isin("US0378331005") is True

def test_invalid_isin_bad_check_digit():
    assert is_valid_isin("US0378331006") is False

def test_invalid_isin_bad_length():
    assert is_valid_isin("US037833100") is False

def test_isin_check_digit_apple():
    assert isin_check_digit("US037833100") == 5

def test_cusip_check_digit_apple():
    assert cusip_check_digit("037833100") == 0  # full CUSIP is 037833100, last digit IS the check

def test_us_isin_to_cusip_apple():
    assert us_isin_to_cusip("US0378331005") == "037833100"

def test_us_isin_to_cusip_rejects_non_us():
    with pytest.raises(ValueError):
        us_isin_to_cusip("DE0005140008")

def test_cusip_to_us_isin_roundtrip():
    assert cusip_to_us_isin("037833100") == "US0378331005"

def test_valid_isin_microsoft():
    assert is_valid_isin("US5949181045") is True

def test_us_isin_to_cusip_rejects_bad_check_digit():
    with pytest.raises(ValueError):
        us_isin_to_cusip("US0378331009")  # valid format, wrong check digit
