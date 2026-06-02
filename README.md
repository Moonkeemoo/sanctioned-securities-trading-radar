# Sanctioned Securities Trading Radar

**Are bonds of sanctioned companies — including bonds quietly issued through their
subsidiaries — still tradeable on US markets?** This project answers that question by
stitching three free public datasets into a single chain:

```
sanctioned security  ──▶  legal entity (LEI)  ──▶  parent / subsidiary group  ──▶  US bond trade
   (OpenSanctions)            (GLEIF)                  (GLEIF Level-2)               (FINRA TRACE)
```

The investigative value is the **indirect** link: a bond whose ISIN is *not* itself on any
sanctions list, but which is issued by a **subsidiary of a sanctioned parent**. A naive
name search never sees those. Walking the ownership graph does.

> ### Status: feasibility spike (not a monitoring service)
> This repository is intentionally a **cheap feasibility spike on free data only**. Its job
> is to *measure*, before anyone spends money, whether sanctioned securities actually
> intersect US bond trading at all — and to quantify every place the free-data path breaks,
> rather than hide it. It is **not** a real-time monitoring product. Real-time / daily TRACE
> trade feeds are paid ($750–1,500/month) and are out of scope here. See
> [`docs/superpowers/specs/2026-06-02-sanctioned-securities-trading-radar-design.md`](docs/superpowers/specs/2026-06-02-sanctioned-securities-trading-radar-design.md)
> for the full design and [`docs/superpowers/plans/`](docs/superpowers/plans/) for the build plan.

## Who it's for

Bank/broker compliance desks, regulators (OFAC, SEC), and investigative journalists who want
to see whether bonds of sanctioned issuers and their subsidiaries are still changing hands on
the US over-the-counter market.

## How it works

A linear pipeline of five stages. Each stage reads its input, writes a Parquet artifact, is
independently re-runnable, and logs every row it could **not** resolve (honest gaps over fake
success).

| Stage | Module | What it does |
|------|--------|--------------|
| 1. Ingest | `stage1_ingest.py` | Parse the free bulk dumps (OpenSanctions securities + entities, GLEIF ISIN→LEI, GLEIF Level-2) into normalized tables. |
| 2. Ownership | `stage2_ownership.py` | Walk the LEI ownership graph **downward** from sanctioned parents to subsidiary-issued ISINs; tag each ISIN `direct` or `indirect`, tracking depth and which sanctioned root it traces to. |
| 3. Classify | `stage3_classify.py` | Decide which candidate ISINs are US bonds eligible for FINRA TRACE — derive the CUSIP for US ISINs and filter to debt instruments via the free OpenFIGI API. |
| 4. Activity | `stage4_activity.py` | Probe **free** FINRA sources for trading-activity signals on the eligible candidates. (See the note on FINRA below.) |
| 5. Report | `stage5_report.py` | Emit the feasibility **funnel**, a ranked `candidates.csv`, and an explicit **GAPS** section. |

`run.py` orchestrates the five stages.

### The output: a feasibility funnel

The headline artifact is a funnel of counts that *is* the feasibility answer:

```
N0  sanctioned securities (OpenSanctions)
N1    with an ISIN
N2    issuer resolvable to an LEI (GLEIF)
N3  descendant issuers of sanctioned groups (GLEIF Level-2)
N4  candidate ISINs  (split: direct vs indirect)
N5    that are debt instruments (OpenFIGI)
N6    that are US / TRACE-eligible
N7    with any free trading-activity signal found     ← the bottom-line number
```

A small N6/N7 is itself a valid, cheap answer ("not worth building the full service"); a large
one justifies paying for real TRACE data next.

## Data sources (all free)

- **OpenSanctions** — sanctioned securities (ISINs) and sanctioned legal entities. Bulk
  JSON/CSV download, no API key, CC BY-NC (non-commercial).
- **GLEIF** — the global LEI index: ISIN→LEI mapping files and Level-2 parent/child ownership
  records. Free bulk + free API.
- **FINRA TRACE** — US OTC bond transactions. Only the **free** delayed/aggregate tier is used
  here (web/monthly aggregates), never a paid feed.

## Requirements

- Python 3.11+
- Dependencies: `polars`, `httpx` (runtime); `pytest`, `ruff` (dev). Installed via the
  package below.

