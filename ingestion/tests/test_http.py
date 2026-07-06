"""Retry helper: honors Retry-After, caps backoff, retries 429/5xx, fails 4xx."""

from __future__ import annotations

import httpx
import pytest

from flight_ingest import _http


def _resp(status: int, headers: dict | None = None) -> httpx.Response:
    req = httpx.Request("GET", "https://example.test/x")
    return httpx.Response(status, headers=headers or {}, request=req)


def test_retry_after_seconds_parses_delta():
    assert _http._retry_after_seconds(_resp(429, {"Retry-After": "12"})) == 12.0
    assert _http._retry_after_seconds(_resp(429, {})) is None
    assert _http._retry_after_seconds(_resp(429, {"Retry-After": "junk"})) is None
    assert _http._retry_after_seconds(None) is None


def test_429_honors_retry_after_then_succeeds(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr(_http.time, "sleep", lambda s: sleeps.append(s))

    seq = [_resp(429, {"Retry-After": "7"}), _resp(200)]

    class _Client:
        def get(self, url, **kw):
            return seq.pop(0)

    out = _http.get_with_retry(_Client(), "https://example.test/x",
                               max_retries=3, pause=0.5, max_backoff=60)
    assert out.status_code == 200
    assert sleeps == [7.0]  # used Retry-After, not exponential backoff


def test_backoff_is_capped(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr(_http.time, "sleep", lambda s: sleeps.append(s))

    class _Client:
        def get(self, url, **kw):
            return _resp(500)  # always retryable, no Retry-After

    with pytest.raises(httpx.HTTPStatusError):
        _http.get_with_retry(_Client(), "https://example.test/x",
                             max_retries=10, pause=1.0, max_backoff=8.0)
    # exponential 1,2,4,8,8,8,... never exceeds the cap
    assert max(sleeps) <= 8.0
    assert sleeps[:4] == [1.0, 2.0, 4.0, 8.0]


def test_4xx_fails_fast(monkeypatch):
    monkeypatch.setattr(_http.time, "sleep", lambda s: None)

    class _Client:
        def get(self, url, **kw):
            return _resp(404)

    with pytest.raises(httpx.HTTPStatusError):
        _http.get_with_retry(_Client(), "https://example.test/x",
                             max_retries=3, pause=0.1)
