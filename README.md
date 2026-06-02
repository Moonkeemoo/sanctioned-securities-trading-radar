# Sanctioned Securities Trading Radar — Feasibility Spike

Measures the real intersection between sanctioned securities (including
subsidiary-issued bonds) and US bond trading, using **free data only**.
See `docs/superpowers/specs/2026-06-02-sanctioned-securities-trading-radar-design.md`.

## Quick start (sample, no network)
```bash
pip install -e ".[dev]"
pytest -q
python -m radar.run --sample --raw tests/fixtures --out data/out
cat data/out/report.md
```

## Real run (free bulk + free APIs)
1. Download bulk dumps into `data/raw/` (filenames stage1 expects):
   - `securities.ftm.json` — OpenSanctions "Sanctioned Securities" FtM export
   - `entities.ftm.json`    — OpenSanctions sanctioned legal entities FtM export
   - `isin_lei.csv`         — GLEIF ISIN-to-LEI mapping
   - `rr.csv`               — GLEIF Level-2 relationship records
2. Run Stage 4 recon FIRST to confirm a free FINRA endpoint, then record the response
   shape into `tests/fixtures/finra_recon_sample.json` and adjust `parse_signal` if needed.
3. `python -m radar.run --date 2026-06-02`
4. Read `data/out/report.md` (funnel + GAPS) and `data/out/candidates.csv`.

## Output
- `report.md` — the feasibility funnel (N0..N7) + GAPS + intersection verdict.
- `candidates.csv` — ranked live suspicious ISINs with full source provenance.
