"""OpenSky one-shot snapshot fetcher.

Scope: a single ``states/all`` snapshot over the US bbox, used to (a) generate a
bundled sample positions file and (b) optional backfill. The continuous polling
daemon belongs to the ``streaming/`` component — NOT here.

Auth: OAuth2 client-credentials when creds are present (4000 credits/day),
otherwise anonymous (400/day) with a logged warning. Never crashes on missing
creds. Output dicts match the api_contract ``aircraft`` shape.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from flight_contracts import US_BBOX

from ._http import get_with_retry, make_client
from .config import OPENSKY_STATES_URL, OPENSKY_TOKEN_URL, Settings

log = logging.getLogger("flight_ingest.opensky")

# OpenSky state-vector array indices (subset we expose).
IDX_ICAO24 = 0
IDX_CALLSIGN = 1
IDX_LON = 5
IDX_LAT = 6
IDX_BARO_ALT = 7
IDX_ON_GROUND = 8
IDX_VELOCITY = 9
IDX_TRUE_TRACK = 10
IDX_GEO_ALT = 13


def parse_state_vector(state: list) -> dict | None:
    """Map one OpenSky state-vector array to the api_contract aircraft shape.

    Returns None for entries with no usable position (lat/lon both missing).
    Prefers geometric altitude, falling back to barometric.
    """

    def at(i: int):
        return state[i] if len(state) > i else None

    lat = at(IDX_LAT)
    lon = at(IDX_LON)
    if lat is None or lon is None:
        return None

    callsign = at(IDX_CALLSIGN)
    altitude = at(IDX_GEO_ALT)
    if altitude is None:
        altitude = at(IDX_BARO_ALT)

    return {
        "icao24": at(IDX_ICAO24),
        "callsign": (callsign or "").strip() or None,
        "lat": lat,
        "lon": lon,
        "altitude": altitude,
        "velocity": at(IDX_VELOCITY),
        "heading": at(IDX_TRUE_TRACK),
        "on_ground": bool(at(IDX_ON_GROUND)),
    }


def parse_states_payload(payload: dict) -> list[dict]:
    """Parse a full states/all payload into clean aircraft dicts."""
    states = payload.get("states") or []
    out: list[dict] = []
    for s in states:
        parsed = parse_state_vector(s)
        if parsed is not None:
            out.append(parsed)
    return out
