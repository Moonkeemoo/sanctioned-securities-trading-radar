"""Split sanctioned-securities reconnaissance by the sanctioned / eo_14071 flags."""
import sys
import polars as pl

sys.stdout.reconfigure(encoding="utf-8")

df = pl.read_csv("data/raw_real/securities.csv", infer_schema_length=20000)
print("flag value counts:")
for col in ["sanctioned", "eo_14071", "public"]:
    print(f"  {col}:", df[col].value_counts().sort(col).to_dicts())

def explode(d):
    return (d.filter((pl.col("isins").is_not_null()) & (pl.col("isins") != ""))
            .with_columns(pl.col("isins").str.split(";").alias("isin"))
            .explode("isin")
            .with_columns(pl.col("isin").str.strip_chars())
            .filter(pl.col("isin") != "")
            .with_columns(pl.col("isin").str.slice(0, 2).alias("cc")))

def report(name, d):
    ex = explode(d)
    us = ex.filter(pl.col("cc") == "US")
    print(f"\n=== {name}: {d.height} companies ===")
    print(f"  distinct ISINs        : {ex.select('isin').n_unique()}")
    print(f"  distinct US ISINs     : {us.select('isin').n_unique()}")
    print(f"  US-ISIN issuers       : {us.select('caption').n_unique()}")
    top = (us.group_by("caption").agg(pl.col("isin").n_unique().alias("n"))
           .sort("n", descending=True).head(8))
    for r in top.to_dicts():
        print(f"     {r['n']:>5}  {r['caption'][:50]}")

# normalize booleans (may be 'true'/'false' strings or bools)
def truthy(col):
    return (pl.col(col).cast(pl.Utf8).str.to_lowercase().is_in(["true", "1", "t", "yes"]))

report("sanctioned == true", df.filter(truthy("sanctioned")))
report("eo_14071 == true (Russian investment ban)", df.filter(truthy("eo_14071")))
report("sanctioned==true AND NOT eo_14071", df.filter(truthy("sanctioned") & ~truthy("eo_14071")))
