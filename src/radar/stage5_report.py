"""Stage 5: assemble the feasibility funnel, candidates.csv, and GAPS section."""
from __future__ import annotations

from pathlib import Path

import polars as pl

from radar.common import log
from radar.stage3_classify import DEBT_TYPES


def compute_funnel(securities, entities, candidates, classified, activity) -> dict:
    return {
        "N0_sanctioned_securities": securities.height,
        "N1_with_isin": securities.filter(pl.col("isin").is_not_null()).height,
        "N2_entities_with_lei": entities.filter(pl.col("lei").is_not_null()).height,
        "N3_descendant_issuers":
            candidates.filter(pl.col("path_depth") > 0).select("issuer_lei").n_unique(),
        "N4_candidates": candidates.select("isin").n_unique(),
        "N4_direct": candidates.filter(pl.col("tag") == "direct").select("isin").n_unique(),
        "N4_indirect": candidates.filter(pl.col("tag") == "indirect").select("isin").n_unique(),
        "N5_debt_instruments":
            classified.filter(pl.col("security_type").is_in(list(DEBT_TYPES))).select("isin").n_unique(),
        "N6_us_trace_eligible":
            classified.filter(pl.col("trace_eligible_guess")).select("isin").n_unique(),
        "N7_with_activity": activity.select("isin").n_unique(),
    }


def render_report(funnel: dict, gaps: dict, sample: bool = False) -> str:
    lines = ["# Feasibility Funnel", ""]
    if sample:
        lines += ["> NOTE: generated in --sample mode on fixtures — counts are illustrative, "
                  "not real findings.", ""]
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


def run(interim_dir: Path, out_dir: Path, sample: bool = False) -> None:
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
        "invalid_us_isin_check_digit":
            classified.filter(pl.col("gap_reason") == "invalid_us_isin_check_digit").height,
        "sanctioned_entity_without_lei": entities.filter(pl.col("lei").is_null()).height,
        "no_activity_signal": funnel["N6_us_trace_eligible"] - funnel["N7_with_activity"],
    }

    # one row per ISIN, preferring the most direct sanctioned connection (min path_depth)
    candidates_1 = (candidates
        .sort("path_depth")
        .unique(subset=["isin"], keep="first")
        .select(["isin", "tag", "issuer_lei", "root_sanctioned_lei", "path_depth"]))
    classified_1 = classified.unique(subset=["isin"], keep="first")
    # human-readable name for the issuer LEI, where it is a known sanctioned entity
    names = (entities.filter(pl.col("lei").is_not_null())
        .select([pl.col("lei").alias("issuer_lei"), pl.col("name").alias("issuer_name")])
        .unique(subset=["issuer_lei"], keep="first"))
    enriched = (candidates_1
        .join(classified_1, on="isin", how="left")
        .join(names, on="issuer_lei", how="left")
        .join(activity.select(["isin", "signal_value", "source_url", "fetched_at"]),
              on="isin", how="left")
        .sort(pl.col("signal_value").cast(pl.Int64, strict=False),
              descending=True, nulls_last=True))
    enriched.write_csv(out_dir / "candidates.csv")
    (out_dir / "report.md").write_text(render_report(funnel, gaps, sample=sample), encoding="utf-8")
    log.metric("stage5", "candidates_csv_rows", enriched.height)
