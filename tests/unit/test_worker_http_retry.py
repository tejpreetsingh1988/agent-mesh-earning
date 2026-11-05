"""Batch 35: fetch_bytes retries transient EDGAR failures
(HTTP 429 from the Workers' shared egress IPs) with backoff,
and never retries a permanent 4xx."""
import asyncio
import urllib.error

import mesh.worker_http as wh


class _Resp:
    def __init__(self, status, body=b"ok"):
        self.status = status
        self._body = body

    async def bytes(self):
        return self._body


def _fake_pyfetch_factory(results):
    """A fake pyfetch: each call pops the next result — either a
    _Resp or an exception to raise."""
    calls = {"n": 0}

    async def fake(url, headers=None):
        calls["n"] += 1
        r = results.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    fake.calls = calls
    return fake


def test_pyfetch_retries_429_then_succeeds(monkeypatch):
    monkeypatch.setattr(wh, "FETCH_RETRY_DELAYS_S", (0, 0))
    fake = _fake_pyfetch_factory([
        wh.WorkerHTTPError(429, "https://example.com/x"),
        wh.WorkerHTTPError(429, "https://example.com/x"),
        _Resp(200, b"third time"),
    ])
    monkeypatch.setattr(wh, "_pyfetch", lambda: fake)
    assert asyncio.run(wh.fetch_bytes("https://example.com/x")) == b"third time"
    assert fake.calls["n"] == 3


def test_pyfetch_does_not_retry_404(monkeypatch):
    monkeypatch.setattr(wh, "FETCH_RETRY_DELAYS_S", (0, 0))
    fake = _fake_pyfetch_factory([_Resp(404)])
    monkeypatch.setattr(wh, "_pyfetch", lambda: fake)
    try:
        asyncio.run(wh.fetch_bytes("https://example.com/x"))
        raise AssertionError("expected WorkerHTTPError")
    except wh.WorkerHTTPError as e:
        assert e.code == 404
    assert fake.calls["n"] == 1


def test_pyfetch_gives_up_after_three_429s(monkeypatch):
    monkeypatch.setattr(wh, "FETCH_RETRY_DELAYS_S", (0, 0))
    fake = _fake_pyfetch_factory([wh.WorkerHTTPError(429, "u")] * 3)
    monkeypatch.setattr(wh, "_pyfetch", lambda: fake)
    try:
        asyncio.run(wh.fetch_bytes("https://example.com/x"))
        raise AssertionError("expected WorkerHTTPError")
    except wh.WorkerHTTPError as e:
        assert e.code == 429
    assert fake.calls["n"] == 3


def test_pyfetch_attempt_timeout_retries(monkeypatch):
    """A hung pyfetch is cut off per attempt and retried."""
    monkeypatch.setattr(wh, "FETCH_RETRY_DELAYS_S", (0, 0))
    monkeypatch.setattr(wh, "FETCH_ATTEMPT_TIMEOUT_S", 0.05)

    async def slow(url, headers=None):
        await asyncio.sleep(0.5)
        return _Resp(200, b"too late")

    monkeypatch.setattr(wh, "_pyfetch", lambda: slow)
    try:
        asyncio.run(wh.fetch_bytes("https://example.com/x"))
        raise AssertionError("expected TimeoutError")
    except (TimeoutError, asyncio.TimeoutError):
        pass


def test_sync_path_retries_429(monkeypatch):
    """Outside a Worker the sync (urllib) path retries too."""
    monkeypatch.setattr(wh, "FETCH_RETRY_DELAYS_S", (0, 0))
    monkeypatch.setattr(wh, "_pyfetch", lambda: None)
    calls = {"n": 0}

    class _FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b"synced"

        @property
        def headers(self):
            return {}

    def fake_urlopen(req, timeout=None):
        calls["n"] += 1
        if calls["n"] < 3:
            raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {}, None)
        return _FakeResp()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert asyncio.run(wh.fetch_bytes("https://example.com/x")) == b"synced"
    assert calls["n"] == 3
