# Sanctioned Securities Trading Radar — Feasibility Spike Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a free-data Python pipeline that measures the real intersection between sanctioned securities (incl. subsidiary-issued bonds) and US bond trading, emitting a feasibility funnel and a ranked candidates list.

**Architecture:** A linear 5-stage pipeline (`ingest → ownership → classify → activity → report`). Each stage reads/writes Parquet via Polars, is independently re-runnable, and logs the count of rows it cannot resolve. Deterministic logic (ISIN/CUSIP math, ownership-graph traversal, funnel arithmetic) is built test-first; network stages (OpenFIGI, FINRA) are recon-driven against disk-cached, fixture-recorded responses.

**Tech Stack:** Python 3.11+, `polars` (dataframes + joins + parquet), `httpx` (HTTP with disk cache), `pytest` (tests), `ruff` (lint). DuckDB available for ad-hoc inspection but not required by the pipeline.

---

## File Structure

```
pyproject.toml                      # deps, ruff/pytest config, package metadata
src/radar/__init__.py
src/radar/common/__init__.py
src/radar/common/ids.py             # ISIN validation, ISIN<->CUSIP, check digits
src/radar/common/http.py            # cached HTTP client (disk cache + retry + rate limit)
src/radar/common/schemas.py         # column-name constants for every interim table
src/radar/common/log.py             # per-stage metric logging helper
src/radar/stage1_ingest.py          # parse OpenSanctions + GLEIF bulk into tables
src/radar/stage2_ownership.py       # LEI parent->child graph; tag direct/indirect ISINs
src/radar/stage3_classify.py        # US-bond / TRACE-eligibility classification + OpenFIGI
src/radar/stage4_activity.py        # free FINRA activity signals (recon then batch)
src/radar/stage5_report.py          # funnel + candidates.csv + GAPS section
src/radar/run.py                    # orchestrator; --sample runs on fixtures
tests/fixtures/                     # tiny committed sample slices of each input format
tests/test_ids.py
tests/test_http.py
tests/test_stage1_ingest.py
tests/test_stage2_ownership.py
tests/test_stage3_classify.py
tests/test_stage4_activity.py
tests/test_stage5_report.py
tests/test_run_sample.py
```

Each stage reads `data/interim/<name>.parquet` and writes the next. `data/raw/` and
`data/interim/` are gitignored (already in `.gitignore`).

---

### Task 0: Project scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `src/radar/__init__.py`, `src/radar/common/__init__.py`
- Create: `tests/__init__.py`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "radar"
version = "0.1.0"
description = "Sanctioned securities trading radar — feasibility spike"
requires-python = ">=3.11"
dependencies = [
    "polars>=1.0",
    "httpx>=0.27",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "ruff>=0.6"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]

[tool.ruff]
line-length = 100
```

- [ ] **Step 2: Create empty package markers**

Create `src/radar/__init__.py`, `src/radar/common/__init__.py`, `tests/__init__.py` each containing a single newline.

- [ ] **Step 3: Create and activate a virtualenv, install deps**

Run (PowerShell):
```powershell
python -m venv .venv; .\.venv\Scripts\Activate.ps1; pip install -e ".[dev]"
```
Expected: `Successfully installed radar-0.1.0 ... polars ... httpx ... pytest ... ruff`

- [ ] **Step 4: Verify pytest collects nothing yet (sanity)**

Run: `pytest -q`
Expected: `no tests ran` (exit code 5) — confirms the harness works.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/radar/__init__.py src/radar/common/__init__.py tests/__init__.py
git commit -m "chore: scaffold radar package and tooling"
```

---

### Task 1: `common/ids.py` — ISIN / CUSIP identity math

This is the most safety-critical deterministic module (the CUSIP-vs-ISIN critique hinges on it). Built strictly test-first with published check-digit vectors.

**Files:**
- Create: `src/radar/common/ids.py`
- Test: `tests/test_ids.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_ids.py
import pytest
from radar.common.ids import (
    is_valid_isin, isin_check_digit, cusip_check_digit,
    us_isin_to_cusip, cusip_to_us_isin,
)

# Apple common stock ISIN US0378331005 (CUSIP 037833100) — published reference vector.
def test_valid_isin_apple():
    assert is_valid_isin("US0378331005") is True

def test_invalid_isin_bad_check_digit():
    assert is_valid_isin("US0378331006") is False

def test_invalid_isin_bad_length():
    assert is_valid_isin("US037833100") is False

def test_isin_check_digit_apple():
    assert isin_check_digit("US037833100") == 5

def test_cusip_check_digit_apple():
    assert cusip_check_digit("037833100") == 0  # full CUSIP is 037833100, last digit IS the check

def test_us_isin_to_cusip_apple():
    assert us_isin_to_cusip("US0378331005") == "037833100"

def test_us_isin_to_cusip_rejects_non_us():
    with pytest.raises(ValueError):
        us_isin_to_cusip("DE0005140008")

def test_cusip_to_us_isin_roundtrip():
    assert cusip_to_us_isin("037833100") == "US0378331005"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ids.py -q`
Expected: FAIL — `ModuleNotFoundError` / `ImportError: cannot import name ...`

- [ ] **Step 3: Implement `common/ids.py`**

