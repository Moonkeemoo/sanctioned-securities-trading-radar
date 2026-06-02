"""Step 2: GLEIF subsidiary traversal — find US bonds issued by subsidiaries of
sanctioned parents that are NOT themselves on the sanctions list (the indirect layer).

For each sanctioned seed LEI: fetch ultimate-children (the whole owned subtree), then
each child's ISINs; keep US ISINs not already in the sanctioned set. Disk-cached and
resumable: re-running reuses cached GLEIF responses.
"""
import sys
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from radar.common.http import CachedClient  # noqa: E402
from radar.common.ids import us_isin_to_cusip  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
OUT = Path("data/out_real")
GLEIF = "https://api.gleif.org/api/v1/lei-records"
client = CachedClient(cache_dir="data/cache_gleif", min_interval=0.7)

df = pl.read_csv("data/raw_real/securities.csv", infer_schema_length=20000)


def truthy(col):
    return pl.col(col).cast(pl.Utf8).str.to_lowercase().is_in(["true", "1", "t", "yes"])


sanc = df.filter(truthy("sanctioned"))
# the lei column can itself be a ';'-separated list; explode and keep valid 20-char LEIs
seeds = (sanc.filter((pl.col("lei").is_not_null()) & (pl.col("lei") != ""))
         .with_columns(pl.col("lei").str.split(";").alias("lei1"))
         .explode("lei1")
         .with_columns(pl.col("lei1").str.strip_chars().alias("lei_one"))
         .filter(pl.col("lei_one").str.len_chars() == 20)
         .select(["caption", "lei_one"]).rename({"lei_one": "lei"})
         .unique(subset=["lei"]))
seed_leis = set(seeds["lei"].to_list())
seed_name = {r["lei"]: r["caption"] for r in seeds.to_dicts()}

# sanctioned ISIN set (to mark a found ISIN as already-direct vs truly indirect)
ex = (sanc.filter((pl.col("isins").is_not_null()) & (pl.col("isins") != ""))
      .with_columns(pl.col("isins").str.split(";").alias("isin")).explode("isin")
      .with_columns(pl.col("isin").str.strip_chars()))
sanctioned_isins = set(ex["isin"].to_list())


def paged(url, params=None):
    """Yield all data items across JSON:API pages."""
    params = dict(params or {})
    params.setdefault("page[size]", 200)
    seen = 0
    while url:
        resp = client.get_json(url, params=params)
        for item in resp.get("data", []):
            yield item
            seen += 1
        url = (resp.get("links", {}) or {}).get("next")
        params = None  # next link already encodes params
        if seen > 5000:  # safety cap per seed
            break


# Phase A: collect descendant LEIs per seed (ultimate-children = whole subtree)
descendants = {}  # child_lei -> root seed lei
seeds_with_children = 0
seed_errors = 0
for i, lei in enumerate(seed_leis, 1):
    n = 0
    try:
        for item in paged(f"{GLEIF}/{lei}/ultimate-children"):
            child = item.get("id") if isinstance(item, dict) else None
            if child and child not in seed_leis:
                descendants.setdefault(child, lei)
                n += 1
    except Exception:  # noqa: BLE001 — skip a bad/unknown LEI, keep going
        seed_errors += 1
    if n:
        seeds_with_children += 1
    if i % 50 == 0:
        print(f"  [A] {i}/{len(seed_leis)} seeds, {len(descendants)} descendants, {seed_errors} errors",
              flush=True)
print(f"[A] done: {seeds_with_children} seeds have children; {len(descendants)} descendant LEIs; "
      f"{seed_errors} seed errors")

# Phase B: ISINs of each descendant; keep US ISINs not already sanctioned
rows = []
for j, (child, root) in enumerate(descendants.items(), 1):
    try:
        items = list(paged(f"{GLEIF}/{child}/isins"))
    except Exception:  # noqa: BLE001
        items = []
    for item in items:
        if not isinstance(item, dict):
            continue
        isin = (item.get("attributes", {}) or {}).get("isin") or item.get("id")
        if not isin or not isin.startswith("US"):
            continue
        if isin in sanctioned_isins:
            continue  # already counted in the direct layer
        try:
            cusip = us_isin_to_cusip(isin)
        except ValueError:
            cusip = None
        rows.append({"isin": isin, "cusip": cusip, "subsidiary_lei": child,
                     "sanctioned_parent_lei": root,
                     "sanctioned_parent": str(seed_name.get(root, ""))[:60]})
    if j % 50 == 0:
        print(f"  [B] {j}/{len(descendants)} descendants processed, {len(rows)} indirect US ISINs",
              flush=True)

out = pl.DataFrame(rows, schema={c: pl.Utf8 for c in
                   ["isin", "cusip", "subsidiary_lei", "sanctioned_parent_lei", "sanctioned_parent"]})
out = out.unique(subset=["isin"])
out.write_csv(OUT / "indirect_candidates.csv")
print("\n================ STEP 2 RESULT ================")
print(f"sanctioned seed LEIs                 : {len(seed_leis)}")
print(f"seeds with GLEIF children            : {seeds_with_children}")
print(f"descendant (subsidiary) LEIs         : {len(descendants)}")
print(f"INDIRECT US ISINs (not directly listed): {out.height}")
print(f"  with valid CUSIP                   : {out.filter(pl.col('cusip').is_not_null()).height}")
print(f"wrote {OUT/'indirect_candidates.csv'}")
if out.height:
    print("\n--- sample indirect US ISINs (subsidiary bonds of sanctioned parents) ---")
    for r in out.head(20).to_dicts():
        print(f"  {r['isin']}  {r['cusip']}  parent={r['sanctioned_parent']}")
