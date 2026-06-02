import json
from pathlib import Path
from radar.stage4_activity import parse_signal

FIX = Path(__file__).parent / "fixtures"

def test_parse_signal_extracts_trade_count():
    raw = json.loads((FIX / "finra_recon_sample.json").read_text())
    sig = parse_signal(raw, source_url="https://finra.test/x", fetched_at="2026-06-02")
    assert sig["isin"] == "US0378331005"
    assert sig["signal_kind"] == "monthly_trade_count"
    assert sig["signal_value"] == "42"
    assert sig["observed_period"] == "2026-05"
    assert sig["source_url"] == "https://finra.test/x"

def test_parse_signal_returns_none_when_no_activity():
    sig = parse_signal({"isin": "US0378331005", "monthlyTrades": 0, "period": "2026-05"},
                       source_url="u", fetched_at="t")
    assert sig is None
