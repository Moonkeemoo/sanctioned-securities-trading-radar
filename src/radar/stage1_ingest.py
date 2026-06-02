"""Stage 1: parse free bulk dumps into normalized Parquet tables."""
from __future__ import annotations

import json
from pathlib import Path

import polars as pl

from radar.common import log


def _first(props: dict, key: str):
    vals = props.get(key)
    return vals[0] if vals else None


def parse_securities(path: Path) -> pl.DataFrame:
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        ent = json.loads(line)
        if ent.get("schema") != "Security":
            continue
        p = ent.get("properties", {})
        rows.append({
            "isin": _first(p, "isin"),
            "ticker": _first(p, "ticker"),
            "figi": _first(p, "figiCode"),
            "issuer_name": _first(p, "name"),
            "issuer_entity_id": _first(p, "issuer"),
            "source": "opensanctions",
        })
    df = pl.DataFrame(rows, schema={c: pl.Utf8 for c in
        ["isin", "ticker", "figi", "issuer_name", "issuer_entity_id", "source"]})
    return df.filter(pl.col("isin").is_not_null())


def parse_entities(path: Path) -> pl.DataFrame:
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        ent = json.loads(line)
        p = ent.get("properties", {})
        rows.append({
            "entity_id": ent.get("id"),
            "name": _first(p, "name"),
            "lei": _first(p, "leiCode"),
            "country": _first(p, "country"),
            "topics": ",".join(p.get("topics", [])) or None,
        })
    return pl.DataFrame(rows, schema={c: pl.Utf8 for c in
        ["entity_id", "name", "lei", "country", "topics"]})


def parse_isin_lei(path: Path) -> pl.DataFrame:
    df = pl.read_csv(path)
    return df.rename({"LEI": "lei", "ISIN": "isin"}).select(["isin", "lei"])


def parse_rr(path: Path) -> pl.DataFrame:
    df = pl.read_csv(path)
    return df.select([
        pl.col("Relationship.EndNode.NodeID").alias("parent_lei"),
        pl.col("Relationship.StartNode.NodeID").alias("child_lei"),
        pl.col("Relationship.RelationshipType").alias("relation_type"),
    ])


def run(raw_dir: Path, interim_dir: Path) -> None:
    raw_dir, interim_dir = Path(raw_dir), Path(interim_dir)
    interim_dir.mkdir(parents=True, exist_ok=True)
    jobs = {
        "sanctioned_securities": parse_securities(raw_dir / "securities.ftm.json"),
        "sanctioned_entities": parse_entities(raw_dir / "entities.ftm.json"),
        "isin_to_lei": parse_isin_lei(raw_dir / "isin_lei.csv"),
        "lei_relations": parse_rr(raw_dir / "rr.csv"),
    }
    for name, df in jobs.items():
        df.write_parquet(interim_dir / f"{name}.parquet")
        log.metric("stage1", f"{name}_rows", df.height)
