"""NATS JetStream connection + stream setup helpers.

Isolated so producer/consumer share one connection recipe and tests can mock a
single seam (``connect_jetstream``).
"""

from __future__ import annotations

import logging

import nats
from nats.js.api import RetentionPolicy, StreamConfig

from .config import StreamSettings

log = logging.getLogger("flight_stream.nats")


async def connect_jetstream(settings: StreamSettings):
    """Connect to NATS and return ``(nc, js)``.

    Reconnection is delegated to nats-py (it auto-reconnects with backoff); we
    just log connection lifecycle events.
    """

    async def _disconnected():
        log.warning("NATS disconnected — nats-py will attempt to reconnect.")

    async def _reconnected():
        log.info("NATS reconnected.")

    async def _error(exc):
        log.warning("NATS error: %s", exc)

    nc = await nats.connect(
        settings.nats_url,
        max_reconnect_attempts=-1,  # retry forever
        disconnected_cb=_disconnected,
        reconnected_cb=_reconnected,
        error_cb=_error,
    )
    js = nc.jetstream()
    log.info("Connected to NATS at %s.", settings.nats_url)
    return nc, js


async def ensure_stream(js, settings: StreamSettings) -> None:
    """Idempotently create the JetStream stream bound to the subject.

    ``max_msgs=1`` keeps only the latest snapshot: this is a "last value" cache
    feed, not an event log, so we never accumulate stale snapshots. A late-
    starting consumer still gets the most recent snapshot on attach.
    """
    config = StreamConfig(
        name=settings.stream_name,
        subjects=[settings.subject],
        retention=RetentionPolicy.LIMITS,
        max_msgs=1,
    )
    try:
        await js.add_stream(config)
        log.info("Created JetStream stream %s (subject %s).", settings.stream_name, settings.subject)
    except Exception as exc:  # noqa: BLE001 — already-exists is fine; log others
        # nats-py raises on existing stream with differing config; for a stable
        # config this is effectively idempotent. Log and proceed.
        log.info("ensure_stream: stream likely exists (%s).", exc)
