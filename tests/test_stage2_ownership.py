from radar.stage2_ownership import descendants, build_candidates, traverse
import polars as pl

def test_descendants_transitive():
    relations = [("P", "A"), ("A", "B"), ("B", "C")]  # (parent, child)
    assert descendants({"P"}, relations, max_depth=10) == {"A", "B", "C"}

def test_descendants_depth_bound():
    relations = [("P", "A"), ("A", "B"), ("B", "C")]
    assert descendants({"P"}, relations, max_depth=2) == {"A", "B"}

def test_descendants_cycle_safe():
    relations = [("P", "A"), ("A", "P")]  # cycle
    assert descendants({"P"}, relations, max_depth=10) == {"A"}

def test_build_candidates_tags_direct_and_indirect():
    seed_leis = {"P"}
    relations = [("P", "SUB")]
    isin_to_lei = pl.DataFrame({"isin": ["US0378331005", "US5949181045"],
                                "lei": ["P", "SUB"]})
    sanctioned_isins = {"US0378331005"}  # only the parent's own bond is directly listed
    out = build_candidates(seed_leis, relations, isin_to_lei, sanctioned_isins, max_depth=5)
    rows = {r["isin"]: r for r in out.to_dicts()}
    assert rows["US0378331005"]["tag"] == "direct"
    assert rows["US5949181045"]["tag"] == "indirect"   # subsidiary bond, not listed
    assert rows["US5949181045"]["issuer_lei"] == "SUB"

def test_traverse_records_depth_and_root():
    relations = [("P", "A"), ("A", "B"), ("B", "C")]
    out = traverse({"P"}, relations, max_depth=10)
    assert out == {"A": (1, "P"), "B": (2, "P"), "C": (3, "P")}

def test_traverse_attributes_correct_seed_multi():
    seeds = {"ALPHA", "BRAVO"}
    relations = [("BRAVO", "SUB")]
    out = traverse(seeds, relations, max_depth=5)
    assert out["SUB"] == (1, "BRAVO")  # attributed to the real parent, not an arbitrary seed

def test_build_candidates_root_and_depth_multi_seed():
    seed_leis = {"ALPHA", "BRAVO"}
    relations = [("BRAVO", "SUB")]
    isin_to_lei = pl.DataFrame({"isin": ["XUSBOND0001"], "lei": ["SUB"]})
    out = build_candidates(seed_leis, relations, isin_to_lei, set(), max_depth=5)
    row = out.to_dicts()[0]
    assert row["root_sanctioned_lei"] == "BRAVO"
    assert row["path_depth"] == 1
    assert row["tag"] == "indirect"
