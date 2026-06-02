"""Stage 3: classify candidate ISINs by US-bond / TRACE-eligibility."""
from __future__ import annotations

from pathlib import Path

import polars as pl

from radar.common import log
from radar.common.ids import us_isin_to_cusip
from radar.common.http import CachedClient

# Instrument types that actually trade on FINRA TRACE (debt). Pfd (preferred equity)
# and Muni (reports to MSRB EMMA, not TRACE) are deliberately excluded.
DEBT_TYPES = {"Corp", "Govt", "Mtge", "Bond", "Note"}
OPENFIGI_URL = "https://api.openfigi.com/v3/mapping"


def is_debt_type(security_type: str | None) -> bool:
    return security_type in DEBT_TYPES


def classify_isin(isin: str, security_type: str | None) -> dict:
    is_us = isin.startswith("US")
    cusip = None
    gap = None
    if is_us:
        try:
            cusip = us_isin_to_cusip(isin)
        except ValueError:
            gap = "invalid_us_isin_check_digit"  # bad data, degrade gracefully
    else:
        gap = "non_us_isin_no_cusip_map"
    debt = is_debt_type(security_type)
    return {
        "isin": isin,
        "is_us": is_us,
        "cusip": cusip,
        "security_type": security_type,
        "trace_eligible_guess": bool(is_us and debt and cusip is not None),
        "gap_reason": gap,
    }


def lookup_types(isins: list[str], client: CachedClient, batch_size: int = 10) -> dict[str, str]:
    """Resolve securityType2 per ISIN via OpenFIGI. Caps + logs dropped on rate limit."""
    out: dict[str, str] = {}
    for i in range(0, len(isins), batch_size):
        chunk = isins[i:i + batch_size]
        body = [{"idType": "ID_ISIN", "idValue": x} for x in chunk]
        try:
            resp = client.post_json(OPENFIGI_URL, body=body)
        except Exception:  # noqa: BLE001 — rate-limited/blocked: record and continue
            log.gap("stage3", "openfigi_lookup_failed", len(chunk))
            continue
        if not isinstance(resp, list):  # API error object instead of a results list
            log.gap("stage3", "openfigi_unexpected_response", len(chunk))
            continue
        for isin, entry in zip(chunk, resp):
            data = entry.get("data") if isinstance(entry, dict) else None
            if data:
                out[isin] = data[0].get("securityType2") or data[0].get("marketSector")
    return out


def run(interim_dir: Path, cache_dir: Path) -> None:
    interim_dir = Path(interim_dir)
    cand = pl.read_parquet(interim_dir / "candidate_isins.parquet")
    client = CachedClient(cache_dir=cache_dir, min_interval=2.0)
    types = lookup_types(cand["isin"].to_list(), client)
    rows = [classify_isin(isin, types.get(isin)) for isin in cand["isin"].to_list()]
    df = pl.DataFrame(rows)
    df.write_parquet(interim_dir / "classified.parquet")

    log.metric("stage3", "us_isins", df.filter(pl.col("is_us")).height)
    log.metric("stage3", "trace_eligible_guess", df.filter(pl.col("trace_eligible_guess")).height)
    log.gap("stage3", "non_us_isin_no_cusip_map", df.filter(~pl.col("is_us")).height)
    log.gap("stage3", "invalid_us_isin_check_digit",
            df.filter(pl.col("gap_reason") == "invalid_us_isin_check_digit").height)
