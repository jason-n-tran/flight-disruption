"""Tests for the producer poll cycle: viewer-gating drives cadence + skips."""

from __future__ import annotations

import json

import fakeredis
import pytest

import flight_stream.producer as producer_mod
from flight_stream.config import load_settings
from flight_stream.fetch import RateLimited, SnapshotResult
from flight_stream.producer import _poll_once
from flight_stream.valkey_io import KEY_VIEWER_LAST_SEEN


class _FakeJS:
    def __init__(self) -> None:
        self.published = []

    async def publish(self, subject, data):
        self.published.append((subject, data))


def _ingest_settings():
    from flight_ingest.config import load_settings as ld
    return ld()


def _snapshot(n=3):
    return {
        "as_of": 1781639300, "stale_seconds": 0, "source": "live", "count": n,
        "aircraft": [{"icao24": str(i)} for i in range(n)],
    }


class _TokenCache:
    def get_token(self, force_refresh=False):
        return None


@pytest.fixture
def settings():
    return load_settings()


async def test_idle_when_no_viewer_skips_opensky(monkeypatch, settings):
    valkey = fakeredis.FakeRedis(decode_responses=True)  # no viewer key set
    js = _FakeJS()

    called = {"fetch": 0}

    def fake_fetch(*a, **k):
        called["fetch"] += 1
        return SnapshotResult(snapshot=_snapshot(), rate_limit_remaining=10)

    monkeypatch.setattr(producer_mod, "fetch_snapshot_with_meta", fake_fetch)

    sleep_for = await _poll_once(settings, _ingest_settings(), _TokenCache(), valkey, js)

    assert sleep_for == settings.idle_interval_seconds
    assert called["fetch"] == 0       # no OpenSky call when idle
    assert js.published == []          # nothing published


async def test_active_viewer_polls_and_publishes(monkeypatch, settings):
    import time

    valkey = fakeredis.FakeRedis(decode_responses=True)
    valkey.set(KEY_VIEWER_LAST_SEEN, str(int(time.time())))  # viewer just now
    js = _FakeJS()

    monkeypatch.setattr(
        producer_mod,
        "fetch_snapshot_with_meta",
        lambda *a, **k: SnapshotResult(snapshot=_snapshot(5), rate_limit_remaining=10),
    )

    sleep_for = await _poll_once(settings, _ingest_settings(), _TokenCache(), valkey, js)

    assert sleep_for == settings.poll_interval_seconds
    assert len(js.published) == 1
    subject, data = js.published[0]
    assert subject == settings.subject
    assert json.loads(data)["count"] == 5


async def test_rate_limited_backs_off_retry_after(monkeypatch, settings):
    import time

    valkey = fakeredis.FakeRedis(decode_responses=True)
    valkey.set(KEY_VIEWER_LAST_SEEN, str(int(time.time())))
    js = _FakeJS()

    def fake_fetch(*a, **k):
        raise RateLimited(retry_after=222)

    monkeypatch.setattr(producer_mod, "fetch_snapshot_with_meta", fake_fetch)

    sleep_for = await _poll_once(settings, _ingest_settings(), _TokenCache(), valkey, js)
    assert sleep_for == 222
    assert js.published == []


async def test_fetch_error_does_not_crash(monkeypatch, settings):
    import time

    valkey = fakeredis.FakeRedis(decode_responses=True)
    valkey.set(KEY_VIEWER_LAST_SEEN, str(int(time.time())))
    js = _FakeJS()

    def boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(producer_mod, "fetch_snapshot_with_meta", boom)

    sleep_for = await _poll_once(settings, _ingest_settings(), _TokenCache(), valkey, js)
    # Survives: returns the normal poll interval to retry next cycle.
    assert sleep_for == settings.poll_interval_seconds
    assert js.published == []
