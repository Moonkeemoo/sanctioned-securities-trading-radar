# Sanctioned Securities Trading Radar — Feasibility Spike (Design)

- **Date:** 2026-06-02
- **Project ID:** sanctioned-securities-trading-radar
- **Status:** Design approved (brainstorming), pending implementation plan
- **Scope of THIS spec:** A **feasibility spike**, not a production monitoring service.

## 1. Problem & Hypothesis

The product idea: detect securities of sanctioned issuers that are *still trading* on US
markets — including bonds issued indirectly through **subsidiaries** of sanctioned parent
groups — by stitching together:

- a sanctioned-securities register (**OpenSanctions**, by ISIN),
- the corporate ownership chain (**GLEIF** LEI parent/child, ISIN↔LEI),
- and real US bond trades (**FINRA TRACE**).

The critic's verdict on the idea is **"maybe"**, for concrete reasons this spike must
resolve *before* any money is spent:

1. **Unverified core intersection.** It is unknown how many sanctioned ISINs are actually
   US bonds that report to TRACE. The set may be large — or near zero. Most of the ~453k
   sanctioned securities may be equities or non-US paper that TRACE never sees.
2. **"Free skeleton" is overstated for monitoring.** FINRA TRACE's free tier gives web
   displays and monthly aggregates (TSAR), not a machine-readable daily/real-time trade
   feed (those cost $750–1500/mo). Real-time *monitoring* is not free.
3. **Join-key reality.** TRACE's primary identifier is CUSIP, not ISIN. ISIN↔CUSIP is
   1:1 *only* for US securities (US ISIN = `US` + CUSIP + check digit). Non-US ISINs
   (Yankee/144A) need extra mapping.
4. **LEI coverage is partial.** Not every sanctioned issuer has an LEI, so some ownership
   chains will break.

**Hypothesis under test:** *There exists a non-trivial set of sanctioned (directly or via
subsidiary) ISINs that are US-tradeable bonds, for which at least some free trading-activity
signal is observable.*

**This spike answers, cheaply and on free data only, whether the full service is worth
building** — and quantifies every place the free path breaks rather than hiding it.

### Goal of the first iteration (decided)
- Build a **feasibility spike on free data**.
- **Stack: Python.**
- **Proof level: both** — *tradeability* (is the ISIN a US bond in the TRACE universe?)
  **and** *free activity signals* (did it trade recently, per any free FINRA source?).

### Explicit non-goals (YAGNI)
- No paid TRACE feeds (real-time, End-of-Day file, Enhanced Historical).
- No real-time monitoring, alerting, scheduler, hosted database service, or web UI.
  (DuckDB is used as an *embedded* library for local processing, not as a running service.)
- No MSRB EMMA / municipal securities, no `nbu-statistics` (the critic correctly flagged
  the latter as unexplained filler).
- No commercial OpenSanctions API usage — bulk dump only (CC BY-NC, non-commercial).

## 2. Architecture

A **linear pipeline of 5 stage-modules** (approach A). Each stage reads its input, writes a
Parquet artifact to `data/interim/` via DuckDB, and is independently re-runnable. A thin
`run.py` orchestrates; stages can also run standalone for inspection.

```
src/radar/
  stage1_ingest.py        # download + parse bulk dumps into normalized tables
  stage2_ownership.py     # build LEI parent->child graph; mark direct/indirect ISINs
  stage3_classify.py      # which ISINs are US bonds / TRACE-eligible (type + ISIN/CUSIP)
  stage4_activity.py      # free FINRA activity signals for candidates
  stage5_report.py        # funnel report + ranked candidates.csv
  common/
    http.py               # cached HTTP client (disk cache, rate-limit, retry)
    ids.py                # isin<->cusip, isin validation, check digits
    schemas.py            # table column contracts (one place)
    log.py                # structured per-stage metrics logging
  run.py                  # orchestrator
data/
  raw/        # immutable bulk dumps (gitignored)
  interim/    # parquet between stages (gitignored)
  out/        # report.md + candidates.csv (committed as evidence, optional)
tests/
docs/
```

