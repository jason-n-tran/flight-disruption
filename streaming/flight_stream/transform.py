"""Pure transforms: raw OpenSky snapshot -> api_contract positions payload,
plus the viewer-gated interval decision. No I/O here, so it is trivially tested.
"""

from __future__ import annotations

import time
from typing import Any

from flight_ingest.opensky import parse_states_payload

# Fields the consumer guarantees on every aircraft entry, per api_contract.md.
AIRCRAFT_FIELDS = (
    "icao24",
    "callsign",
    "lat",
    "lon",
    "altitude",
    "velocity",
    "heading",
    "on_ground",
)


def _coerce_aircraft(entry: dict[str, Any]) -> dict[str, Any]:
    """Project one parsed entry onto exactly the contract aircraft fields."""
    return {field: entry.get(field) for field in AIRCRAFT_FIELDS}


def snapshot_to_payload(
    raw: dict[str, Any],
    *,
    now: int | None = None,
    source: str = "live",
) -> dict[str, Any]:
    """Transform a snapshot into the ``/api/live/positions`` payload.

    Accepts EITHER:
    * a raw OpenSky ``states/all`` payload (has a ``states`` list), or
    * an already-parsed ``flight_ingest.fetch_snapshot`` dict (has ``aircraft``).

    The producer publishes ``fetch_snapshot`` output (already parsed) over NATS;
    accepting the raw form too keeps the transform usable standalone/in tests.
    """
    now = int(now if now is not None else time.time())

    if "aircraft" in raw:
        aircraft = [_coerce_aircraft(a) for a in (raw.get("aircraft") or [])]
        as_of = int(raw.get("as_of") or now)
    else:
        aircraft = [_coerce_aircraft(a) for a in parse_states_payload(raw)]
        as_of = int(raw.get("time") or now)

    return {
        "as_of": as_of,
        "stale_seconds": max(0, now - as_of),
        "source": source,
        "count": len(aircraft),
        "aircraft": aircraft,
    }


def viewer_is_active(
    last_seen: float | int | str | None,
    *,
    window_seconds: int,
    now: float | None = None,
) -> bool:
    """True if a viewer was seen within ``window_seconds`` of now.

    ``last_seen`` is whatever Valkey returned for ``flight:viewer:last_seen``
    (a unix-epoch string/number) or None when nobody has ever viewed.
    """
    if last_seen is None:
        return False
    try:
        ts = float(last_seen)
    except (TypeError, ValueError):
        return False
    now = time.time() if now is None else now
    return (now - ts) <= window_seconds


def choose_interval(
    last_seen: float | int | str | None,
    *,
    poll_interval_seconds: int,
    idle_interval_seconds: int,
    viewer_active_window_seconds: int,
    now: float | None = None,
) -> int:
    """Viewer-gated cadence: short interval if a viewer is active, else idle."""
    if viewer_is_active(
        last_seen, window_seconds=viewer_active_window_seconds, now=now
    ):
        return poll_interval_seconds
    return idle_interval_seconds
