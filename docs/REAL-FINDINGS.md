# Real-Data Findings — Sanctioned Securities Trading Radar

**Run date:** 2026-06-02 · **Data:** free only (OpenSanctions + GLEIF live API + OpenFIGI) ·
**Reproduce:** `scripts/real_report.py` → `scripts/step1_openfigi.py` →
`scripts/step2_traverse.py` → `scripts/final_consolidate.py` (outputs land in `data/out_real/`,
which is gitignored).

## Headline

The real, free-data intersection of sanctioned issuers with **US-tradeable bonds** is
**~33 securities** — small but real, and exactly the high-value compliance targets.

## Consolidated funnel

| Step | Count |
|------|------:|
| Sanctioned companies (OpenSanctions, `sanctioned=true`) | 11,689 |
| …with ≥1 ISIN | 338 |
| Distinct sanctioned ISINs | 9,705 |
| **US ISINs — direct layer** | **74** |
| …real bonds after OpenFIGI (ADRs/equity removed) | **22** |
| Sanctioned seed LEIs (ownership roots) | 590 |
| GLEIF descendant (subsidiary) LEIs | 117 |
| **US ISINs — indirect layer (subsidiary, hidden)** | **12** |
| …real bonds after OpenFIGI | **11** |
| **TOTAL US sanctioned bonds (direct + indirect)** | **33** |
| With a *free* FINRA trade signal (N7) | **0** (no free no-auth FINRA feed) |

## Step 1 — Direct layer (OpenSanctions + OpenFIGI)

Of 74 US sanctioned ISINs, OpenFIGI typed 51 (23 are delisted/matured with no active record).
**22 are real bonds:** PDVSA / Venezuela (13, Corp), Russian Ministry of Finance (6 sovereign,
Govt), plus LUKOIL, Credit Bank of Moscow, CNOOC, Development Bank of Belarus. The other 29
resolved as **Depositary Receipts** (Sberbank, VTB, China Mobile/Telecom/Unicom ADRs) — equity,
not TRACE debt — correctly excluded.

### Data-quality catch
The raw `securities.csv` initially suggested ~24,558 US ISINs, but those were dominated by
**non-sanctioned context companies** (TD Bank, Duke Energy, Northrop) carried in the file.
Filtering `sanctioned == true` gives the honest 74 → 22.

## Step 2 — Indirect layer (GLEIF ownership, the project's edge)

590 sanctioned seed LEIs → 42 have GLEIF children → 117 subsidiary LEIs → **12 US bonds
issued by subsidiaries that are NOT themselves on any sanctions list** (11 confirmed Corp
bonds). **Every one traces to CNOOC Limited** via subsidiaries such as **Nexen Inc**
(CUSIP `65334H…`) and **CNOOC Finance** (`12625G…`, `12591D…`). A direct name/ISIN search
misses all of them; the ownership chain surfaces them. This is the unique value the project
set out to demonstrate — and it works on real data.

## Step 3 — FINRA free-tier recon (the honest limit)

There is **no free, no-auth, machine-readable per-CUSIP trade endpoint**. `api.finra.org`
WAF-redirects unauthenticated calls; the Data API requires an OAuth2 account, and real-time /
End-of-Day trade files are paid ($1,500 / $750 per month). So **N7 = 0** via the free path —
empirically confirming the design's main risk. Proving these 33 bonds *currently trade*
requires either a free FINRA API account (then test whether aggregate datasets are
entitlement-free) or a paid TRACE feed. Full probe log: `data/out_real/step3_finra_recon.md`.

## Bottom line

- The chain **sanction → LEI → subsidiary → US bond** produces a concrete, defensible list of
  **33 securities** on free data.
- The intersection is **MARGINAL but non-zero** and concentrated in exactly the names
  compliance cares about (PDVSA, Russian sovereign, CNOOC subsidiaries).
- The only hard blocker to a live "is it trading right now" signal is **paid/authenticated
  FINRA TRACE** — a known, quantified cost decision, not a surprise.
