"""Producer: OpenSky -> NATS JetStream subject ``flight.positions``.

Responsibilities
----------------
* Poll OpenSky on a **viewer-gated** cadence (short interval when the map has a
  recent viewer, long idle interval otherwise) — see ``transform.choose_interval``
  and the README credit math.
* Cache + refresh the OAuth token (``oauth.TokenCache``).
* Publish each snapshot to JetStream so the consumer (any number, any pace) can
  pick it up. JetStream persists the last message so a freshly-started consumer
  gets the latest snapshot immediately.
* Be unkillable: every network/broker error is logged and the loop continues.
  429s back off honoring ``Retry-After``.
"""

from __future__ import annotations

import asyncio
import json
import logging

from flight_ingest.config import load_settings as load_ingest_settings

from .config import StreamSettings
from .fetch import RateLimited, fetch_snapshot_with_meta
from .nats_io import connect_jetstream, ensure_stream
from .oauth import TokenCache
from .valkey_io import make_valkey, read_viewer_last_seen
from .transform import choose_interval

log = logging.getLogger("flight_stream.producer")


async def run_producer(
    settings: StreamSettings,
    *,
    stop: asyncio.Event | None = None,
) -> None:
    """Run the polling/publishing loop until ``stop`` is set (or forever)."""
    stop = stop or asyncio.Event()
    ingest_settings = load_ingest_settings()
    token_cache = TokenCache(ingest_settings)

    valkey = make_valkey(settings)
    nc, js = await connect_jetstream(settings)
    await ensure_stream(js, settings)

    log.info(
        "Producer up: subject=%s poll=%ds idle=%ds viewer_window=%ds auth=%s",
        settings.subject,
        settings.poll_interval_seconds,
        settings.idle_interval_seconds,
        settings.viewer_active_window_seconds,
        token_cache.authenticated,
    )

    try:
        while not stop.is_set():
            sleep_for = await _poll_once(settings, ingest_settings, token_cache, valkey, js)
            # Interruptible sleep so a stop signal is honored promptly.
            try:
                await asyncio.wait_for(stop.wait(), timeout=sleep_for)
            except asyncio.TimeoutError:
                pass
    finally:
        try:
            await nc.drain()
        except Exception as exc:  # noqa: BLE001
            log.warning("NATS drain failed on shutdown: %s", exc)


async def _poll_once(
    settings: StreamSettings,
    ingest_settings,
    token_cache: TokenCache,
    valkey,
    js,
) -> int:
    """One poll cycle. Returns how many seconds to sleep before the next one.

    Never raises: all failures degrade to a sensible sleep so the loop survives.
    """
    # Decide cadence from the latest viewer activity each cycle.
    try:
        last_seen = read_viewer_last_seen(valkey, settings)
    except Exception as exc:  # noqa: BLE001 — Valkey down shouldn't kill polling
        log.warning("Could not read viewer last_seen (%s); assuming idle.", exc)
        last_seen = None

    interval = choose_interval(
        last_seen,
        poll_interval_seconds=settings.poll_interval_seconds,
        idle_interval_seconds=settings.idle_interval_seconds,
        viewer_active_window_seconds=settings.viewer_active_window_seconds,
    )

    # Skip the network call entirely when nobody is watching: there is no point
    # spending OpenSky credits to refresh a map no one is looking at.
    if interval >= settings.idle_interval_seconds:
        log.info("No recent viewer — idling %ds (no OpenSky call).", interval)
        return interval

    try:
        token = token_cache.get_token()
        result = fetch_snapshot_with_meta(ingest_settings, token)
    except RateLimited as exc:
        backoff = exc.retry_after or settings.rate_limit_backoff_seconds
        log.warning("Rate limited; backing off %ds.", backoff)
        return backoff
    except Exception as exc:  # noqa: BLE001 — log + retry next cycle, never crash
        log.warning("Snapshot fetch failed (%s); retrying in %ds.", exc, interval)
        return interval

    try:
        await js.publish(settings.subject, json.dumps(result.snapshot).encode("utf-8"))
        log.info("Published snapshot (%d aircraft) to %s.", result.snapshot["count"], settings.subject)
    except Exception as exc:  # noqa: BLE001 — broker hiccup; retry next cycle
        log.warning("Publish to NATS failed (%s); retrying in %ds.", exc, interval)

    return interval
