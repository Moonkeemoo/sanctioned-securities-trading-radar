import polars as pl
from radar.stage5_report import compute_funnel, render_report

def _frames():
    securities = pl.DataFrame({"isin": ["US0378331005", "XS1234567890"]})
    entities = pl.DataFrame({"lei": ["P", None]})
    candidates = pl.DataFrame({"isin": ["US0378331005", "US5949181045"],
                               "tag": ["direct", "indirect"]})
    classified = pl.DataFrame({"isin": ["US0378331005", "US5949181045"],
                               "is_us": [True, True],
                               "trace_eligible_guess": [True, False]})
    activity = pl.DataFrame({"isin": ["US0378331005"]})
    return securities, entities, candidates, classified, activity

def test_compute_funnel_counts():
    f = compute_funnel(*_frames())
    assert f["N0_sanctioned_securities"] == 2
    assert f["N4_candidates"] == 2
    assert f["N4_direct"] == 1
    assert f["N4_indirect"] == 1
    assert f["N6_us_trace_eligible"] == 1
    assert f["N7_with_activity"] == 1

def test_render_report_contains_gaps_section():
    f = compute_funnel(*_frames())
    md = render_report(f, gaps={"non_us_isin": 1})
    assert "## GAPS" in md
    assert "N7" in md
