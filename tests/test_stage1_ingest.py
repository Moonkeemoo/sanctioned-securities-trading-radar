from pathlib import Path
import polars as pl
from radar.stage1_ingest import (
    parse_securities, parse_entities, parse_isin_lei, parse_rr,
)

FIX = Path(__file__).parent / "fixtures"

def test_parse_securities_extracts_first_isin_and_issuer():
    df = parse_securities(FIX / "opensanctions_securities.ftm.json")
    row = df.filter(pl.col("isin") == "US0378331005").to_dicts()[0]
    assert row["security_name"] == "ACME Bond 2030"
    assert row["issuer_entity_id"] == "ent-acme"
    assert row["figi"] == "BBG000000001"

def test_parse_securities_handles_missing_issuer():
    df = parse_securities(FIX / "opensanctions_securities.ftm.json")
    row = df.filter(pl.col("isin") == "XS1234567890").to_dicts()[0]
    assert row["issuer_entity_id"] is None

def test_parse_entities_extracts_lei():
    df = parse_entities(FIX / "opensanctions_entities.ftm.json")
    assert df.filter(pl.col("entity_id") == "ent-acme")["lei"][0] == "5493000000000000ACME"
    assert df.filter(pl.col("entity_id") == "ent-nolei")["lei"][0] is None

def test_parse_isin_lei():
    df = parse_isin_lei(FIX / "gleif_isin_lei.csv")
    assert set(df.columns) == {"isin", "lei"}
    assert df.height == 2

def test_parse_rr_direction_parent_is_endnode():
    df = parse_rr(FIX / "gleif_rr.csv")
    row = df.to_dicts()[0]
    assert row["parent_lei"] == "5493000000000000ACME"   # EndNode = parent
    assert row["child_lei"] == "5493000000000000SUB1"     # StartNode = child
