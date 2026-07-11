"""Tests for rate-limit-aware snapshot fetch (429 + X-Rate-Limit-Remaining)."""

from __future__ import annotations

import httpx
import pytest

import flight_stream.fetch as fetch_mod
from flight_ingest.config import Settings
from flight_stream.fetch import RateLimited, fetch_snapshot_with_meta


def _settings() -> Settings:
    return Settings(
        lake_root="/tmp/lake",
        data_dir="/tmp/raw",  # type: ignore[arg-type]
        ssl_verify=True,
        http_timeout=10.0,
        request_pause_sec=0.0,
        max_retries=1,
        user_agent="test",
        opensky_client_id=None,
        opensky_client_secret=None,
    )


class _FakeResponse:
    def __init__(self, status_code, json_data=None, headers=None) -> None:
        self.status_code = status_code
        self._json = json_data or {}
        self.headers = headers or {}

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=None, response=None)


class _FakeClient:
    def __init__(self, response) -> None:
        self._response = response

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url, params=None):
        return self._response


def _patch_client(monkeypatch, response):
    monkeypatch.setattr(fetch_mod, "make_client", lambda settings, **kw: _FakeClient(response))


def test_success_parses_and_reads_remaining(monkeypatch):
    raw = {
        "time": 1781639300,
        "states": [
            ["ab1644", "UAL1091 ", "US", 0, 0, -96.42, 29.33, 6000.0, False,
             209.6, 43.6, -1.0, None, 6606.5, None, False, 0],
        ],
    }
    resp = _FakeResponse(200, raw, {"X-Rate-Limit-Remaining": "742"})
    _patch_client(monkeypatch, resp)

    result = fetch_snapshot_with_meta(_settings(), token=None)
    assert result.rate_limit_remaining == 742
    assert result.snapshot["count"] == 1
    assert result.snapshot["source"] == "live"
    assert result.snapshot["aircraft"][0]["icao24"] == "ab1644"


def test_429_raises_rate_limited_with_retry_after(monkeypatch):
    resp = _FakeResponse(429, {}, {"Retry-After": "120", "X-Rate-Limit-Remaining": "0"})
    _patch_client(monkeypatch, resp)

    with pytest.raises(RateLimited) as ei:
        fetch_snapshot_with_meta(_settings(), token=None)
    assert ei.value.retry_after == 120


def test_429_without_retry_after_is_none(monkeypatch):
    resp = _FakeResponse(429, {}, {})
    _patch_client(monkeypatch, resp)

    with pytest.raises(RateLimited) as ei:
        fetch_snapshot_with_meta(_settings(), token=None)
    assert ei.value.retry_after is None


def test_missing_remaining_header_is_none(monkeypatch):
    resp = _FakeResponse(200, {"time": 1, "states": []}, {})
    _patch_client(monkeypatch, resp)

    result = fetch_snapshot_with_meta(_settings(), token=None)
    assert result.rate_limit_remaining is None
    assert result.snapshot["count"] == 0
