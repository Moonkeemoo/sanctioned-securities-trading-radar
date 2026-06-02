from radar.stage3_classify import classify_isin, is_debt_type

def test_classify_us_isin_derives_cusip():
    row = classify_isin("US0378331005", security_type="Corp")
    assert row["is_us"] is True
    assert row["cusip"] == "037833100"
    assert row["trace_eligible_guess"] is True
    assert row["gap_reason"] is None

def test_classify_non_us_flags_gap():
    row = classify_isin("XS1234567890", security_type="Corp")
    assert row["is_us"] is False
    assert row["cusip"] is None
    assert row["gap_reason"] == "non_us_isin_no_cusip_map"

def test_equity_not_trace_eligible():
    row = classify_isin("US0378331005", security_type="Equity")
    assert row["trace_eligible_guess"] is False

def test_is_debt_type():
    assert is_debt_type("Corp") is True
    assert is_debt_type("Govt") is True
    assert is_debt_type("Equity") is False
    assert is_debt_type(None) is False