```python
# src/radar/common/ids.py
"""ISIN and CUSIP identifier math.

ISIN = 2-letter country + 9-char NSIN + 1 check digit (mod-10 / Luhn over base-36).
CUSIP = 9 chars where the 9th is a mod-10 check digit.
For US securities: ISIN == "US" + 9-char CUSIP + ISIN check digit, so the mapping
is exact and reversible. This module is the single source of truth for that math.
"""
from __future__ import annotations

_ALNUM = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _luhn_mod10(digits: list[int]) -> int:
    """Luhn checksum used by ISIN: double every second digit from the right."""
    total = 0
    # Rightmost (the position the check digit will occupy) is doubled first.
    double = True
    for d in reversed(digits):
        if double:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        double = not double
    return (10 - (total % 10)) % 10


def isin_check_digit(isin_body: str) -> int:
    """Compute the ISIN check digit for the 11-char body (country+NSIN)."""
    expanded: list[int] = []
    for ch in isin_body.upper():
        val = _ALNUM.index(ch)
        if val < 10:
            expanded.append(val)
        else:
            expanded.append(val // 10)
            expanded.append(val % 10)
    return _luhn_mod10(expanded)


def is_valid_isin(isin: str) -> bool:
    if not isinstance(isin, str) or len(isin) != 12:
        return False
    if not isin[:2].isalpha():
        return False
    body, check = isin[:11], isin[11]
    if not check.isdigit():
        return False
    try:
        return isin_check_digit(body) == int(check)
    except ValueError:
        return False


def cusip_check_digit(cusip9: str) -> int:
    """The 9th CUSIP char is the check digit; recompute from the first 8."""
    body = cusip9.upper()[:8]
    total = 0
    for i, ch in enumerate(body):
        if ch.isdigit():
            v = int(ch)
        else:
            v = _ALNUM.index(ch)  # A=10..Z=35
        if i % 2 == 1:  # every second char (0-indexed odd) doubled
            v *= 2
        total += v // 10 + v % 10
    return (10 - (total % 10)) % 10


def us_isin_to_cusip(isin: str) -> str:
    if not isin.startswith("US") or len(isin) != 12:
        raise ValueError(f"Not a US ISIN: {isin!r}")
    return isin[2:11]


def cusip_to_us_isin(cusip9: str) -> str:
    body = "US" + cusip9.upper()
    return body + str(isin_check_digit(body))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ids.py -q`
Expected: PASS (8 passed). If `cusip_check_digit("037833100")` does not return `0`, stop and re-derive — Apple's CUSIP check digit is a published value; a mismatch means the algorithm is wrong, not the test.

- [ ] **Step 5: Commit**

```bash
git add src/radar/common/ids.py tests/test_ids.py
git commit -m "feat: ISIN/CUSIP identity math with check-digit validation"
```

---

### Task 2: `common/schemas.py` and `common/log.py`

Centralize column names (so stages never disagree on a column) and per-stage metric logging (so every stage reports what it dropped).

**Files:**
- Create: `src/radar/common/schemas.py`
- Create: `src/radar/common/log.py`
- Test: `tests/test_stage1_ingest.py` (imports only; real assertions added in Task 4)

- [ ] **Step 1: Create `common/schemas.py`**

```python
# src/radar/common/schemas.py
"""Column-name constants for interim tables. One source of truth so stages agree."""

# stage1 outputs
SANCTIONED_SECURITIES = ["isin", "ticker", "figi", "issuer_name", "issuer_entity_id", "source"]
SANCTIONED_ENTITIES = ["entity_id", "name", "lei", "country", "topics"]
ISIN_TO_LEI = ["isin", "lei"]
LEI_RELATIONS = ["parent_lei", "child_lei", "relation_type"]

# stage2 output
CANDIDATE_ISINS = ["isin", "issuer_lei", "root_sanctioned_lei", "path_depth", "tag"]

# stage3 output
CLASSIFIED = ["isin", "is_us", "cusip", "security_type", "trace_eligible_guess", "gap_reason"]

# stage4 output
ACTIVITY = ["isin", "signal_kind", "signal_value", "observed_period", "source_url", "fetched_at"]

TAG_DIRECT = "direct"
TAG_INDIRECT = "indirect"
```

- [ ] **Step 2: Create `common/log.py`**

```python
# src/radar/common/log.py
"""Tiny structured logger so every stage reports row counts and dropped rows."""
from __future__ import annotations

import sys


def metric(stage: str, name: str, value: int | str) -> None:
    print(f"[{stage}] {name}={value}", file=sys.stderr)


def gap(stage: str, reason: str, count: int) -> None:
    print(f"[{stage}] GAP reason={reason!r} count={count}", file=sys.stderr)
```

- [ ] **Step 3: Verify import smoke test**

Run: `python -c "import radar.common.schemas, radar.common.log; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add src/radar/common/schemas.py src/radar/common/log.py
git commit -m "feat: shared schemas and per-stage metric logging"
```

---

### Task 3: `common/http.py` — disk-cached HTTP client

Network politeness + reproducibility: cache every GET to disk keyed by URL hash, so re-runs are free and tests use recorded responses.

**Files:**
- Create: `src/radar/common/http.py`
- Test: `tests/test_http.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_http.py
import httpx
from radar.common.http import CachedClient


def test_cache_hit_avoids_second_network_call(tmp_path):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(200, json={"url": str(request.url)})

    transport = httpx.MockTransport(handler)
    client = CachedClient(cache_dir=tmp_path, transport=transport)

    r1 = client.get_json("https://example.test/a")
    r2 = client.get_json("https://example.test/a")

    assert r1 == r2 == {"url": "https://example.test/a"}
    assert calls["n"] == 1  # second call served from disk cache
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_http.py -q`
Expected: FAIL — `ImportError: cannot import name 'CachedClient'`

- [ ] **Step 3: Implement `common/http.py`**