**Data flow:**

```
OpenSanctions bulk ─┐
                    ├─→ stage1 → sanctioned_securities, sanctioned_entities
GLEIF ISIN→LEI bulk ┤            (isin, issuer, lei, figi, ticker)
GLEIF Level-2 bulk ─┘
                                   │
                    stage2 → ownership graph (parent_lei→child_lei, transitive,
                             depth-bounded, cycle-safe) → candidate ISINs tagged
                             direct | indirect
                                   │
                    stage3 → classify: debt vs equity (OpenFIGI); US vs non-US;
                             TRACE-eligible? derive CUSIP for US ISINs
                                   │
                    stage4 → for candidates: probe FREE FINRA signals
                             (recon first, then batch); record provenance
                                   │
                    stage5 → funnel of counts + ranked "live" candidates + GAPS section
```

### Stage contracts

**Stage 1 — Ingest** (all free, bulk, no API key)
- Inputs: OpenSanctions "Sanctioned Securities" (Security schema, ~453k, daily, CC BY-NC)
  + a sanctioned legal-entity dataset (Consolidated Sanctions / Companies) for `leiCode`;
  GLEIF ISIN-to-LEI mapping (bulk CSV); GLEIF Level-2 relationship records (bulk).
- Outputs:
  - `sanctioned_securities(isin, ticker, figi, security_name, issuer_entity_id, source)`
  - `sanctioned_entities(entity_id, name, lei, country, topics)`
  - `isin_to_lei(isin, lei)` (GLEIF, world)
  - `lei_relations(parent_lei, child_lei, relation_type)` (GLEIF Level-2)
- Idempotent: bulk dumps cached in `data/raw/`, pulled once. Logs row counts.

**Stage 2 — Ownership graph** (the investigative edge)
- Seed set = sanctioned LEIs (from `sanctioned_entities.lei`) ∪ LEIs of issuers of
  sanctioned ISINs (resolved via GLEIF `isin_to_lei`).
  **Robustness note:** the seed must NOT depend on an OpenSanctions Security→issuer link
  (its presence in the bulk dump is not guaranteed). Issuer LEIs are derived primarily
  from GLEIF `isin_to_lei`, so the chain holds even when that link is absent.
- Traverse `lei_relations` **downward** (parent→children), transitively, with a
  configurable max depth and cycle protection → set of descendant LEIs.
- Via `isin_to_lei`, collect all ISINs issued by {seed ∪ descendant} LEIs.
- Tag each ISIN `direct` (present in sanctioned securities list) or `indirect`
  (subsidiary-issued, not itself named) — **indirect is the core value**.
- Output: `candidate_isins(isin, issuer_lei, root_sanctioned_lei, path_depth, tag)`.
- Logs: seed LEI count, descendant count, direct vs indirect ISIN counts, chains broken
  by missing LEI.

**Stage 3 — Classify US bonds / TRACE-eligibility**
- For each candidate ISIN:
  - `is_us = isin.startswith("US")`; if US, derive CUSIP (strip `US` + recompute/validate
    check digit) → addresses the CUSIP-vs-ISIN critique for US paper.
  - Security type via **OpenFIGI API** (free, rate-limited): keep debt (bond/note),
    drop equities — TRACE is debt only. This directly *measures* critique #1 instead of
    assuming it.
  - Non-US ISINs (Yankee/144A that may still trade on TRACE) flagged separately; CUSIP
    mapping for them is a known GAP (OpenFIGI within free limits where possible).
- Output: `classified(isin, is_us, cusip, security_type, trace_eligible_guess, gap_reason)`.

