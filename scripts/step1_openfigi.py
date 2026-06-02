"""Step 1: classify the 74 US sanctioned ISINs via OpenFIGI into debt vs equity/ADR.

Uses the project's cached HTTP client. OpenFIGI free tier: ~25 req/min, 10 ISINs/req,
so 74 ISINs = 8 requests. Responses are disk-cached under data/cache_openfigi.
"""
import sys
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from radar.common.http import CachedClient  # noqa: E402
from radar.stage3_classify import is_debt_type, OPENFIGI_URL  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
OUT = Path("data/out_real")
cand = pl.read_csv(OUT / "candidates_us_direct.csv")
isins = cand["isin"].to_list()

client = CachedClient(cache_dir="data/cache_openfigi", min_interval=3.0)


def lookup(isins):
    """Return {isin: {securityType, securityType2, marketSector}} via OpenFIGI."""
    out = {}
    for i in range(0, len(isins), 10):
        chunk = isins[i:i + 10]
        body = [{"idType": "ID_ISIN", "idValue": x} for x in chunk]
        try:
            resp = client.post_json(OPENFIGI_URL, body=body)
        except Exception as exc:  # noqa: BLE001
            print(f"  batch {i//10} failed: {exc}", file=sys.stderr)
            continue
        if not isinstance(resp, list):
            print(f"  batch {i//10} unexpected: {resp}", file=sys.stderr)
            continue
        for isin, entry in zip(chunk, resp):
            data = entry.get("data") if isinstance(entry, dict) else None
            if data:
                d = data[0]
                out[isin] = {
                    "securityType": d.get("securityType"),
                    "securityType2": d.get("securityType2"),
                    "marketSector": d.get("marketSector"),
                }
        print(f"  batch {i//10}: {len([x for x in chunk if x in out])}/{len(chunk)} resolved")
    return out


print(f"Looking up {len(isins)} US ISINs via OpenFIGI ...")
types = lookup(isins)

rows = []
for r in cand.to_dicts():
    t = types.get(r["isin"], {})
    st2 = t.get("securityType2")
    sector = t.get("marketSector")
    is_bond = is_debt_type(st2)  # DEBT_TYPES match against securityType2
    rows.append({
        **r,
        "securityType": t.get("securityType"),
        "securityType2": st2,
        "marketSector": sector,
        "is_bond": is_bond,
    })
enriched = pl.DataFrame(rows)
enriched.write_csv(OUT / "candidates_us_typed.csv")

resolved = enriched.filter(pl.col("securityType2").is_not_null())
bonds = enriched.filter(pl.col("is_bond"))
print("\n================ RESULT ================")
print(f"US sanctioned ISINs                 : {enriched.height}")
print(f"  resolved by OpenFIGI              : {resolved.height}")
print(f"  classified as BOND/debt (TRACE)   : {bonds.height}")
print(f"  equity / ADR / other / unresolved : {enriched.height - bonds.height}")
print("\n--- breakdown by securityType2 ---")
for r in (enriched.group_by("securityType2").len().sort("len", descending=True)).to_dicts():
    print(f"  {str(r['securityType2']):<22} {r['len']}")
print("\n--- the real BONDS (TRACE-eligible sanctioned US debt) ---")
for r in bonds.sort(["country", "issuer"]).to_dicts():
    print(f"  {r['isin']}  {r['cusip']}  {str(r['securityType2']):<14} {r['country']:>5}  {str(r['issuer'])[:40]}")
print(f"\nwrote {OUT/'candidates_us_typed.csv'}")