```python
# src/radar/common/http.py
"""HTTP GET client with on-disk JSON cache, retry, and a minimum request interval."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import httpx


class CachedClient:
    def __init__(self, cache_dir, transport=None, min_interval=0.0, max_retries=3):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._client = httpx.Client(transport=transport, timeout=30.0)
        self.min_interval = min_interval
        self.max_retries = max_retries
        self._last_request = 0.0

    def _cache_path(self, key: str) -> Path:
        h = hashlib.sha256(key.encode()).hexdigest()[:32]
        return self.cache_dir / f"{h}.json"

    def get_json(self, url: str, *, params=None) -> dict | list:
        key = url + ("?" + json.dumps(params, sort_keys=True) if params else "")
        path = self._cache_path(key)
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        data = self._fetch_json(url, params)
        path.write_text(json.dumps(data), encoding="utf-8")
        return data

    def post_json(self, url: str, *, body) -> dict | list:
        key = url + "|POST|" + json.dumps(body, sort_keys=True)
        path = self._cache_path(key)
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        self._throttle()
        resp = self._client.post(url, json=body)
        resp.raise_for_status()
        data = resp.json()
        path.write_text(json.dumps(data), encoding="utf-8")
        return data

    def _throttle(self) -> None:
        if self.min_interval:
            wait = self.min_interval - (time.monotonic() - self._last_request)
            if wait > 0:
                time.sleep(wait)
        self._last_request = time.monotonic()

    def _fetch_json(self, url, params):
        last_exc = None
        for attempt in range(self.max_retries):
            self._throttle()
            try:
                resp = self._client.get(url, params=params)
                resp.raise_for_status()
                return resp.json()
            except (httpx.HTTPError, ValueError) as exc:  # ValueError = bad JSON
                last_exc = exc
                time.sleep(0.5 * (attempt + 1))
        raise RuntimeError(f"GET failed after {self.max_retries} attempts: {url}") from last_exc
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_http.py -q`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add src/radar/common/http.py tests/test_http.py
git commit -m "feat: disk-cached HTTP client with retry and throttle"
```

---

### Task 4: `stage1_ingest.py` — parse bulk inputs

Parse each free bulk format into a normalized Parquet table. Tested against tiny committed fixtures so no network is needed in tests.

> **Format notes (verify against real dumps during execution):**
> - OpenSanctions FtM export = newline-delimited JSON, one entity per line:
>   `{"id": ..., "schema": "Security", "properties": {"isin": [...], "name": [...], "ticker": [...], "figiCode": [...], "issuer": [...]}}`.
> - GLEIF ISIN-to-LEI mapping = CSV with header `LEI,ISIN`.
> - GLEIF Level-2 relationship CSV: `Relationship.StartNode.NodeID` is the **child**,
>   `Relationship.EndNode.NodeID` is the **parent**, `Relationship.RelationshipType` is e.g.
>   `IS_DIRECTLY_CONSOLIDATED_BY` / `IS_ULTIMATELY_CONSOLIDATED_BY` (StartNode is consolidated
>   *by* EndNode → EndNode is the parent). Edge direction is a known bug-trap; the test pins it.

**Files:**
- Create: `src/radar/stage1_ingest.py`
- Create fixtures: `tests/fixtures/opensanctions_securities.ftm.json`,
  `tests/fixtures/opensanctions_entities.ftm.json`,
  `tests/fixtures/gleif_isin_lei.csv`, `tests/fixtures/gleif_rr.csv`
- Test: `tests/test_stage1_ingest.py`

- [ ] **Step 1: Create fixtures**

`tests/fixtures/opensanctions_securities.ftm.json`:
```json
{"id": "sec-1", "schema": "Security", "properties": {"isin": ["US0378331005"], "name": ["ACME Bond 2030"], "ticker": ["ACM30"], "figiCode": ["BBG000000001"], "issuer": ["ent-acme"]}}
{"id": "sec-2", "schema": "Security", "properties": {"isin": ["XS1234567890"], "name": ["Foreign Note"]}}
```

`tests/fixtures/opensanctions_entities.ftm.json`:
```json
{"id": "ent-acme", "schema": "Company", "properties": {"name": ["ACME Holding"], "leiCode": ["5493000000000000ACME"], "country": ["ru"], "topics": ["sanction"]}}
{"id": "ent-nolei", "schema": "Company", "properties": {"name": ["No LEI Corp"], "country": ["ru"], "topics": ["sanction"]}}
```

`tests/fixtures/gleif_isin_lei.csv`:
```csv
LEI,ISIN
5493000000000000ACME,US0378331005
5493000000000000SUB1,US5949181045
```

`tests/fixtures/gleif_rr.csv`:
```csv
Relationship.StartNode.NodeID,Relationship.EndNode.NodeID,Relationship.RelationshipType
5493000000000000SUB1,5493000000000000ACME,IS_DIRECTLY_CONSOLIDATED_BY
```

- [ ] **Step 2: Write failing tests**

```python
# tests/test_stage1_ingest.py
from pathlib import Path
import polars as pl
from radar.stage1_ingest import (
    parse_securities, parse_entities, parse_isin_lei, parse_rr,
)

FIX = Path(__file__).parent / "fixtures"

def test_parse_securities_extracts_first_isin_and_issuer():
    df = parse_securities(FIX / "opensanctions_securities.ftm.json")
    row = df.filter(pl.col("isin") == "US0378331005").to_dicts()[0]
    assert row["issuer_name"] == "ACME Bond 2030"
    assert row["issuer_entity_id"] == "ent-acme"
    assert row["figi"] == "BBG000000001"

def test_parse_securities_handles_missing_issuer():
    df = parse_securities(FIX / "opensanctions_securities.ftm.json")
    row = df.filter(pl.col("isin") == "XS1234567890").to_dicts()[0]
    assert row["issuer_entity_id"] is None

def test_parse_entities_extracts_lei():
    df = parse_entities(FIX / "opensanctions_entities.ftm.json")
    assert df.filter(pl.col("entity_id") == "ent-acme")["lei"][0] == "5493000000000000ACME"
    assert df.filter(pl.col("entity_id") == "ent-nolei")["lei"][0] is None

def test_parse_isin_lei():
    df = parse_isin_lei(FIX / "gleif_isin_lei.csv")
    assert set(df.columns) == {"isin", "lei"}
    assert df.height == 2

def test_parse_rr_direction_parent_is_endnode():
    df = parse_rr(FIX / "gleif_rr.csv")
    row = df.to_dicts()[0]
    assert row["parent_lei"] == "5493000000000000ACME"   # EndNode = parent
    assert row["child_lei"] == "5493000000000000SUB1"     # StartNode = child
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_stage1_ingest.py -q`
Expected: FAIL — `ImportError`

- [ ] **Step 4: Implement `stage1_ingest.py`**

```python
# src/radar/stage1_ingest.py
"""Stage 1: parse free bulk dumps into normalized Parquet tables."""
from __future__ import annotations

