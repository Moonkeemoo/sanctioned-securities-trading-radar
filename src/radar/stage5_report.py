"""Stage 5: assemble the feasibility funnel, candidates.csv, and GAPS section."""
from __future__ import annotations

from pathlib import Path

import polars as pl

from radar.common import log


def compute_funnel(securities, entities, candidates, classified, activity) -> dict:
    return {
        "N0_sanctioned_securities": securities.height,
        "N1_with_isin": securities.filter(pl.col("isin").is_not_null()).height,
        "N2_entities_with_lei": entities.filter(pl.col("lei").is_not_null()).height,
        "N4_candidates": candidates.height,
        "N4_direct": candidates.filter(pl.col("tag") == "direct").height,
        "N4_indirect": candidates.filter(pl.col("tag") == "indirect").height,
        "N6_us_trace_eligible": classified.filter(pl.col("trace_eligible_guess")).height,
        "N7_with_activity": activity.height,
    }


def render_report(funnel: dict, gaps: dict) -> str:
    lines = ["# Feasibility Funnel", ""]
    for k, v in funnel.items():
        lines.append(f"- **{k}**: {v}")
    verdict = (
        "ZERO" if funnel["N6_us_trace_eligible"] == 0
        else "MARGINAL" if funnel["N6_us_trace_eligible"] < 25
        else "SIGNIFICANT"
    )
    lines += ["", f"**Intersection verdict (N6): {verdict}**", "", "## GAPS", ""]
    for reason, count in gaps.items():
        lines.append(f"- {reason}: {count}")
    return "\n".join(lines) + "\n"


def run(interim_dir: Path, out_dir: Path) -> None:
    interim_dir, out_dir = Path(interim_dir), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    securities = pl.read_parquet(interim_dir / "sanctioned_securities.parquet")
    entities = pl.read_parquet(interim_dir / "sanctioned_entities.parquet")
    candidates = pl.read_parquet(interim_dir / "candidate_isins.parquet")
    classified = pl.read_parquet(interim_dir / "classified.parquet")
    activity = pl.read_parquet(interim_dir / "activity.parquet")

    funnel = compute_funnel(securities, entities, candidates, classified, activity)
    gaps = {
        "non_us_isin": classified.filter(~pl.col("is_us")).height,
        "sanctioned_entity_without_lei": entities.filter(pl.col("lei").is_null()).height,
        "no_activity_signal": funnel["N6_us_trace_eligible"] - funnel["N7_with_activity"],
    }

    # candidates.csv: classified joined with tag + activity, ranked activity-first
    enriched = (classified
        .join(candidates.select(["isin", "tag", "issuer_lei", "root_sanctioned_lei"]), on="isin", how="left")
        .join(activity.select(["isin", "signal_value", "source_url"]), on="isin", how="left")
        .sort("signal_value", descending=True, nulls_last=True))
    enriched.write_csv(out_dir / "candidates.csv")
    (out_dir / "report.md").write_text(render_report(funnel, gaps), encoding="utf-8")
    log.metric("stage5", "candidates_csv_rows", enriched.height)
