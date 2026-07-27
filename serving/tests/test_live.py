"""Unit tests for the live-positions viewer gate + Valkey fallback chain."""

from __future__ import annotations

import json
import time

from flight_serving.live import (
    LivePositions,
    _POSITIONS_CACHED_KEY,
    _POSITIONS_KEY,
    _VIEWER_KEY,
)


class _FakeValkey:
    """Minimal in-memory stand-in for the redis/valkey client."""

    def __init__(self, initial: dict | None = None):
        self.store: dict[str, str] = dict(initial or {})
        self.sets: list[tuple[str, str, int | None]] = []

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ex=None):
        self.store[key] = value
        self.sets.append((key, value, ex))


def _live_with(client) -> LivePositions:
    # Build without touching real Valkey, then inject the fake client.
    lp = LivePositions.__new__(LivePositions)
    import threading
    lp.settings = type("S", (), {"live_fresh_seconds": 120})()
    lp._client = client
    lp._lock = threading.Lock()
    lp._last_good = None
    lp._sample = None
    return lp


def _payload(as_of: int) -> str:
    return json.dumps({
        "as_of": as_of,
        "aircraft": [{"icao24": "abc", "lat": 33.6, "lon": -84.4, "callsign": "DAL1"}],
    })


def test_touch_viewer_stamps_key_with_ttl():
    fake = _FakeValkey()
    lp = _live_with(fake)
    lp.touch_viewer()
    assert _VIEWER_KEY in fake.store
    # value is an epoch-second string and a TTL was set
    key, val, ex = fake.sets[-1]
    assert key == _VIEWER_KEY
    assert val.isdigit()
    assert ex and ex > 0


def test_touch_viewer_noop_without_client():
    lp = _live_with(None)
    lp.touch_viewer()  # must not raise


def test_fresh_latest_is_source_live():
    fake = _FakeValkey({_POSITIONS_KEY: _payload(int(time.time()))})
    lp = _live_with(fake)
    out = lp.get_positions()
    assert out["source"] == "live"
    assert out["count"] == 1


def test_falls_back_to_cached_key_when_latest_missing():
    # latest expired (absent); cached still present -> still serves real data.
    fake = _FakeValkey({_POSITIONS_CACHED_KEY: _payload(int(time.time()) - 9999)})
    lp = _live_with(fake)
    out = lp.get_positions()
    assert out["count"] == 1
    assert out["source"] == "cached"  # stale -> cached, not live