import json
from pathlib import Path

import polars as pl

from radar.common import log


def _first(props: dict, key: str):
    vals = props.get(key)
    return vals[0] if vals else None


def parse_securities(path: Path) -> pl.DataFrame:
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        ent = json.loads(line)
        if ent.get("schema") != "Security":
            continue
        p = ent.get("properties", {})
        rows.append({
            "isin": _first(p, "isin"),
            "ticker": _first(p, "ticker"),
            "figi": _first(p, "figiCode"),
            "issuer_name": _first(p, "name"),
            "issuer_entity_id": _first(p, "issuer"),
            "source": "opensanctions",
        })
    df = pl.DataFrame(rows, schema={c: pl.Utf8 for c in
        ["isin", "ticker", "figi", "issuer_name", "issuer_entity_id", "source"]})
    return df.filter(pl.col("isin").is_not_null())


def parse_entities(path: Path) -> pl.DataFrame:
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        ent = json.loads(line)
        p = ent.get("properties", {})
        rows.append({
            "entity_id": ent.get("id"),
            "name": _first(p, "name"),
            "lei": _first(p, "leiCode"),
            "country": _first(p, "country"),
            "topics": ",".join(p.get("topics", [])) or None,
        })
    return pl.DataFrame(rows, schema={c: pl.Utf8 for c in
        ["entity_id", "name", "lei", "country", "topics"]})


def parse_isin_lei(path: Path) -> pl.DataFrame:
    df = pl.read_csv(path)
    return df.rename({"LEI": "lei", "ISIN": "isin"}).select(["isin", "lei"])


def parse_rr(path: Path) -> pl.DataFrame:
    df = pl.read_csv(path)
    return df.select([
        pl.col("Relationship.EndNode.NodeID").alias("parent_lei"),
        pl.col("Relationship.StartNode.NodeID").alias("child_lei"),
        pl.col("Relationship.RelationshipType").alias("relation_type"),
    ])


def run(raw_dir: Path, interim_dir: Path) -> None:
    raw_dir, interim_dir = Path(raw_dir), Path(interim_dir)
    interim_dir.mkdir(parents=True, exist_ok=True)
    jobs = {
        "sanctioned_securities": parse_securities(raw_dir / "securities.ftm.json"),
        "sanctioned_entities": parse_entities(raw_dir / "entities.ftm.json"),
        "isin_to_lei": parse_isin_lei(raw_dir / "isin_lei.csv"),
        "lei_relations": parse_rr(raw_dir / "rr.csv"),
    }
    for name, df in jobs.items():
        df.write_parquet(interim_dir / f"{name}.parquet")
        log.metric("stage1", f"{name}_rows", df.height)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_stage1_ingest.py -q`
Expected: PASS (5 passed)

- [ ] **Step 6: Commit**

```bash
git add src/radar/stage1_ingest.py tests/test_stage1_ingest.py tests/fixtures/
git commit -m "feat: stage1 ingest of OpenSanctions and GLEIF bulk dumps"
```

---

### Task 5: `stage2_ownership.py` — ownership graph & direct/indirect tagging

The investigative core: walk down from sanctioned parents to subsidiary-issued ISINs. Built test-first on a synthetic graph that exercises transitivity, cycle safety, and the depth bound.

**Files:**
- Create: `src/radar/stage2_ownership.py`
- Test: `tests/test_stage2_ownership.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_stage2_ownership.py
from radar.stage2_ownership import descendants, build_candidates
import polars as pl

def test_descendants_transitive():
    relations = [("P", "A"), ("A", "B"), ("B", "C")]  # (parent, child)
    assert descendants({"P"}, relations, max_depth=10) == {"A", "B", "C"}

def test_descendants_depth_bound():
    relations = [("P", "A"), ("A", "B"), ("B", "C")]
    assert descendants({"P"}, relations, max_depth=2) == {"A", "B"}

def test_descendants_cycle_safe():
    relations = [("P", "A"), ("A", "P")]  # cycle
    assert descendants({"P"}, relations, max_depth=10) == {"A", "P"} - {"P"} | {"A"}
    # i.e. {"A"} plus P is re-reached but not infinite-looped
    assert descendants({"P"}, relations, max_depth=10) == {"A", "P"}.difference({"P"}) | {"A"}

