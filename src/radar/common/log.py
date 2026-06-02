"""Tiny structured logger so every stage reports row counts and dropped rows."""
from __future__ import annotations

import sys


def metric(stage: str, name: str, value: int | str) -> None:
    print(f"[{stage}] {name}={value}", file=sys.stderr)


def gap(stage: str, reason: str, count: int) -> None:
    print(f"[{stage}] GAP reason={reason!r} count={count}", file=sys.stderr)
