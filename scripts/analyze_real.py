"""Quick real-data reconnaissance over OpenSanctions securities.csv (no network)."""
import polars as pl

df = pl.read_csv("data/raw_real/securities.csv")

# explode the ';'-separated isins list into one row per (company, isin)
ex = (df
      .filter((pl.col("isins").is_not_null()) & (pl.col("isins") != ""))
      .with_columns(pl.col("isins").str.split(";").alias("isin"))
      .explode("isin")
      .with_columns(pl.col("isin").str.strip_chars())
      .filter(pl.col("isin") != ""))

total_isin_rows = ex.height
uniq_isins = ex.select("isin").n_unique()
print(f"sanctioned companies total            : {df.height}")
print(f"companies WITH >=1 ISIN               : {df.filter((pl.col('isins').is_not_null()) & (pl.col('isins') != '')).height}")
print(f"(company, ISIN) pairs                 : {total_isin_rows}")
print(f"distinct sanctioned ISINs             : {uniq_isins}")

# country of issue = first 2 chars of ISIN
ex = ex.with_columns(pl.col("isin").str.slice(0, 2).alias("isin_cc"))
by_cc = (ex.group_by("isin_cc").agg(pl.col("isin").n_unique().alias("n"))
         .sort("n", descending=True))
print("\n--- distinct sanctioned ISINs by ISIN country prefix (top 12) ---")
for r in by_cc.head(12).to_dicts():
    print(f"  {r['isin_cc']}: {r['n']}")

us = ex.filter(pl.col("isin_cc") == "US")
print(f"\nUS-prefixed distinct sanctioned ISINs : {us.select('isin').n_unique()}")
print(f"  issued by # distinct companies      : {us.select('caption').n_unique()}")
print(f"  of those companies, # with LEI      : {us.filter(pl.col('lei').is_not_null() & (pl.col('lei') != '')).select('caption').n_unique()}")

print("\n--- top US-bond issuers among sanctioned companies (by # US ISINs) ---")
top = (us.group_by("caption").agg(pl.col("isin").n_unique().alias("us_isins"))
       .sort("us_isins", descending=True).head(12))
for r in top.to_dicts():
    print(f"  {r['us_isins']:>4}  {r['caption'][:55]}")