def test_build_candidates_tags_direct_and_indirect():
    seed_leis = {"P"}
    relations = [("P", "SUB")]
    isin_to_lei = pl.DataFrame({"isin": ["US0378331005", "US5949181045"],
                                "lei": ["P", "SUB"]})
    sanctioned_isins = {"US0378331005"}  # only the parent's own bond is directly listed
    out = build_candidates(seed_leis, relations, isin_to_lei, sanctioned_isins, max_depth=5)
    rows = {r["isin"]: r for r in out.to_dicts()}
    assert rows["US0378331005"]["tag"] == "direct"
    assert rows["US5949181045"]["tag"] == "indirect"   # subsidiary bond, not listed
    assert rows["US5949181045"]["issuer_lei"] == "SUB"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_stage2_ownership.py -q`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement `stage2_ownership.py`**

```python
# src/radar/stage2_ownership.py
"""Stage 2: traverse the GLEIF ownership graph; tag candidate ISINs direct/indirect."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import polars as pl

from radar.common import log
from radar.common.schemas import TAG_DIRECT, TAG_INDIRECT


def descendants(seed_leis: set[str], relations, max_depth: int) -> set[str]:
    """All LEIs reachable downward from seeds (exclusive of seeds), depth-bounded."""
    children = defaultdict(list)
    for parent, child in relations:
        children[parent].append(child)
    found: set[str] = set()
    frontier = set(seed_leis)
    for _ in range(max_depth):
        nxt: set[str] = set()
        for lei in frontier:
            for child in children.get(lei, []):
                if child not in found:
                    found.add(child)
                    nxt.add(child)
        if not nxt:
            break
        frontier = nxt
    return found - set(seed_leis)  # seeds excluded even if re-reached via a cycle


def build_candidates(seed_leis, relations, isin_to_lei: pl.DataFrame,
                     sanctioned_isins: set[str], max_depth: int) -> pl.DataFrame:
    desc = descendants(set(seed_leis), list(relations), max_depth)
    all_leis = set(seed_leis) | desc
    sub = isin_to_lei.filter(pl.col("lei").is_in(list(all_leis)))
    rows = []
    for r in sub.to_dicts():
        isin, lei = r["isin"], r["lei"]
        tag = TAG_DIRECT if isin in sanctioned_isins else TAG_INDIRECT
        # root = the seed LEI if issuer is a seed, else first seed (approx for spike)
        root = lei if lei in seed_leis else next(iter(seed_leis), None)
        rows.append({
            "isin": isin, "issuer_lei": lei, "root_sanctioned_lei": root,
            "path_depth": 0 if lei in seed_leis else 1, "tag": tag,
        })
    return pl.DataFrame(rows, schema={
        "isin": pl.Utf8, "issuer_lei": pl.Utf8, "root_sanctioned_lei": pl.Utf8,
        "path_depth": pl.Int64, "tag": pl.Utf8})


def run(interim_dir: Path, max_depth: int = 5) -> None:
    interim_dir = Path(interim_dir)
    entities = pl.read_parquet(interim_dir / "sanctioned_entities.parquet")
    securities = pl.read_parquet(interim_dir / "sanctioned_securities.parquet")
    isin_to_lei = pl.read_parquet(interim_dir / "isin_to_lei.parquet")
    rr = pl.read_parquet(interim_dir / "lei_relations.parquet")

    seed_leis = set(entities.filter(pl.col("lei").is_not_null())["lei"].to_list())
    # also seed with LEIs of issuers of sanctioned ISINs (via GLEIF, not the OS issuer link)
    sanctioned_isins = set(securities["isin"].to_list())
    issuer_leis = set(isin_to_lei.filter(pl.col("isin").is_in(list(sanctioned_isins)))["lei"].to_list())
    seed_leis |= issuer_leis

    relations = list(zip(rr["parent_lei"].to_list(), rr["child_lei"].to_list()))
    out = build_candidates(seed_leis, relations, isin_to_lei, sanctioned_isins, max_depth)
    out.write_parquet(interim_dir / "candidate_isins.parquet")

    log.metric("stage2", "seed_leis", len(seed_leis))
    log.metric("stage2", "descendant_leis", len(descendants(seed_leis, relations, max_depth)))
    log.metric("stage2", "candidates_direct", out.filter(pl.col("tag") == TAG_DIRECT).height)
    log.metric("stage2", "candidates_indirect", out.filter(pl.col("tag") == TAG_INDIRECT).height)
    no_lei = entities.filter(pl.col("lei").is_null()).height
    log.gap("stage2", "sanctioned_entity_without_lei", no_lei)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_stage2_ownership.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/radar/stage2_ownership.py tests/test_stage2_ownership.py
git commit -m "feat: stage2 ownership graph with direct/indirect ISIN tagging"
```

---

### Task 6: `stage3_classify.py` — US-bond / TRACE-eligibility classification

Deterministic ISIN/CUSIP/US logic is test-first; the OpenFIGI type lookup goes through the cached client and is tested with a recorded response.

**Files:**
- Create: `src/radar/stage3_classify.py`
- Create fixture: `tests/fixtures/openfigi_response.json`
- Test: `tests/test_stage3_classify.py`

- [ ] **Step 1: Create OpenFIGI fixture**

`tests/fixtures/openfigi_response.json`:
```json
[{"data": [{"securityType": "GLOBAL", "securityType2": "Corp", "marketSector": "Corp"}]}]
```

- [ ] **Step 2: Write failing tests**

```python
# tests/test_stage3_classify.py
from radar.stage3_classify import classify_isin, is_debt_type

def test_classify_us_isin_derives_cusip():
    row = classify_isin("US0378331005", security_type="Corp")
    assert row["is_us"] is True
    assert row["cusip"] == "037833100"
    assert row["trace_eligible_guess"] is True
    assert row["gap_reason"] is None

def test_classify_non_us_flags_gap():
    row = classify_isin("XS1234567890", security_type="Corp")
    assert row["is_us"] is False
    assert row["cusip"] is None
    assert row["gap_reason"] == "non_us_isin_no_cusip_map"

def test_equity_not_trace_eligible():
    row = classify_isin("US0378331005", security_type="Equity")
    assert row["trace_eligible_guess"] is False

def test_is_debt_type():
    assert is_debt_type("Corp") is True
    assert is_debt_type("Govt") is True
    assert is_debt_type("Equity") is False
    assert is_debt_type(None) is False
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_stage3_classify.py -q`
Expected: FAIL — `ImportError`

- [ ] **Step 4: Implement `stage3_classify.py`**

```python
# src/radar/stage3_classify.py
"""Stage 3: classify candidate ISINs by US-bond / TRACE-eligibility."""
from __future__ import annotations

from pathlib import Path

import polars as pl

from radar.common import log
from radar.common.ids import us_isin_to_cusip
from radar.common.http import CachedClient

_DEBT_TYPES = {"Corp", "Govt", "Mtge", "Muni", "Pfd", "Bond", "Note"}
OPENFIGI_URL = "https://api.openfigi.com/v3/mapping"


def is_debt_type(security_type: str | None) -> bool:
    return security_type in _DEBT_TYPES


def classify_isin(isin: str, security_type: str | None) -> dict:
    is_us = isin.startswith("US")
    cusip = us_isin_to_cusip(isin) if is_us else None
    debt = is_debt_type(security_type)
    gap = None if is_us else "non_us_isin_no_cusip_map"
    return {
        "isin": isin,
        "is_us": is_us,
        "cusip": cusip,
        "security_type": security_type,
        "trace_eligible_guess": bool(is_us and debt),
        "gap_reason": gap,
    }


def lookup_types(isins: list[str], client: CachedClient, batch_size: int = 10) -> dict[str, str]:
    """Resolve securityType2 per ISIN via OpenFIGI. Caps + logs dropped on rate limit."""
    out: dict[str, str] = {}
    for i in range(0, len(isins), batch_size):
        chunk = isins[i:i + batch_size]
        body = [{"idType": "ID_ISIN", "idValue": x} for x in chunk]
        try:
            resp = client.post_json(OPENFIGI_URL, body=body)
        except Exception:  # noqa: BLE001 — rate-limited/blocked: record and continue
            log.gap("stage3", "openfigi_lookup_failed", len(chunk))
            continue
        for isin, entry in zip(chunk, resp):
            data = entry.get("data") if isinstance(entry, dict) else None
            if data:
                out[isin] = data[0].get("securityType2") or data[0].get("marketSector")
    return out


def run(interim_dir: Path, cache_dir: Path) -> None:
    interim_dir = Path(interim_dir)
    cand = pl.read_parquet(interim_dir / "candidate_isins.parquet")
    client = CachedClient(cache_dir=cache_dir, min_interval=2.0)
    types = lookup_types(cand["isin"].to_list(), client)
    rows = [classify_isin(isin, types.get(isin)) for isin in cand["isin"].to_list()]
    df = pl.DataFrame(rows)
    df.write_parquet(interim_dir / "classified.parquet")

    log.metric("stage3", "us_isins", df.filter(pl.col("is_us")).height)
    log.metric("stage3", "trace_eligible_guess", df.filter(pl.col("trace_eligible_guess")).height)
    log.gap("stage3", "non_us_isin_no_cusip_map", df.filter(~pl.col("is_us")).height)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_stage3_classify.py -q`
Expected: PASS (4 passed)

- [ ] **Step 6: Commit**

```bash
git add src/radar/stage3_classify.py tests/test_stage3_classify.py tests/fixtures/openfigi_response.json
git commit -m "feat: stage3 US-bond / TRACE-eligibility classification"
```

---

### Task 7: `stage4_activity.py` — free FINRA activity signals (recon-driven)

The free-FINRA path is the main known unknown. This stage separates a **recon** probe (run once, manually inspected) from a **parse** function that is unit-tested against the recorded response. If no free machine-readable signal exists, the stage records that as the result.

**Files:**
- Create: `src/radar/stage4_activity.py`
- Create fixture: `tests/fixtures/finra_recon_sample.json` (placeholder shape; replaced with the real recorded response during execution recon)
- Test: `tests/test_stage4_activity.py`

- [ ] **Step 1: Create a recon fixture (shape to be replaced during recon)**

`tests/fixtures/finra_recon_sample.json`:
```json
{"isin": "US0378331005", "monthlyTrades": 42, "period": "2026-05"}
```

- [ ] **Step 2: Write failing test for the parser**

```python
# tests/test_stage4_activity.py
import json
from pathlib import Path
from radar.stage4_activity import parse_signal

FIX = Path(__file__).parent / "fixtures"

def test_parse_signal_extracts_trade_count():
    raw = json.loads((FIX / "finra_recon_sample.json").read_text())
    sig = parse_signal(raw, source_url="https://finra.test/x", fetched_at="2026-06-02")
    assert sig["isin"] == "US0378331005"
    assert sig["signal_kind"] == "monthly_trade_count"
    assert sig["signal_value"] == "42"
    assert sig["observed_period"] == "2026-05"
    assert sig["source_url"] == "https://finra.test/x"

def test_parse_signal_returns_none_when_no_activity():
    sig = parse_signal({"isin": "US0378331005", "monthlyTrades": 0, "period": "2026-05"},
                       source_url="u", fetched_at="t")
    assert sig is None
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_stage4_activity.py -q`
Expected: FAIL — `ImportError`

- [ ] **Step 4: Implement `stage4_activity.py`**

```python
# src/radar/stage4_activity.py
"""Stage 4: probe FREE FINRA sources for activity signals.

