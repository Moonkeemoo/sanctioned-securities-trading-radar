"""Step 2 explore: count sanctioned seed LEIs and probe the GLEIF API shape."""
import sys
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from radar.common.http import CachedClient  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")

df = pl.read_csv("data/raw_real/securities.csv", infer_schema_length=20000)


def truthy(col):
    return pl.col(col).cast(pl.Utf8).str.to_lowercase().is_in(["true", "1", "t", "yes"])


sanc = df.filter(truthy("sanctioned"))
seeds = (sanc.filter((pl.col("lei").is_not_null()) & (pl.col("lei") != ""))
         .select(["caption", "lei"]).unique(subset=["lei"]))
print(f"sanctioned companies                 : {sanc.height}")
print(f"  with a LEI (ownership seeds)        : {seeds.height}")

client = CachedClient(cache_dir="data/cache_gleif", min_interval=1.0)
GLEIF = "https://api.gleif.org/api/v1/lei-records"

# probe a few seeds for the relationship + isin endpoints
for r in seeds.head(6).to_dicts():
    lei = r["lei"]
    name = str(r["caption"])[:38]
    try:
        dc = client.get_json(f"{GLEIF}/{lei}/direct-children", params={"page[size]": 100})
        uc = client.get_json(f"{GLEIF}/{lei}/ultimate-children", params={"page[size]": 100})
        isn = client.get_json(f"{GLEIF}/{lei}/isins", params={"page[size]": 100})
        n_dc = (dc.get("meta", {}).get("pagination", {}) or {}).get("total", len(dc.get("data", [])))
        n_uc = (uc.get("meta", {}).get("pagination", {}) or {}).get("total", len(uc.get("data", [])))
        n_isin = (isn.get("meta", {}).get("pagination", {}) or {}).get("total", len(isn.get("data", [])))
        print(f"  {lei}  dc={n_dc:<4} uc={n_uc:<4} isins={n_isin:<4}  {name}")
    except Exception as exc:  # noqa: BLE001
        print(f"  {lei}  ERROR {exc}  {name}")
