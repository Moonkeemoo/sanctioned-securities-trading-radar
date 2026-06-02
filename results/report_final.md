# Sanctioned Securities Trading Radar — REAL data, consolidated

Source: OpenSanctions Sanctioned Securities (2026-06-02) + GLEIF ownership (live API) +
OpenFIGI security typing. Free data only.

## Funnel

- sanctioned companies                        : 11689
- sanctioned seed LEIs (ownership roots)       : 590
- GLEIF descendant (subsidiary) LEIs           : 117
- distinct sanctioned ISINs (direct)           : 9705
- US ISINs, DIRECT layer                       : 74
-     of which real bonds (OpenFIGI)           : 22
- US ISINs, INDIRECT layer (subsidiary, hidden): 12
-     of which real bonds (OpenFIGI)           : 11
- ---------------------------------------------------------------
- TOTAL US sanctioned bonds (direct+indirect)  : 33
- with free FINRA trade signal (N7)            : 0  (no free no-auth FINRA feed — see step3)

## What the indirect layer found (the project's edge)

12 US bonds issued by subsidiaries of sanctioned parents that are NOT
themselves on any sanctions list — invisible to a name search. All trace to CNOOC Limited
via its subsidiaries (e.g. Nexen Inc, CNOOC Finance). A direct sanctioned-ISIN lookup misses
every one of them; the ownership chain surfaces them.

## Honest verdict

The real, free-data intersection of sanctioned issuers with US-tradeable BONDS is
**~33 securities** (≈22 directly named + 11 hidden via
subsidiaries) — dominated by Venezuelan (PDVSA) and Russian sovereign debt, plus CNOOC's
subsidiary bonds. Small but real, and exactly the high-value compliance targets. Proving they
*currently trade* requires a FINRA account or paid TRACE feed (Step 3 recon).
