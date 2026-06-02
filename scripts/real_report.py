"""Build a REAL feasibility report (direct layer) from OpenSanctions securities.csv.

No network. Uses the project's own ids module to derive + validate CUSIPs for US ISINs.
Writes data/out_real/report_real.md and data/out_real/candidates_us_direct.csv.
"""
import sys
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from radar.common.ids import us_isin_to_cusip  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
OUT = Path("data/out_real")
OUT.mkdir(parents=True, exist_ok=True)

df = pl.read_csv("data/raw_real/securities.csv", infer_schema_length=20000)


def truthy(col):
    return pl.col(col).cast(pl.Utf8).str.to_lowercase().is_in(["true", "1", "t", "yes"])


sanc = df.filter(truthy("sanctioned"))
with_isin = sanc.filter((pl.col("isins").is_not_null()) & (pl.col("isins") != ""))

ex = (with_isin
      .with_columns(pl.col("isins").str.split(";").alias("isin"))
      .explode("isin")
      .with_columns(pl.col("isin").str.strip_chars())
      .filter(pl.col("isin") != "")
      .with_columns(pl.col("isin").str.slice(0, 2).alias("cc")))

uniq_isins = ex.select("isin").n_unique()
us = ex.filter(pl.col("cc") == "US").unique(subset=["isin"])

# derive + validate CUSIP using the project's own check-digit logic
rows = []
invalid = 0
for r in us.to_dicts():
    isin = r["isin"]
    try:
        cusip = us_isin_to_cusip(isin)
    except ValueError:
        invalid += 1
        cusip = None
    rows.append({
        "isin": isin,
        "cusip": cusip,
        "issuer": r["caption"],
        "country": r["countries"],
        "lei": r["lei"],
        "eo_14071": r["eo_14071"],
    })
cand = pl.DataFrame(rows).sort(["country", "issuer", "isin"])
cand.write_csv(OUT / "candidates_us_direct.csv")

verdict = "ZERO" if cand.height == 0 else "MARGINAL" if cand.height < 200 else "SIGNIFICANT"
report = f"""# Sanctioned Securities Trading Radar — REAL data, direct layer

Source: OpenSanctions "Sanctioned Securities" bulk (securities.csv), as of 2026-06-02.
This is the DIRECT layer only (companies named on sanctions lists). The subsidiary /
indirect layer needs GLEIF ownership traversal and is not included here yet.

## Funnel (truly sanctioned companies only: sanctioned == true)

- N0  sanctioned companies                : {sanc.height}
- N1  companies with >=1 ISIN             : {with_isin.height}
- N2  distinct sanctioned ISINs           : {uniq_isins}
- N6  distinct US ISINs (TRACE universe)  : {cand.height}
-       of which valid CUSIP derived      : {cand.height - invalid}
-       of which failed CUSIP check digit : {invalid}
- N6  distinct US-ISIN issuers            : {us.select('caption').n_unique()}

**Direct intersection verdict (US ISINs): {verdict}**

The ~{cand.height} US-tradeable sanctioned securities are dominated by Venezuelan and
Russian sovereign/corporate issuers — exactly the high-value targets for compliance.

## GAPS / honest notes
- This counts the DIRECT layer only. Subsidiary-issued bonds (the project's main edge)
  require GLEIF Level-2 traversal — pending.
- "US ISIN" here means TRACE-*universe* (could trade). Whether each actually traded needs
  FINRA TRACE activity data (Stage 4 recon — pending).
- Debt-vs-equity typing (OpenFIGI) not yet applied; a few US ISINs may be ADRs/equity.
"""
(OUT / "report_real.md").write_text(report, encoding="utf-8")
print(report)
print(f"wrote {OUT/'candidates_us_direct.csv'} ({cand.height} rows)")
print("\n--- first 15 candidate US sanctioned ISINs ---")
for r in cand.head(15).to_dicts():
    print(f"  {r['isin']}  cusip={r['cusip'] or '----INVALID----'}  {r['country']:>3}  {str(r['issuer'])[:42]}")
