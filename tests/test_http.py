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


def test_post_json_cache_hit(tmp_path):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    client = CachedClient(cache_dir=tmp_path, transport=transport)

    r1 = client.post_json("https://example.test/m", body=[{"a": 1}])
    r2 = client.post_json("https://example.test/m", body=[{"a": 1}])

    assert r1 == r2 == {"ok": True}
    assert calls["n"] == 1