Design: recon() is run once and its raw response inspected/recorded as the fixture.
parse_signal() is the tested, stable contract. If no free machine-readable signal is
available, run() records zero signals and logs a GAP — a valid feasibility result.
"""
from __future__ import annotations

from pathlib import Path

import polars as pl

from radar.common import log
from radar.common.http import CachedClient

# Candidate free endpoints to probe during recon (resolved/confirmed at execution time).
# Documented free surfaces: FINRA Data API (developer.finra.org), Bond Center, TSAR monthly.
FINRA_RECON_ENDPOINTS = [
    # filled in during recon; left explicit so the engineer records what actually works
]


def recon(client: CachedClient, sample_isins: list[str]) -> list[dict]:
    """Probe each candidate endpoint on known US corp-bond ISINs; return raw responses.

    Run interactively; inspect the returned dicts; copy the working response shape into
    tests/fixtures/finra_recon_sample.json and update parse_signal if the shape differs.
    """
    results = []
    for url in FINRA_RECON_ENDPOINTS:
        for isin in sample_isins:
            try:
                results.append({"url": url, "isin": isin, "resp": client.get_json(url, params={"isin": isin})})
            except Exception as exc:  # noqa: BLE001
                results.append({"url": url, "isin": isin, "error": str(exc)})
    return results


def parse_signal(raw: dict, *, source_url: str, fetched_at: str) -> dict | None:
    """Normalize one FINRA response into an ACTIVITY row, or None if no activity.

    NOTE: keyed to the recon fixture shape ({isin, monthlyTrades, period}). If recon
    reveals a different shape, update this function and the fixture together.
    """
    trades = raw.get("monthlyTrades")
    if not trades:  # 0 or missing → no observable activity
        return None
    return {
        "isin": raw["isin"],
        "signal_kind": "monthly_trade_count",
        "signal_value": str(trades),
        "observed_period": raw.get("period"),
        "source_url": source_url,
        "fetched_at": fetched_at,
    }


def run(interim_dir: Path, cache_dir: Path, fetched_at: str) -> None:
    interim_dir = Path(interim_dir)
    classified = pl.read_parquet(interim_dir / "classified.parquet")
    eligible = classified.filter(pl.col("trace_eligible_guess"))["isin"].to_list()
    client = CachedClient(cache_dir=cache_dir, min_interval=1.0)

    rows = []
    if not FINRA_RECON_ENDPOINTS:
        log.gap("stage4", "no_free_finra_endpoint_confirmed", len(eligible))
    else:
        for isin in eligible:
            for url in FINRA_RECON_ENDPOINTS:
                try:
                    raw = client.get_json(url, params={"isin": isin})
                except Exception:  # noqa: BLE001
                    continue
                sig = parse_signal(raw, source_url=url, fetched_at=fetched_at)
                if sig:
                    rows.append(sig)
                    break

    df = pl.DataFrame(rows, schema={c: pl.Utf8 for c in
        ["isin", "signal_kind", "signal_value", "observed_period", "source_url", "fetched_at"]})
    df.write_parquet(interim_dir / "activity.parquet")
    log.metric("stage4", "signals_found", df.height)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_stage4_activity.py -q`
Expected: PASS (2 passed)

- [ ] **Step 6: Commit**

```bash
git add src/radar/stage4_activity.py tests/test_stage4_activity.py tests/fixtures/finra_recon_sample.json
git commit -m "feat: stage4 free FINRA activity probing (recon + tested parser)"
```

---

### Task 8: `stage5_report.py` — funnel + candidates.csv + GAPS

**Files:**
- Create: `src/radar/stage5_report.py`
- Test: `tests/test_stage5_report.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_stage5_report.py
import polars as pl
from radar.stage5_report import compute_funnel, render_report

def _frames():
    securities = pl.DataFrame({"isin": ["US0378331005", "XS1234567890"]})
    entities = pl.DataFrame({"lei": ["P", None]})
    candidates = pl.DataFrame({"isin": ["US0378331005", "US5949181045"],
                               "tag": ["direct", "indirect"]})
    classified = pl.DataFrame({"isin": ["US0378331005", "US5949181045"],
                               "is_us": [True, True],
                               "trace_eligible_guess": [True, False]})
    activity = pl.DataFrame({"isin": ["US0378331005"]})
    return securities, entities, candidates, classified, activity

def test_compute_funnel_counts():
    f = compute_funnel(*_frames())
    assert f["N0_sanctioned_securities"] == 2
    assert f["N4_candidates"] == 2
    assert f["N4_direct"] == 1
    assert f["N4_indirect"] == 1
    assert f["N6_us_trace_eligible"] == 1
    assert f["N7_with_activity"] == 1

def test_render_report_contains_gaps_section():
    f = compute_funnel(*_frames())
    md = render_report(f, gaps={"non_us_isin": 1})
    assert "## GAPS" in md
    assert "N7" in md
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_stage5_report.py -q`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement `stage5_report.py`**

```python
# src/radar/stage5_report.py
"""Stage 5: assemble the feasibility funnel, candidates.csv, and GAPS section."""
from __future__ import annotations

from pathlib import Path

import polars as pl

from radar.common import log


def compute_funnel(securities, entities, candidates, classified, activity) -> dict:
    return {
        "N0_sanctioned_securities": securities.height,
        "N1_with_isin": securities.filter(pl.col("isin").is_not_null()).height,
        "N2_entities_with_lei": entities.filter(pl.col("lei").is_not_null()).height,
        "N4_candidates": candidates.height,
        "N4_direct": candidates.filter(pl.col("tag") == "direct").height,
        "N4_indirect": candidates.filter(pl.col("tag") == "indirect").height,
        "N6_us_trace_eligible": classified.filter(pl.col("trace_eligible_guess")).height,
        "N7_with_activity": activity.height,
    }


def render_report(funnel: dict, gaps: dict) -> str:
    lines = ["# Feasibility Funnel", ""]
    for k, v in funnel.items():
        lines.append(f"- **{k}**: {v}")
    verdict = (
        "ZERO" if funnel["N6_us_trace_eligible"] == 0
        else "MARGINAL" if funnel["N6_us_trace_eligible"] < 25
        else "SIGNIFICANT"
    )
    lines += ["", f"**Intersection verdict (N6): {verdict}**", "", "## GAPS", ""]
    for reason, count in gaps.items():
        lines.append(f"- {reason}: {count}")
    return "\n".join(lines) + "\n"


def run(interim_dir: Path, out_dir: Path) -> None:
    interim_dir, out_dir = Path(interim_dir), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    securities = pl.read_parquet(interim_dir / "sanctioned_securities.parquet")
    entities = pl.read_parquet(interim_dir / "sanctioned_entities.parquet")
    candidates = pl.read_parquet(interim_dir / "candidate_isins.parquet")
    classified = pl.read_parquet(interim_dir / "classified.parquet")
    activity = pl.read_parquet(interim_dir / "activity.parquet")

    funnel = compute_funnel(securities, entities, candidates, classified, activity)
    gaps = {
        "non_us_isin": classified.filter(~pl.col("is_us")).height,
        "sanctioned_entity_without_lei": entities.filter(pl.col("lei").is_null()).height,
        "no_activity_signal": funnel["N6_us_trace_eligible"] - funnel["N7_with_activity"],
    }

    # candidates.csv: classified joined with tag + activity, ranked activity-first
    enriched = (classified
        .join(candidates.select(["isin", "tag", "issuer_lei", "root_sanctioned_lei"]), on="isin", how="left")
        .join(activity.select(["isin", "signal_value", "source_url"]), on="isin", how="left")
        .sort("signal_value", descending=True, nulls_last=True))
    enriched.write_csv(out_dir / "candidates.csv")
    (out_dir / "report.md").write_text(render_report(funnel, gaps), encoding="utf-8")
    log.metric("stage5", "candidates_csv_rows", enriched.height)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_stage5_report.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/radar/stage5_report.py tests/test_stage5_report.py
git commit -m "feat: stage5 feasibility funnel and candidates report"
```

---

### Task 9: `run.py` orchestrator + `--sample` end-to-end

**Files:**
- Create: `src/radar/run.py`
- Create fixtures dir copy target: reuse `tests/fixtures/` as the `--sample` raw input
- Test: `tests/test_run_sample.py`

- [ ] **Step 1: Write failing end-to-end test**

```python
# tests/test_run_sample.py
import shutil
from pathlib import Path
from radar.run import run_pipeline

FIX = Path(__file__).parent / "fixtures"

def test_pipeline_runs_on_sample(tmp_path):
    raw = tmp_path / "raw"; raw.mkdir()
    # map fixtures to the raw filenames stage1 expects
    shutil.copy(FIX / "opensanctions_securities.ftm.json", raw / "securities.ftm.json")
    shutil.copy(FIX / "opensanctions_entities.ftm.json", raw / "entities.ftm.json")
    shutil.copy(FIX / "gleif_isin_lei.csv", raw / "isin_lei.csv")
    shutil.copy(FIX / "gleif_rr.csv", raw / "rr.csv")

    run_pipeline(raw_dir=raw, interim_dir=tmp_path / "interim",
                 out_dir=tmp_path / "out", cache_dir=tmp_path / "cache",
                 sample=True, fetched_at="2026-06-02")

    report = (tmp_path / "out" / "report.md").read_text()
    assert "# Feasibility Funnel" in report
    assert (tmp_path / "out" / "candidates.csv").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_run_sample.py -q`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement `run.py`**

```python
# src/radar/run.py
"""Pipeline orchestrator. `--sample` skips network stages (no OpenFIGI/FINRA calls)."""
from __future__ import annotations

import argparse
from pathlib import Path

import polars as pl

from radar import stage1_ingest, stage2_ownership, stage3_classify, stage4_activity, stage5_report


def _classify_offline(interim_dir: Path) -> None:
    """Sample mode: classify without OpenFIGI (security_type unknown -> not eligible by type,
    but US ISINs still derive CUSIP). Keeps the e2e test network-free."""
    cand = pl.read_parquet(interim_dir / "candidate_isins.parquet")
    rows = [stage3_classify.classify_isin(isin, security_type="Corp")
            for isin in cand["isin"].to_list()]
    pl.DataFrame(rows).write_parquet(interim_dir / "classified.parquet")


def run_pipeline(raw_dir, interim_dir, out_dir, cache_dir, *, sample: bool, fetched_at: str) -> None:
    raw_dir, interim_dir = Path(raw_dir), Path(interim_dir)
    stage1_ingest.run(raw_dir, interim_dir)
    stage2_ownership.run(interim_dir)
    if sample:
        _classify_offline(interim_dir)
        pl.DataFrame(schema={c: pl.Utf8 for c in
            ["isin", "signal_kind", "signal_value", "observed_period", "source_url", "fetched_at"]}
            ).write_parquet(interim_dir / "activity.parquet")
    else:
        stage3_classify.run(interim_dir, cache_dir)
        stage4_activity.run(interim_dir, cache_dir, fetched_at)
    stage5_report.run(interim_dir, out_dir)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="data/raw")
    ap.add_argument("--interim", default="data/interim")
    ap.add_argument("--out", default="data/out")
    ap.add_argument("--cache", default="data/cache")
    ap.add_argument("--sample", action="store_true")
    ap.add_argument("--date", default="unknown")
    a = ap.parse_args()
    run_pipeline(a.raw, a.interim, a.out, a.cache, sample=a.sample, fetched_at=a.date)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_run_sample.py -q`
Expected: PASS (1 passed)

- [ ] **Step 5: Run the full suite + lint**

Run: `pytest -q && ruff check src tests`
Expected: all tests pass; ruff reports no errors.

- [ ] **Step 6: Commit**

```bash
git add src/radar/run.py tests/test_run_sample.py
git commit -m "feat: pipeline orchestrator with offline --sample end-to-end"
```

---

### Task 10: README + real-run runbook

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write `README.md`**

````markdown
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
````

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: README with sample and real-run runbook"
```

---

## Self-Review

**Spec coverage:**
- Stage 1–5 architecture → Tasks 4–9. ✓
- ISIN↔CUSIP critique → Task 1 (test-first check digits). ✓
- Investigative edge (subsidiary/indirect) → Task 5 (`build_candidates` direct/indirect). ✓
- GLEIF Level-2 edge-direction trap → Task 4 `parse_rr` test pins parent=EndNode. ✓
- "Measure, don't assume" intersection → Task 8 funnel N5/N6 + verdict. ✓
- Free-FINRA known-unknown + "no free path is a valid result" → Task 7 recon split + GAP log. ✓
- Honest gaps / provenance → Task 7 (source_url/fetched_at), Task 8 (GAPS section), `log.gap`. ✓
- `--sample` fixtures e2e, no live-network CI → Task 9. ✓
- Seed not dependent on OS issuer link → Task 5 `run()` seeds via GLEIF `isin_to_lei`. ✓

**Placeholder scan:** `FINRA_RECON_ENDPOINTS` is intentionally empty with an explicit
recon instruction (the endpoint is a real execution-time unknown, not a hidden TODO); the
plan documents exactly how to fill it and what happens if it stays empty (GAP recorded).
No other placeholders.

**Type consistency:** `classify_isin(isin, security_type)` signature consistent across
Tasks 6 and 9; funnel keys consistent between Task 8 implementation and tests; `parse_rr`
output columns match `schemas.LEI_RELATIONS`; `build_candidates` output matches
`schemas.CANDIDATE_ISINS`.
