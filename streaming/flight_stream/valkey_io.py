"""Valkey (Redis-protocol) helpers: connection, viewer gate read, position writes.

All keys go through ``flight_contracts.valkey_key`` so the ``flight:`` prefix and
key layout stay consistent with the serving API.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import redis

from flight_contracts import valkey_key

from .config import StreamSettings

log = logging.getLogger("flight_stream.valkey")

# Canonical keys (the serving API reads these for /api/live/positions).
KEY_POSITIONS_LATEST = valkey_key("positions", "latest")
KEY_POSITIONS_CACHED = valkey_key("positions", "cached")
KEY_VIEWER_LAST_SEEN = valkey_key("viewer", "last_seen")


def make_valkey(settings: StreamSettings) -> "redis.Redis":
    """Create a Valkey client (decode_responses so we get str, not bytes)."""
    return redis.Redis(
        host=settings.valkey_host,
        port=settings.valkey_port,
        db=settings.valkey_db,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=5,
    )


def read_viewer_last_seen(client: "redis.Redis", settings: StreamSettings) -> str | None:
    """Read ``flight:viewer:last_seen`` (epoch seconds as a string) or None."""
    return client.get(KEY_VIEWER_LAST_SEEN)


def write_positions(client: "redis.Redis", payload: dict[str, Any], settings: StreamSettings) -> None:
    """Write the positions payload to BOTH the live and cached keys.

    * ``positions:latest`` — short TTL: the live view. If it expires, the
      serving API knows live data went stale.
    * ``positions:cached`` — long TTL fallback so the map is never empty even if
      the producer/OpenSky go down for a while (the API relabels source as
      "cached" when serving from here).
    """
    blob = json.dumps(payload)
    client.set(KEY_POSITIONS_LATEST, blob, ex=settings.positions_ttl_seconds)

    cached = dict(payload)
    cached["source"] = "cached"
    client.set(
        KEY_POSITIONS_CACHED,
        json.dumps(cached),
        ex=settings.positions_cached_ttl_seconds,
    )
    log.info(
        "Wrote %s (ttl=%ds) and %s (ttl=%ds): %d aircraft.",
        KEY_POSITIONS_LATEST,
        settings.positions_ttl_seconds,
        KEY_POSITIONS_CACHED,
        settings.positions_cached_ttl_seconds,
        payload.get("count", 0),
    )
