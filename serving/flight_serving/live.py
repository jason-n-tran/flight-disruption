"""Live aircraft positions + airport congestion, with a never-empty fallback chain.

The map MUST never be empty. The fallback chain for ``/api/live/positions``:

1. **live**   — read the latest snapshot the streaming consumer wrote to Valkey at
   ``valkey_key("positions", "latest")``; compute ``stale_seconds`` from its
   ``as_of`` timestamp. Used when present and fresh.
2. **cached**  — Valkey reachable but the snapshot is older than the freshness
   window (still real data, just stale) -> ``source: "cached"``.
3. **sample**  — Valkey missing/unreachable/empty -> bundled ``positions.json``.

We also keep the last good payload in-process so a transient Valkey blip still
serves real positions ("cached") rather than dropping to sample.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path

from flight_contracts.contract import valkey_key

from .config import Settings

log = logging.getLogger("flight_serving.live")

_POSITIONS_KEY = valkey_key("positions", "latest")
_POSITIONS_CACHED_KEY = valkey_key("positions", "cached")
_VIEWER_KEY = valkey_key("viewer", "last_seen")
# Keep the viewer signal alive a bit longer than the streaming producer's active
# window so a brief gap between requests doesn't drop it back to idle.
_VIEWER_TTL_SECONDS = 1800


class LivePositions:
    """Owns the Valkey client + fallback chain for live positions."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._client = None
        self._lock = threading.Lock()
        self._last_good: dict | None = None  # last real (Valkey) payload seen
        self._sample: dict | None = None     # lazily loaded bundled sample

        if settings.valkey_enabled:
            self._client = _connect_valkey(settings)

    # ------------------------------------------------------------------
    def touch_viewer(self) -> None:
        """Stamp ``flight:viewer:last_seen`` so the streaming producer knows the
        map is being watched and polls OpenSky (viewer-gated polling). Best
        effort — never raises, never blocks the request on Valkey issues.
        """
        if self._client is None:
            return
        try:
            self._client.set(_VIEWER_KEY, str(int(time.time())), ex=_VIEWER_TTL_SECONDS)
        except Exception as exc:  # noqa: BLE001 — viewer signal is best-effort
            log.debug("Could not stamp viewer key (%s)", exc)

    # ------------------------------------------------------------------
    def get_positions(self) -> dict:
        """Return a valid /api/live/positions payload — always."""
        payload = self._read_valkey()
        if payload is not None:
            with self._lock:
                self._last_good = payload
            stale = _stale_seconds(payload)
            fresh = stale is not None and stale <= self.settings.live_fresh_seconds
            payload["stale_seconds"] = stale if stale is not None else 0
            payload["source"] = "live" if fresh else "cached"
            return payload

        # Valkey unreachable/empty -> try the last good in-process snapshot.
        with self._lock:
            last = self._last_good
        if last is not None:
            out = dict(last)
            out["stale_seconds"] = _stale_seconds(out) or 0
            out["source"] = "cached"
            return out

        # Final fallback: bundled sample.
        return self._sample_payload()

    # ------------------------------------------------------------------
    def _read_valkey(self) -> dict | None:
        if self._client is None:
            return None
        try:
            # Prefer the fresh `latest` key; if it's expired (producer paused or
            # OpenSky briefly down) fall back to the longer-TTL `cached` key,
            # which the producer also writes. Both hold the same payload shape.
            raw = self._client.get(_POSITIONS_KEY) or self._client.get(
                _POSITIONS_CACHED_KEY
            )
        except Exception as exc:  # noqa: BLE001 — Valkey down -> fall back
            log.warning("Valkey read failed (%s); falling back", exc)
            return None
        if not raw:
            return None
        try:
            data = json.loads(raw)
        except (ValueError, TypeError) as exc:
            log.warning("Bad positions JSON in Valkey (%s); falling back", exc)
            return None
        aircraft = data.get("aircraft") or []
        if not aircraft:
            return None
        data.setdefault("as_of", int(time.time()))
        data["count"] = len(aircraft)
        return data

    def _sample_payload(self) -> dict:
        if self._sample is None:
            self._sample = _load_sample(self.settings.positions_sample_path)
        out = dict(self._sample)
        out["source"] = "sample"
        out.setdefault("as_of", 0)
        out["stale_seconds"] = 0
        out["count"] = len(out.get("aircraft") or [])
        return out

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception:  # noqa: BLE001
                pass


# ----------------------------------------------------------------------
# Congestion: count aircraft within ~1.5 degrees of the airport lat/lon.
# ----------------------------------------------------------------------
_CONGESTION_RADIUS_DEG = 1.5


def airport_congestion(positions: dict, lat: float, lon: float) -> dict:
    """Count airborne-ish aircraft near (lat, lon) and bucket into a level."""
    aircraft = positions.get("aircraft") or []
    r = _CONGESTION_RADIUS_DEG
    nearby = 0
    for ac in aircraft:
        alat, alon = ac.get("lat"), ac.get("lon")
        if alat is None or alon is None:
            continue
        if abs(alat - lat) <= r and abs(alon - lon) <= r:
            nearby += 1
    return {"aircraft_nearby": nearby, "level": _congestion_level(nearby)}
