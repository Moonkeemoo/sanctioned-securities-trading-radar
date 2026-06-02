"""Stage 2: traverse the GLEIF ownership graph; tag candidate ISINs direct/indirect."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import polars as pl

from radar.common import log
from radar.common.schemas import TAG_DIRECT, TAG_INDIRECT


def descendants(seed_leis: set[str], relations, max_depth: int) -> set[str]:
    """All LEIs reachable downward from seeds (exclusive of seeds), depth-bounded."""
    children = defaultdict(list)
    for parent, child in relations:
        children[parent].append(child)
    found: set[str] = set()
    frontier = set(seed_leis)
    for _ in range(max_depth):
        nxt: set[str] = set()
        for lei in frontier:
            for child in children.get(lei, []):
                if child not in found:
                    found.add(child)
                    nxt.add(child)
        if not nxt:
            break
        frontier = nxt
    return found - set(seed_leis)  # seeds excluded even if re-reached via a cycle


def build_candidates(seed_leis, relations, isin_to_lei: pl.DataFrame,
                     sanctioned_isins: set[str], max_depth: int) -> pl.DataFrame:
    desc = descendants(set(seed_leis), list(relations), max_depth)
    all_leis = set(seed_leis) | desc
    sub = isin_to_lei.filter(pl.col("lei").is_in(list(all_leis)))
    rows = []
    for r in sub.to_dicts():
        isin, lei = r["isin"], r["lei"]
        tag = TAG_DIRECT if isin in sanctioned_isins else TAG_INDIRECT
        # root = the seed LEI if issuer is a seed, else first seed (approx for spike)
        root = lei if lei in seed_leis else next(iter(seed_leis), None)
        rows.append({
            "isin": isin, "issuer_lei": lei, "root_sanctioned_lei": root,
            "path_depth": 0 if lei in seed_leis else 1, "tag": tag,
        })
    return pl.DataFrame(rows, schema={
        "isin": pl.Utf8, "issuer_lei": pl.Utf8, "root_sanctioned_lei": pl.Utf8,
        "path_depth": pl.Int64, "tag": pl.Utf8})


def run(interim_dir: Path, max_depth: int = 5) -> None:
    interim_dir = Path(interim_dir)
    entities = pl.read_parquet(interim_dir / "sanctioned_entities.parquet")
    securities = pl.read_parquet(interim_dir / "sanctioned_securities.parquet")
    isin_to_lei = pl.read_parquet(interim_dir / "isin_to_lei.parquet")
    rr = pl.read_parquet(interim_dir / "lei_relations.parquet")

    seed_leis = set(entities.filter(pl.col("lei").is_not_null())["lei"].to_list())
    # also seed with LEIs of issuers of sanctioned ISINs (via GLEIF, not the OS issuer link)
    sanctioned_isins = set(securities["isin"].to_list())
    issuer_leis = set(isin_to_lei.filter(pl.col("isin").is_in(list(sanctioned_isins)))["lei"].to_list())
    seed_leis |= issuer_leis

    relations = list(zip(rr["parent_lei"].to_list(), rr["child_lei"].to_list()))
    out = build_candidates(seed_leis, relations, isin_to_lei, sanctioned_isins, max_depth)
    out.write_parquet(interim_dir / "candidate_isins.parquet")

    log.metric("stage2", "seed_leis", len(seed_leis))
    log.metric("stage2", "descendant_leis", len(descendants(seed_leis, relations, max_depth)))
    log.metric("stage2", "candidates_direct", out.filter(pl.col("tag") == TAG_DIRECT).height)
    log.metric("stage2", "candidates_indirect", out.filter(pl.col("tag") == TAG_INDIRECT).height)
    no_lei = entities.filter(pl.col("lei").is_null()).height
    log.gap("stage2", "sanctioned_entity_without_lei", no_lei)