**Stage 4 — Free activity signals**
- The exact behavior of FINRA's free tier is the main **known unknown**. Stage 4:
  1. **Recon**: probe 1–2 free FINRA endpoints (free FINRA Data API / Bond Center / TSAR
     monthly aggregates) on a handful of *known* US corporate-bond ISINs to learn what is
     actually queryable for free, recording exact request/response shape.
  2. **Batch**: apply the confirmed method to TRACE-eligible candidates.
  3. If **no** machine-readable free path exists at all, that is itself a spike result
     (confirms critique #2) — documented in GAPS, not hidden.
- Output: `activity(isin, signal_kind, signal_value, observed_period, source_url, fetched_at)`.

**Stage 5 — Report**
- Emits the funnel (N0…N7), `candidates.csv`, and an explicit **GAPS** section.

## 3. Output: the feasibility funnel

```
Sanctioned securities (OpenSanctions)        → N0
  with ISIN                                  → N1
  resolvable to LEI (GLEIF)                  → N2
Descendant issuers of sanctioned groups (L2) → N3
Candidate ISINs (direct + indirect)          → N4   (direct / indirect split)
  that are debt instruments (OpenFIGI)       → N5
  that are US / TRACE-eligible               → N6
  with any free activity signal found        → N7   ← headline number
```

Artifacts:
- `out/report.md` — the funnel + a **GAPS** section listing every place the free path
  breaks (LEI coverage, non-US ISIN mapping, FINRA free-tier limits) with counts.
- `out/candidates.csv` — ranked "live" suspicious ISINs: `isin, issuer, root_parent
  (sanctioned group), direct|indirect, security_type, us|non_us, activity_signal,
  source_provenance`.

## 4. Error handling & data-quality posture

- **Honest gaps over fake success.** Every stage counts and reports records it *could not*
  resolve. A broken free path is a valid, documented spike result.
- **Provenance on every row** carried to `candidates.csv` (which source, which URL, when
  fetched) — investigative tool credibility depends on it.
- **Caching + rate-limit + retry** in `common/http.py`; bulk dumps pulled once into
  `data/raw/`; OpenFIGI/FINRA responses disk-cached so re-runs are cheap and polite.
- **No silent truncation.** If a stage samples or caps (e.g. OpenFIGI free rate limit),
  it logs exactly how many rows were dropped and why.

## 5. Testing

- **Unit:** `ids.py` ISIN validation + ISIN↔CUSIP check-digit round-trip (known vectors);
  ownership-graph traversal on a small synthetic parent/child fixture (transitivity,
  cycle safety, depth bound); funnel arithmetic on a fixture.
- **Contract/golden:** tiny committed sample slices of each bulk format so stage parsers
  are tested without network; one recorded FINRA/OpenFIGI response fixture per shape.
- **No live-network tests in CI.** Network calls happen only in real runs against the disk
  cache; a `--sample` mode runs the whole pipeline on the committed fixtures end-to-end.

## 6. Risks & how the design addresses them (critic's points)

| Critic point | Design response |
|---|---|
| Free TRACE ≠ machine-readable trade feed | Stage 4 recon proves what free actually yields; "no free path" is a recorded result, not a failure. |
| ISIN vs CUSIP not 1:1 | Trivial derivation for US ISINs; non-US flagged as explicit GAP with counts. |
| `fusion_confidence` via BIC is bogus | Ignored. Real join key is ISIN (+ LEI for ownership). No BIC join. |
| Sanctioned-ISIN ∩ TRACE may be tiny | Funnel N5→N6 *measures* it directly; small result is a valid (and cheap) answer. |
| `nbu-statistics` / EMMA filler | Out of scope. |

## 7. Open questions deferred to the spike itself (by design)
- Exact free FINRA endpoint(s) and their machine-readability — resolved in Stage 4 recon.
- OpenFIGI free rate-limit throughput vs candidate volume — measured, capped, logged.
- GLEIF Level-2 coverage depth for sanctioned groups — measured in Stage 2.

## 8. Definition of done
- Pipeline runs end-to-end on free data and on the `--sample` fixtures.
- `out/report.md` funnel filled with real numbers; GAPS quantified.
- Clear verdict surfaced: intersection **significant / marginal / zero**, with the evidence
  to justify the next decision (build the full service, or stop).
