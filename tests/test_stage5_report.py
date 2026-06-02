import polars as pl
from radar.stage5_report import compute_funnel, render_report, run

def _frames():
    securities = pl.DataFrame({"isin": ["US0378331005", "XS1234567890"]})
    entities = pl.DataFrame({"lei": ["P", None]})
    candidates = pl.DataFrame({"isin": ["US0378331005", "US5949181045"],
                               "tag": ["direct", "indirect"],
                               "issuer_lei": ["P", "SUB"],
                               "path_depth": [0, 1]})
    classified = pl.DataFrame({"isin": ["US0378331005", "US5949181045"],
                               "is_us": [True, True],
                               "security_type": ["Corp", "Equity"],
                               "trace_eligible_guess": [True, False]})
    activity = pl.DataFrame({"isin": ["US0378331005"]})
    return securities, entities, candidates, classified, activity

def test_compute_funnel_counts():
    f = compute_funnel(*_frames())
    assert f["N0_sanctioned_securities"] == 2
    assert f["N3_descendant_issuers"] == 1
    assert f["N4_candidates"] == 2
    assert f["N4_direct"] == 1
    assert f["N4_indirect"] == 1
    assert f["N5_debt_instruments"] == 1
    assert f["N6_us_trace_eligible"] == 1
    assert f["N7_with_activity"] == 1

def test_render_report_contains_gaps_section():
    f = compute_funnel(*_frames())
    md = render_report(f, gaps={"non_us_isin": 1})
    assert "## GAPS" in md
    assert "N7" in md

def test_render_report_sample_label():
    f = compute_funnel(*_frames())
    assert "--sample" in render_report(f, gaps={}, sample=True)
    assert "--sample" not in render_report(f, gaps={}, sample=False)

def test_run_ranks_candidates_numerically(tmp_path):
    interim = tmp_path / "interim"; interim.mkdir()  # noqa: E702
    out = tmp_path / "out"
    pl.DataFrame({"isin": ["US0378331005", "US5949181045"]}).write_parquet(
        interim / "sanctioned_securities.parquet")
    pl.DataFrame({"entity_id": ["e"], "name": ["ACME"], "lei": ["P"],
                  "country": [None], "topics": [None]},
                 schema={"entity_id": pl.Utf8, "name": pl.Utf8, "lei": pl.Utf8,
                         "country": pl.Utf8, "topics": pl.Utf8}).write_parquet(
        interim / "sanctioned_entities.parquet")
    pl.DataFrame({"isin": ["US0378331005", "US5949181045"], "issuer_lei": ["P", "SUB"],
                  "root_sanctioned_lei": ["P", "P"], "path_depth": [0, 1],
                  "tag": ["direct", "indirect"]}).write_parquet(
        interim / "candidate_isins.parquet")
    pl.DataFrame({"isin": ["US0378331005", "US5949181045"], "is_us": [True, True],
                  "cusip": ["037833100", "594918104"], "security_type": ["Corp", "Corp"],
                  "trace_eligible_guess": [True, True], "gap_reason": [None, None]},
                 schema={"isin": pl.Utf8, "is_us": pl.Boolean, "cusip": pl.Utf8,
                         "security_type": pl.Utf8, "trace_eligible_guess": pl.Boolean,
                         "gap_reason": pl.Utf8}).write_parquet(interim / "classified.parquet")
    pl.DataFrame({"isin": ["US0378331005", "US5949181045"],
                  "signal_kind": ["monthly_trade_count", "monthly_trade_count"],
                  "signal_value": ["9", "42"], "observed_period": ["2026-05", "2026-05"],
                  "source_url": ["u", "u"], "fetched_at": ["t", "t"]}).write_parquet(
        interim / "activity.parquet")

    run(interim, out)
    csv = pl.read_csv(out / "candidates.csv")
    assert csv["isin"][0] == "US5949181045"  # 42 trades ranks above 9 (numeric, not lexicographic)
    assert "fetched_at" in csv.columns
    assert "issuer_name" in csv.columns
