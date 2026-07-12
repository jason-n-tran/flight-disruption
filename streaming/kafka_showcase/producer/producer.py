"""Producer: OpenSky US-bbox snapshots -> Kafka topic ``flight-positions``.

This is the SHOWCASE ingestion path (the live demo uses NATS elsewhere). It
reuses ``flight_ingest`` for the OpenSky HTTP client, auth, and the state-vector
parser, then fans each aircraft state out as an individual JSON Kafka message
keyed by ``icao24``. Spark Structured Streaming (``spark_app/streaming_job.py``)
consumes the topic and computes live airport-congestion windows.

Design notes
------------
* **Keyed by icao24** so all states for an aircraft share a partition (ordering).
* **Event-time carried in the payload** (``event_ts`` = OpenSky snapshot time) so
  Spark watermarks/windows on event-time, not processing-time.
* **Robust loop**: every network/broker error is logged and the loop continues;
  the producer is meant to be left running for a screenshot session.

Run::

    python -m producer.producer            # from kafka_showcase/, forever
    MAX_POLLS=5 python -m producer.producer # bounded run for a screenshot
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import time

from flight_ingest.config import load_settings as load_ingest_settings
from flight_ingest.opensky import fetch_snapshot

from .config import ProducerSettings, load_settings
from .messages import iter_messages

# Make prints/log unicode-safe on the Windows console (per task spec).
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("kafka_showcase.producer")


def _make_kafka_producer(settings: ProducerSettings):
    """Build a ``kafka-python`` ``KafkaProducer``.

    Imported lazily so the module imports (and unit tests on ``messages``) work
    without ``kafka-python`` or a broker installed.
    """
    from kafka import KafkaProducer  # type: ignore

    return KafkaProducer(
        bootstrap_servers=settings.bootstrap_servers.split(","),
        client_id=settings.client_id,
        # Values/keys are already bytes from iter_messages; identity serializers.
        key_serializer=None,
        value_serializer=None,
        acks="all",
        linger_ms=50,         # small batch window — many small position msgs
        retries=3,
        request_timeout_ms=30000,
    )


def publish_snapshot(producer, settings: ProducerSettings, snapshot: dict) -> int:
    """Publish every aircraft in a snapshot as a keyed Kafka message.

    Returns the number of messages sent. The snapshot is the api_contract dict
    from ``flight_ingest.opensky.fetch_snapshot`` (``as_of`` + ``aircraft``).
    """
    event_ts = int(snapshot.get("as_of") or time.time())
    pairs = iter_messages(snapshot.get("aircraft") or [], event_ts)
    for key, value in pairs:
        producer.send(settings.topic, key=key, value=value)
    producer.flush()
    return len(pairs)


def run(settings: ProducerSettings | None = None) -> None:
    """Run the poll -> publish loop until interrupted (or ``MAX_POLLS`` reached)."""
    settings = settings or load_settings()
    ingest_settings = load_ingest_settings()

    log.info(
        "Producer up: bootstrap=%s topic=%s poll=%.0fs max_polls=%s",
        settings.bootstrap_servers,
        settings.topic,
        settings.poll_interval_seconds,
        settings.max_polls or "inf",
    )

    producer = _make_kafka_producer(settings)

    stop = {"flag": False}

    def _handle_signal(signum, _frame):
        log.info("Signal %s received — finishing current cycle and exiting.", signum)
        stop["flag"] = True

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    polls = 0
    try:
        while not stop["flag"]:
            try:
                snapshot = fetch_snapshot(ingest_settings)
                sent = publish_snapshot(producer, settings, snapshot)
                log.info(
                    "Snapshot @%s: %d aircraft -> %d messages on '%s'.",
                    snapshot.get("as_of"),
                    snapshot.get("count"),
                    sent,
                    settings.topic,
                )
            except Exception as exc:  # noqa: BLE001 — log + retry, never crash
                log.warning("Poll/publish cycle failed (%s); retrying next cycle.", exc)

            polls += 1
            if settings.max_polls and polls >= settings.max_polls:
                log.info("Reached MAX_POLLS=%d — stopping.", settings.max_polls)
                break

            # Interruptible sleep so Ctrl-C exits promptly.
            slept = 0.0
            while slept < settings.poll_interval_seconds and not stop["flag"]:
                time.sleep(min(1.0, settings.poll_interval_seconds - slept))
                slept += 1.0
    finally:
        try:
            producer.flush()
            producer.close(timeout=10)
        except Exception as exc:  # noqa: BLE001
            log.warning("Producer close failed: %s", exc)
        log.info("Producer stopped after %d poll(s).", polls)


def main() -> int:
    run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