## Install

```bash
python -m venv .venv
# Windows (PowerShell):
.\.venv\Scripts\Activate.ps1
# macOS/Linux:
# source .venv/bin/activate
pip install -e ".[dev]"
```

## Quick start (sample, no network)

Runs the entire pipeline on the tiny committed fixtures — no internet required. This is the
fastest way to see the shape of the output and confirm the install works.

```bash
pytest -q
python -m radar.run --sample --raw tests/fixtures --out data/out
# then read the report:
#   Windows:  Get-Content data/out/report.md
#   *nix:     cat data/out/report.md
```

In `--sample` mode the report is clearly labelled as illustrative (it cannot know security
types without the network, so it honestly reports N6 = 0).

## Real run (free bulk dumps + free APIs)

1. Download the four bulk dumps into `data/raw/` with the filenames stage 1 expects:
   | File | Source |
   |------|--------|
   | `securities.ftm.json` | OpenSanctions "Sanctioned Securities" FollowTheMoney export |
   | `entities.ftm.json`   | OpenSanctions sanctioned legal-entities FollowTheMoney export |
   | `isin_lei.csv`        | GLEIF ISIN-to-LEI mapping |
   | `rr.csv`              | GLEIF Level-2 relationship records |

2. **Confirm a free FINRA endpoint first (recon).** `stage4_activity.FINRA_RECON_ENDPOINTS`
   is intentionally **empty** — the behaviour of FINRA's free tier is the main unknown this
   spike exists to resolve. Use `stage4_activity.recon()` against a few known US corporate-bond
   ISINs, inspect what actually comes back for free, record the response shape into
   `tests/fixtures/finra_recon_sample.json`, and adjust `parse_signal()` if the shape differs.
   If no free machine-readable signal exists, that is a valid result — the pipeline records it
   in the GAPS section and N7 stays 0.

3. Run the full pipeline:
   ```bash
   python -m radar.run --date 2026-06-02
   ```

4. Read the results in `data/out/`.

### CLI options

```
python -m radar.run [--sample] [--raw DIR] [--interim DIR] [--out DIR] [--cache DIR] [--date YYYY-MM-DD]
```
- `--sample` — run on fixtures, skip all network calls.
- `--raw` / `--interim` / `--out` / `--cache` — directory overrides (default under `data/`).
- `--date` — provenance timestamp recorded on activity rows.

## Output

Written to `data/out/`:

- **`report.md`** — the feasibility funnel (N0..N7), an intersection verdict
  (ZERO / MARGINAL / SIGNIFICANT), and a **GAPS** section quantifying where the free path
  breaks (non-US ISINs without a CUSIP map, sanctioned entities without an LEI, FINRA free-tier
  limits).
- **`candidates.csv`** — the ranked list of "live" suspicious ISINs, one row per ISIN, with
  full source provenance: issuer LEI and name, the sanctioned root it traces to, direct vs
  indirect, security type, US/non-US, any activity signal, and the source URL.

## Repository layout

```
src/radar/
  common/        # ISIN/CUSIP math, cached HTTP client, shared schemas, logging
  stage1_ingest.py … stage5_report.py
  run.py         # orchestrator
tests/           # pytest suite + tiny fixtures (the --sample inputs)
docs/superpowers/
  specs/         # design / spec
  plans/         # TDD implementation plan
data/            # raw dumps, interim parquet, outputs (gitignored)
```

## Development

```bash
pytest -q            # run the test suite
ruff check src tests # lint
```

The deterministic logic (ISIN/CUSIP check digits, ownership-graph traversal, the funnel) is
covered test-first; the network stages are exercised against recorded fixtures, so the whole
suite runs offline.

## Caveats

- **ISIN↔CUSIP is 1:1 only for US ISINs** (`US` + CUSIP + check digit). Non-US ISINs that may
  still trade on TRACE (Yankee/144A bonds) are flagged as an explicit, counted gap.
- **LEI coverage is incomplete** — not every sanctioned issuer has an LEI, so some ownership
  chains break. The pipeline counts how many.
- **The free FINRA path may yield no machine-readable trade signal at all.** That is a valid
  spike outcome, recorded honestly rather than hidden.
