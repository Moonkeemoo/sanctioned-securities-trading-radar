# Step 3 — FINRA TRACE free-tier recon (findings)

Date: 2026-06-02. Goal: does a **free, machine-readable, no-auth** FINRA endpoint return
trade activity for a given bond CUSIP (e.g. PDVSA `716558AC5`, Russian MinFin `78307AAE3`)?

## What was probed

| Probe | Endpoint | Result |
|------|----------|--------|
| A | `api.finra.org/data/group/otcMarket/name/...` (no auth) | **307 → `error.waf.finra.org`** (WAF blocks unauthenticated access) |
| B | `ews.fip.finra.org/.../oauth2/access_token` | **405** on GET — OAuth2 `client_credentials` flow required (needs a FINRA API account) |
| C | `api.finra.org/data/group/otcMarket` metadata (no auth) | redirect, empty body |
| D | `finra.org/finra-data/fixed-income/...` | **307** (restructured / WAF) |
| E | legacy `services-finra.morningstar.com` bond center | **000 / 404** (service retired) |

## Conclusion

**There is no free, no-auth, machine-readable per-CUSIP trade endpoint.** This empirically
confirms the design's main risk (critic concern #2): the "free skeleton" does **not** extend
to a machine-readable trading signal.

Access to the FINRA Data API (`api.finra.org`) requires:
1. A **free FINRA API account** → OAuth2 client credentials (interactive registration), and
2. even then, transaction-level TRACE datasets need entitlement; the real-time and
   End-of-Day trade files are the **paid** products ($1,500/mo and $750/mo).

The genuinely free surfaces (web TRACE display, monthly TSAR aggregates) are either
JS-rendered web pages or sit behind the account/WAF — not a clean machine feed.

## Effect on the funnel

`N7` (candidates with a *free* trading-activity signal) is **not achievable via a no-auth
free path**. This is recorded as a GAP — and it is itself a valid feasibility result:
to prove these 22 sanctioned US bonds actually trade, you need either a free FINRA API
account (then test whether aggregate datasets are entitlement-free) or a paid TRACE feed.

## Actionable next steps (require the user / a decision)

1. **Register a free FINRA API account** at the FINRA API portal, obtain OAuth2
   client credentials, then re-probe whether any TRACE *aggregate* dataset (e.g. weekly/
   monthly summaries) is accessible without paid entitlement. If yes, wire those credentials
   into `stage4_activity` and populate `FINRA_RECON_ENDPOINTS`.
2. If a real, current trade signal is required, budget for the **End-of-Day Transaction
   File ($750/mo)** or **real-time feed ($1,500/mo)**.
3. Interim free proxy: the FINRA TRACE web display can confirm *by hand* whether a specific
   CUSIP shows recent trades — useful for spot-checking the top candidates (PDVSA, Russian
   sovereign) but not a scalable feed.
