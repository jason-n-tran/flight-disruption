"""Env-driven configuration for the live stream.

Every value is overridable via environment variables (see ``.env.example``).
Sensible defaults keep a fresh clone runnable; missing OpenSky creds degrade to
anonymous fetches (handled inside ``flight_ingest``).
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return float(raw)


@dataclass(frozen=True)
class StreamSettings:
    """Resolved live-stream settings.

    Attributes
    ----------
    nats_url:
        NATS server URL (JetStream enabled). Prod: TrueNAS NATS.
    subject:
        JetStream subject snapshots are published to / consumed from.
    stream_name:
        JetStream stream that binds ``subject``.
    valkey_host / valkey_port / valkey_db:
        Valkey (Redis-protocol) connection. Prod: shared TrueNAS Valkey.
    poll_interval_seconds:
        Active poll cadence when a viewer was seen recently. Default 60s — safe
        because viewer-gating means we are not polling 24/7 (see README credit
        math: 4000 credits/day / 4 per US-bbox call = ~1000 calls/day).
    idle_interval_seconds:
        Back-off cadence when NO viewer has been seen within
        ``viewer_active_window_seconds``. Default 600s (10 min) — keeps the
        producer cheap when nobody is watching the map.
    viewer_active_window_seconds:
        A viewer is "recent" if ``flight:viewer:last_seen`` is within this many
        seconds of now. The serving API refreshes that key on live requests.
    positions_ttl_seconds:
        TTL on the fresh ``flight:positions:latest`` key (live).
    positions_cached_ttl_seconds:
        TTL on the longer-lived ``flight:positions:cached`` fallback key.
    rate_limit_backoff_seconds:
        Default sleep when a 429 lacks a usable ``Retry-After`` header.
    """

    # --- NATS ---
    nats_url: str
    subject: str
    stream_name: str

    # --- Valkey ---
    valkey_host: str
    valkey_port: int
    valkey_db: int

    # --- polling cadence (viewer-gated) ---
    poll_interval_seconds: int
    idle_interval_seconds: int
    viewer_active_window_seconds: int

    # --- cache TTLs ---
    positions_ttl_seconds: int
    positions_cached_ttl_seconds: int

    # --- resilience ---
    rate_limit_backoff_seconds: int


def load_settings() -> StreamSettings:
    """Build :class:`StreamSettings` from the current environment."""
    return StreamSettings(
        nats_url=os.environ.get("NATS_URL", "nats://localhost:4223"),
        subject=os.environ.get("NATS_SUBJECT", "flight.positions"),
        stream_name=os.environ.get("NATS_STREAM", "FLIGHT_POSITIONS"),
        valkey_host=os.environ.get("VALKEY_HOST", "localhost"),
        valkey_port=_env_int("VALKEY_PORT", 6379),
        valkey_db=_env_int("VALKEY_DB", 0),
        poll_interval_seconds=_env_int("POLL_INTERVAL_SECONDS", 60),
        idle_interval_seconds=_env_int("IDLE_INTERVAL_SECONDS", 600),
        viewer_active_window_seconds=_env_int("VIEWER_ACTIVE_WINDOW_SECONDS", 300),
        positions_ttl_seconds=_env_int("POSITIONS_TTL_SECONDS", 300),
        positions_cached_ttl_seconds=_env_int("POSITIONS_CACHED_TTL_SECONDS", 86400),
        rate_limit_backoff_seconds=_env_int("RATE_LIMIT_BACKOFF_SECONDS", 60),
    )
