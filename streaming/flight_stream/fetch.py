"""Rate-limit-aware OpenSky snapshot fetch for the continuous producer.

Reuses ``flight_ingest`` for the HTTP client, the state-vector parser, and the
payload shape — this module only adds what continuous polling needs and the
one-shot fetcher deliberately omits: inspecting ``X-Rate-Limit-Remaining`` and
honoring ``Retry-After`` on 429s.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from flight_contracts import US_BBOX
from flight_ingest._http import make_client
from flight_ingest.config import OPENSKY_STATES_URL, Settings
from flight_ingest.opensky import parse_states_payload

log = logging.getLogger("flight_stream.fetch")


class RateLimited(Exception):
    """Raised on HTTP 429. ``retry_after`` is seconds to wait (best effort)."""

    def __init__(self, retry_after: int | None) -> None:
        super().__init__(f"OpenSky rate limited (retry_after={retry_after})")
        self.retry_after = retry_after


@dataclass
class SnapshotResult:
    """A parsed snapshot plus the rate-limit telemetry we logged it with."""

    snapshot: dict
    rate_limit_remaining: int | None


def _parse_retry_after(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError):
        return None


def fetch_snapshot_with_meta(settings: Settings, token: str | None) -> SnapshotResult:
    """Fetch one US-bbox snapshot, returning the contract payload + RL header.

    Raises :class:`RateLimited` on 429 (caller backs off, honoring Retry-After);
    raises for other transport/HTTP errors (caller logs + retries the loop).
    """
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    params = US_BBOX.as_params()
    with make_client(settings, headers=headers) as client:
        resp = client.get(OPENSKY_STATES_URL, params=params)

        remaining_raw = resp.headers.get("X-Rate-Limit-Remaining")
        remaining = None
        if remaining_raw is not None:
            try:
                remaining = int(remaining_raw)
            except ValueError:
                remaining = None

        if resp.status_code == 429:
            retry_after = _parse_retry_after(resp.headers.get("Retry-After"))
            log.warning(
                "OpenSky 429 rate limited (remaining=%s, retry_after=%s).",
                remaining,
                retry_after,
            )
            raise RateLimited(retry_after)

        resp.raise_for_status()
        payload = resp.json()

    aircraft = parse_states_payload(payload)
    as_of = int(payload.get("time") or time.time())
    snapshot = {
        "as_of": as_of,
        "stale_seconds": max(0, int(time.time()) - as_of),
        "source": "live",
        "count": len(aircraft),
        "aircraft": aircraft,
    }
    if remaining is not None:
        log.info(
            "OpenSky snapshot ok: %d aircraft, X-Rate-Limit-Remaining=%d.",
            len(aircraft),
            remaining,
        )
    else:
        log.info("OpenSky snapshot ok: %d aircraft.", len(aircraft))
    return SnapshotResult(snapshot=snapshot, rate_limit_remaining=remaining)
