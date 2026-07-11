"""Pure (de)serialization for the ``flight-positions`` Kafka topic.

Kept broker-free so the message shape is unit-testable without a running Kafka
cluster. The producer (``producer.py``) and the Spark job's JSON schema
(``spark_app/streaming_job.py``) must agree on exactly the fields built here.

The message is a flattened, per-aircraft event derived from the api_contract
aircraft shape produced by ``flight_ingest.opensky.parse_states_payload`` —
plus the event-time (``event_ts``, unix seconds) carried from the OpenSky
snapshot ``time`` so Spark can do *event-time* windowing + watermarking.
"""

from __future__ import annotations

import json
from typing import Any, Iterable

# The exact field set on every Kafka message value. Spark's from_json schema in
# streaming_job.py mirrors this 1:1 — change them together.
MESSAGE_FIELDS = (
    "icao24",      # str  — aircraft id, also the Kafka message KEY
    "callsign",    # str | None
    "lat",         # float
    "lon",         # float
    "altitude",    # float | None (metres)
    "velocity",    # float | None (m/s)
    "heading",     # float | None (deg)
    "on_ground",   # bool
    "event_ts",    # int  — unix seconds, snapshot time (event-time)
)


def build_message(aircraft: dict[str, Any], event_ts: int) -> dict[str, Any]:
    """Project one parsed aircraft dict + snapshot time into a Kafka message.

    ``aircraft`` is one entry from ``parse_states_payload`` (api_contract shape).
    ``event_ts`` is the OpenSky snapshot's ``time`` (unix seconds) — the same for
    every aircraft in a snapshot; this is the event-time Spark watermarks on.
    """
    msg = {field: aircraft.get(field) for field in MESSAGE_FIELDS if field != "event_ts"}
    msg["event_ts"] = int(event_ts)
    return msg


def iter_messages(
    aircraft_list: Iterable[dict[str, Any]], event_ts: int
) -> list[tuple[bytes, bytes]]:
    """Build ``(key, value)`` byte tuples ready for ``KafkaProducer.send``.

    Key = icao24 (UTF-8) so all states for one aircraft land on one partition,
    giving per-aircraft ordering. Aircraft with no icao24 are skipped (cannot
    key them; they are noise for congestion counts anyway).
    """
    out: list[tuple[bytes, bytes]] = []
    for ac in aircraft_list:
        icao24 = ac.get("icao24")
        if not icao24:
            continue
        msg = build_message(ac, event_ts)
        key = str(icao24).encode("utf-8")
        value = json.dumps(msg, separators=(",", ":")).encode("utf-8")
        out.append((key, value))
    return out


def deserialize(value: bytes | str) -> dict[str, Any]:
    """Inverse of the value serialization (handy for tests / a debug consumer)."""
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    return json.loads(value)
