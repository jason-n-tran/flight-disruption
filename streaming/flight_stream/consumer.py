"""Consumer: NATS ``flight.positions`` -> api_contract payload -> Valkey cache.

Subscribes to the JetStream subject, normalizes each snapshot into the exact
``/api/live/positions`` shape, and writes it to Valkey under the live key (short
TTL) plus the cached fallback key (long TTL). The serving API reads these keys
directly — the consumer is the only writer.
"""

from __future__ import annotations

import asyncio
import json
import logging

from .config import StreamSettings
from .nats_io import connect_jetstream, ensure_stream
from .transform import snapshot_to_payload
from .valkey_io import make_valkey, write_positions

log = logging.getLogger("flight_stream.consumer")


async def run_consumer(
    settings: StreamSettings,
    *,
    stop: asyncio.Event | None = None,
) -> None:
    """Subscribe and write each incoming snapshot to Valkey until ``stop`` set."""
    stop = stop or asyncio.Event()
    valkey = make_valkey(settings)
    nc, js = await connect_jetstream(settings)
    await ensure_stream(js, settings)

    async def _on_message(msg) -> None:
        await _handle_message(msg, settings, valkey)

    # Durable push subscription: a restarted consumer resumes; deliver_policy
    # "last" means a fresh consumer immediately gets the most recent snapshot.
    sub = await js.subscribe(
        settings.subject,
        durable="flight_positions_writer",
        cb=_on_message,
    )
    log.info("Consumer subscribed to %s -> Valkey.", settings.subject)

    try:
        await stop.wait()
    finally:
        try:
            await sub.unsubscribe()
        except Exception as exc:  # noqa: BLE001
            log.warning("Unsubscribe failed: %s", exc)
        try:
            await nc.drain()
        except Exception as exc:  # noqa: BLE001
            log.warning("NATS drain failed on shutdown: %s", exc)


async def _handle_message(msg, settings: StreamSettings, valkey) -> None:
    """Transform one NATS message and persist it. Never raises (ack regardless).

    A poison/garbled message is logged and acked so it doesn't wedge the stream;
    the next valid snapshot supersedes it anyway (this is a last-value cache).
    """
    try:
        raw = json.loads(msg.data.decode("utf-8"))
        payload = snapshot_to_payload(raw, source="live")
        write_positions(valkey, payload, settings)
    except Exception as exc:  # noqa: BLE001
        log.warning("Failed to handle snapshot message (%s); acking and skipping.", exc)
    finally:
        try:
            await msg.ack()
        except Exception:  # noqa: BLE001
            pass
