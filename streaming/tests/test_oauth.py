"""Tests for TokenCache: caching, refresh-before-expiry, anonymous mode."""

from __future__ import annotations

from flight_ingest.config import Settings
from flight_stream.oauth import TokenCache


def _settings(*, creds: bool) -> Settings:
    return Settings(
        lake_root="/tmp/lake",
        data_dir="/tmp/raw",  # type: ignore[arg-type]
        ssl_verify=True,
        http_timeout=10.0,
        request_pause_sec=0.0,
        max_retries=1,
        user_agent="test",
        opensky_client_id="id" if creds else None,
        opensky_client_secret="secret" if creds else None,
    )


class _Clock:
    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def test_token_cached_between_calls():
    calls = {"n": 0}

    def fetch(_s):
        calls["n"] += 1
        return f"token-{calls['n']}"

    clock = _Clock(0.0)
    cache = TokenCache(_settings(creds=True), ttl_seconds=1800,
                       refresh_margin_seconds=60, fetcher=fetch, clock=clock)

    assert cache.get_token() == "token-1"
    clock.t = 100  # well before expiry
    assert cache.get_token() == "token-1"  # reused, not refetched
    assert calls["n"] == 1


def test_token_refreshes_before_expiry():
    calls = {"n": 0}

    def fetch(_s):
        calls["n"] += 1
        return f"token-{calls['n']}"

    clock = _Clock(0.0)
    cache = TokenCache(_settings(creds=True), ttl_seconds=1800,
                       refresh_margin_seconds=60, fetcher=fetch, clock=clock)

    assert cache.get_token() == "token-1"   # expires_at = 1800
    clock.t = 1700                           # still > expires_at - margin(1740)? no
    assert cache.get_token() == "token-1"
    clock.t = 1745                           # within margin -> refresh
    assert cache.get_token() == "token-2"
    assert calls["n"] == 2


def test_force_refresh():
    calls = {"n": 0}

    def fetch(_s):
        calls["n"] += 1
        return f"token-{calls['n']}"

    cache = TokenCache(_settings(creds=True), fetcher=fetch, clock=_Clock(0.0))
    assert cache.get_token() == "token-1"
    assert cache.get_token(force_refresh=True) == "token-2"


def test_anonymous_mode_fetches_once_returns_none():
    calls = {"n": 0}

    def fetch(_s):
        calls["n"] += 1
        return None  # ingest returns None when no creds

    cache = TokenCache(_settings(creds=False), fetcher=fetch, clock=_Clock(0.0))
    assert cache.authenticated is False
    assert cache.get_token() is None
    assert cache.get_token() is None
    assert calls["n"] == 1  # short-circuited, no repeated network attempts


def test_failed_refresh_degrades_to_anonymous_then_retries():
    seq = [None, "token-good"]

    def fetch(_s):
        return seq.pop(0)

    clock = _Clock(0.0)
    cache = TokenCache(_settings(creds=True), ttl_seconds=1800,
                       refresh_margin_seconds=60, fetcher=fetch, clock=clock)

    # First call: exchange fails -> None, short expiry so next cycle retries.
    assert cache.get_token() is None
    clock.t = 100
    # Next cycle retries and succeeds.
    assert cache.get_token() == "token-good"
