"""HTTP GET/POST client with on-disk JSON cache, retry, and a minimum request interval."""
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
        data = self._with_retry(lambda: self._do_get(url, params))
        path.write_text(json.dumps(data), encoding="utf-8")
        return data

    def post_json(self, url: str, *, body) -> dict | list:
        key = url + "|POST|" + json.dumps(body, sort_keys=True)
        path = self._cache_path(key)
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        data = self._with_retry(lambda: self._do_post(url, body))
        path.write_text(json.dumps(data), encoding="utf-8")
        return data

    def _do_get(self, url, params):
        resp = self._client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()

    def _do_post(self, url, body):
        resp = self._client.post(url, json=body)
        resp.raise_for_status()
        return resp.json()

    def _throttle(self) -> None:
        if self.min_interval:
            wait = self.min_interval - (time.monotonic() - self._last_request)
            if wait > 0:
                time.sleep(wait)
        self._last_request = time.monotonic()

    def _with_retry(self, fn):
        last_exc = None
        for attempt in range(self.max_retries):
            self._throttle()
            try:
                return fn()
            except (httpx.HTTPError, ValueError) as exc:  # ValueError = bad JSON
                last_exc = exc
                time.sleep(0.5 * (attempt + 1))
        raise RuntimeError(f"request failed after {self.max_retries} attempts") from last_exc
