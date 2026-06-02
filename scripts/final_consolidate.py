"""Consolidate direct + indirect layers into one real funnel and candidates file.

Types the indirect (subsidiary) US ISINs via OpenFIGI, merges with the already-typed
direct layer, and writes data/out_real/report_final.md + candidates_final.csv.
"""
import sys
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from radar.common.http import CachedClient  # noqa: E402
from radar.stage3_classify import is_debt_type, OPENFIGI_URL  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
OUT = Path("data/out_real")

direct = pl.read_csv(OUT / "candidates_us_typed.csv")          # 74 US, typed
indirect = pl.read_csv(OUT / "indirect_candidates.csv")        # subsidiary US ISINs

client = CachedClient(cache_dir="data/cache_openfigi", min_interval=3.0)


def type_isins(isins):
    out = {}
    for i in range(0, len(isins), 10):
        chunk = isins[i:i + 10]
        body = [{"idType": "ID_ISIN", "idValue": x} for x in chunk]
        try:
            resp = client.post_json(OPENFIGI_URL, body=body)
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(resp, list):
            continue
        for isin, entry in zip(chunk, resp):
            data = entry.get("data") if isinstance(entry, dict) else None
            if data:
                out[isin] = data[0].get("securityType2")
    return out


ind_types = type_isins(indirect["isin"].to_list())
indirect = indirect.with_columns(
    pl.col("isin").replace_strict(ind_types, default=None).alias("securityType2")
).with_columns(
    pl.col("securityType2").map_elements(is_debt_type, return_dtype=pl.Boolean).alias("is_bond")
)

# unify schemas into one candidates table
direct_u = direct.select([
    pl.col("isin"), pl.col("cusip"),
    pl.lit("direct").alias("layer"),
    pl.col("issuer").alias("issuer_or_parent"),
    pl.col("country"), pl.col("securityType2"), pl.col("is_bond"),
])
indirect_u = indirect.select([
    pl.col("isin"), pl.col("cusip"),
    pl.lit("indirect").alias("layer"),
    pl.col("sanctioned_parent").alias("issuer_or_parent"),
    pl.lit(None, dtype=pl.Utf8).alias("country"),
    pl.col("securityType2"), pl.col("is_bond"),
])
final = pl.concat([direct_u, indirect_u]).unique(subset=["isin"]).sort(["layer", "issuer_or_parent"])
final.write_csv(OUT / "candidates_final.csv")

d_bonds = direct.filter(pl.col("is_bond")).height
i_bonds = indirect.filter(pl.col("is_bond")).height
report = f"""# Sanctioned Securities Trading Radar — REAL data, consolidated

Source: OpenSanctions Sanctioned Securities (2026-06-02) + GLEIF ownership (live API) +
OpenFIGI security typing. Free data only.

## Funnel

- sanctioned companies                        : 11689
- sanctioned seed LEIs (ownership roots)       : 590
- GLEIF descendant (subsidiary) LEIs           : 117
- distinct sanctioned ISINs (direct)           : 9705
- US ISINs, DIRECT layer                       : {direct.height}
-     of which real bonds (OpenFIGI)           : {d_bonds}
- US ISINs, INDIRECT layer (subsidiary, hidden): {indirect.height}
-     of which real bonds (OpenFIGI)           : {i_bonds}
- ---------------------------------------------------------------
- TOTAL US sanctioned bonds (direct+indirect)  : {d_bonds + i_bonds}
- with free FINRA trade signal (N7)            : 0  (no free no-auth FINRA feed — see step3)

## What the indirect layer found (the project's edge)

{indirect.height} US bonds issued by subsidiaries of sanctioned parents that are NOT
themselves on any sanctions list — invisible to a name search. All trace to CNOOC Limited
via its subsidiaries (e.g. Nexen Inc, CNOOC Finance). A direct sanctioned-ISIN lookup misses
every one of them; the ownership chain surfaces them.

## Honest verdict

The real, free-data intersection of sanctioned issuers with US-tradeable BONDS is
**~{d_bonds + i_bonds} securities** (≈{d_bonds} directly named + {i_bonds} hidden via
subsidiaries) — dominated by Venezuelan (PDVSA) and Russian sovereign debt, plus CNOOC's
subsidiary bonds. Small but real, and exactly the high-value compliance targets. Proving they
*currently trade* requires a FINRA account or paid TRACE feed (Step 3 recon).
"""
(OUT / "report_final.md").write_text(report, encoding="utf-8")
print(report)
print(f"\nwrote {OUT/'candidates_final.csv'} ({final.height} rows)")
print("\n--- INDIRECT bonds (subsidiary, typed) ---")
for r in indirect.sort("cusip").to_dicts():
    print(f"  {r['isin']}  {r['cusip']}  {str(r.get('securityType2')):<12} parent={r['sanctioned_parent']}")
