"""Pipeline orchestrator. `--sample` skips network stages (no OpenFIGI/FINRA calls)."""
from __future__ import annotations

import argparse
from pathlib import Path

import polars as pl

from radar import stage1_ingest, stage2_ownership, stage3_classify, stage4_activity, stage5_report


def _classify_offline(interim_dir: Path) -> None:
    """Sample mode: classify with UNKNOWN security_type (None) so nothing is marked
    TRACE-eligible by type (US ISINs still derive a CUSIP). Keeps the e2e smoke test
    network-free and avoids inflating the sample funnel's N6."""
    cand = pl.read_parquet(interim_dir / "candidate_isins.parquet")
    rows = [stage3_classify.classify_isin(isin, security_type=None)
            for isin in cand["isin"].to_list()]
    pl.DataFrame(rows).write_parquet(interim_dir / "classified.parquet")


def run_pipeline(raw_dir, interim_dir, out_dir, cache_dir, *, sample: bool, fetched_at: str) -> None:
    raw_dir, interim_dir = Path(raw_dir), Path(interim_dir)
    stage1_ingest.run(raw_dir, interim_dir)
    stage2_ownership.run(interim_dir)
    if sample:
        _classify_offline(interim_dir)
        pl.DataFrame(schema={c: pl.Utf8 for c in
            ["isin", "signal_kind", "signal_value", "observed_period", "source_url", "fetched_at"]}
            ).write_parquet(interim_dir / "activity.parquet")
    else:
        stage3_classify.run(interim_dir, cache_dir)
        stage4_activity.run(interim_dir, cache_dir, fetched_at)
    stage5_report.run(interim_dir, out_dir, sample=sample)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="data/raw")
    ap.add_argument("--interim", default="data/interim")
    ap.add_argument("--out", default="data/out")
    ap.add_argument("--cache", default="data/cache")
    ap.add_argument("--sample", action="store_true")
    ap.add_argument("--date", default="unknown")
    a = ap.parse_args()
    run_pipeline(a.raw, a.interim, a.out, a.cache, sample=a.sample, fetched_at=a.date)


if __name__ == "__main__":
    main()
