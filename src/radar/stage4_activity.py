"""Stage 4: probe FREE FINRA sources for activity signals.

Design: recon() is run once and its raw response inspected/recorded as the fixture.
parse_signal() is the tested, stable contract. If no free machine-readable signal is
available, run() records zero signals and logs a GAP — a valid feasibility result.
"""
from __future__ import annotations

from pathlib import Path

import polars as pl

from radar.common import log
from radar.common.http import CachedClient

# Candidate free endpoints to probe during recon (resolved/confirmed at execution time).
# Documented free surfaces: FINRA Data API (developer.finra.org), Bond Center, TSAR monthly.
FINRA_RECON_ENDPOINTS = [
    # filled in during recon; left explicit so the engineer records what actually works
]


def recon(client: CachedClient, sample_isins: list[str]) -> list[dict]:
    """Probe each candidate endpoint on known US corp-bond ISINs; return raw responses.

    Run interactively; inspect the returned dicts; copy the working response shape into
    tests/fixtures/finra_recon_sample.json and update parse_signal if the shape differs.
    """
    results = []
    for url in FINRA_RECON_ENDPOINTS:
        for isin in sample_isins:
            try:
                results.append({"url": url, "isin": isin, "resp": client.get_json(url, params={"isin": isin})})
            except Exception as exc:  # noqa: BLE001
                results.append({"url": url, "isin": isin, "error": str(exc)})
    return results


def parse_signal(raw: dict, *, source_url: str, fetched_at: str) -> dict | None:
    """Normalize one FINRA response into an ACTIVITY row, or None if no activity.

    NOTE: keyed to the recon fixture shape ({isin, monthlyTrades, period}). If recon
    reveals a different shape, update this function and the fixture together.
    """
    trades = raw.get("monthlyTrades")
    if not trades:  # 0 or missing -> no observable activity
        return None
    return {
        "isin": raw["isin"],
        "signal_kind": "monthly_trade_count",
        "signal_value": str(trades),
        "observed_period": raw.get("period"),
        "source_url": source_url,
        "fetched_at": fetched_at,
    }


def run(interim_dir: Path, cache_dir: Path, fetched_at: str) -> None:
    interim_dir = Path(interim_dir)
    classified = pl.read_parquet(interim_dir / "classified.parquet")
    eligible = classified.filter(pl.col("trace_eligible_guess"))["isin"].to_list()
    client = CachedClient(cache_dir=cache_dir, min_interval=1.0)

    rows = []
    if not FINRA_RECON_ENDPOINTS:
        log.gap("stage4", "no_free_finra_endpoint_confirmed", len(eligible))
    else:
        for isin in eligible:
            for url in FINRA_RECON_ENDPOINTS:
                try:
                    raw = client.get_json(url, params={"isin": isin})
                except Exception:  # noqa: BLE001
                    continue
                sig = parse_signal(raw, source_url=url, fetched_at=fetched_at)
                if sig:
                    rows.append(sig)
                    break

    df = pl.DataFrame(rows, schema={c: pl.Utf8 for c in
        ["isin", "signal_kind", "signal_value", "observed_period", "source_url", "fetched_at"]})
    df.write_parquet(interim_dir / "activity.parquet")
    log.metric("stage4", "signals_found", df.height)
