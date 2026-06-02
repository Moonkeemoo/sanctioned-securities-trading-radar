import polars as pl

df = pl.read_csv("data/raw_real/securities.csv")
print("shape:", df.shape)
sub = df.filter((pl.col("lei").is_not_null()) & (pl.col("isins").is_not_null()) & (pl.col("isins") != ""))
print("rows with lei AND isins:", sub.height)
print("rows with isins (any):", df.filter((pl.col("isins").is_not_null()) & (pl.col("isins") != "")).height)
print("rows with lei (any):", df.filter(pl.col("lei").is_not_null()).height)
print("--- sample rows (caption | lei | countries | isins) ---")
for r in sub.select(["caption", "lei", "isins", "countries"]).head(5).to_dicts():
    print(repr(r["caption"][:35]), "|", r["lei"], "|", r["countries"], "|", repr(r["isins"][:160]))
